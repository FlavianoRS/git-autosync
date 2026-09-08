import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import autosync_core as core
import runtime_safety
import scheduler
import credentials
import run_sync
import app


class GitIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        state = self.base / "state"
        for key, value in {"CONFIG_DIR": state, "CONFIG_FILE": state / "config.json",
                           "STATUS_FILE": state / "status.json", "LOG_FILE": state / "autosync.log"}.items():
            p = patch.object(core, key, value)
            p.start()
            self.addCleanup(p.stop)
        # Never inherit user hooks, signing, credential helpers or Git configuration.
        env = patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        env.start()
        self.addCleanup(env.stop)
        self.git("init", "-b", "main")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        (self.repo / "a.txt").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-m", "initial")

    def git(self, *args, cwd=None):
        r = subprocess.run(["git", *args], cwd=cwd or self.repo, text=True,
                           capture_output=True, timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_commit_and_preserve_worktree(self):
        (self.repo / "a.txt").write_text("changed\n")
        result = core.commit_repo(str(self.repo), message="fix: change")
        self.assertTrue(result["success"], result)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("log", "-1", "--format=%s"), "fix: change")

    def test_hook_rejection_preserves_stage_and_head(self):
        (self.repo / "a.txt").write_text("staged\n")
        self.git("add", ".")
        (self.repo / "a.txt").write_text("unstaged\n")
        before = (self.repo / ".git" / "index").read_bytes()
        head = self.git("rev-parse", "HEAD")
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        result = core.commit_repo(str(self.repo), message="must fail")
        self.assertFalse(result["success"], result)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        # Git status may refresh stat fields; staged contents must be identical.
        self.assertEqual(self.git("show", ":a.txt"), "staged")
        self.assertEqual((self.repo / "a.txt").read_text(), "unstaged\n")

    def test_preview_cancel_preserves_partial_stage(self):
        (self.repo / "a.txt").write_text("staged\n")
        self.git("add", ".")
        (self.repo / "a.txt").write_text("unstaged\n")
        result = core.stage_and_generate_message(str(self.repo))
        self.assertIsNone(result["error"], result)
        core.unstage(str(self.repo))
        self.assertEqual(self.git("show", ":a.txt"), "staged")
        self.assertEqual((self.repo / "a.txt").read_text(), "unstaged\n")

    def test_review_detects_changed_content(self):
        (self.repo / "a.txt").write_text("first\n")
        core.stage_and_generate_message(str(self.repo))
        (self.repo / "a.txt").write_text("second\n")
        result = core.finalize_commit(str(self.repo), "reviewed first")
        self.assertFalse(result["success"], result)
        self.assertIn("revise novamente", result["message"])
        self.assertEqual(self.git("show", ":a.txt"), "base")

    def test_clean_repo_pushes_pending_commits_to_empty_remote(self):
        remote = self.base / "remote.git"
        self.git("init", "--bare", str(remote))
        self.git("remote", "add", "origin", str(remote))
        result = core.sync_repo(str(self.repo))
        self.assertTrue(result["success"], result)
        self.assertFalse(result["hadChanges"])
        self.assertEqual(self.git("rev-parse", "HEAD"), self.git("rev-parse", "refs/heads/main", cwd=remote))

    def test_offline_is_pending_not_success(self):
        (self.repo / "a.txt").write_text("offline\n")
        with patch.object(core, "_resolve_push_availability", return_value=(False, False)):
            result = core.sync_repo(str(self.repo), message="offline")
        self.assertFalse(result["success"])
        self.assertFalse(result["pushed"])
        self.assertEqual(result["state"], "pending_push")
        self.assertEqual(self.git("log", "-1", "--format=%s"), "offline")

    def test_sensitive_file_blocks_commit(self):
        (self.repo / ".env").write_text("PASSWORD=example")
        result = core.commit_repo(str(self.repo), message="must fail")
        self.assertFalse(result["success"])
        self.assertIn("sensivel", result["message"])

    def test_merge_in_progress_blocks_commit(self):
        (self.repo / ".git" / "MERGE_HEAD").write_text(self.git("rev-parse", "HEAD"))
        (self.repo / "a.txt").write_text("modified")
        result = core.commit_repo(str(self.repo), message="must fail")
        self.assertFalse(result["success"])
        self.assertIn("andamento", result["message"])

    def test_stale_config_merges_independent_fields(self):
        a, b = core.load_config(), core.load_config()
        a["theme"] = "dark"
        core.save_config(a)
        b["aiAgent"] = "codex"
        core.save_config(b)
        self.assertEqual(core.load_config()["theme"], "dark")
        self.assertEqual(core.load_config()["aiAgent"], "codex")

    def test_stale_same_field_rejected(self):
        a, b = core.load_config(), core.load_config()
        a["theme"] = "dark"
        b["theme"] = "light"
        core.save_config(a)
        with self.assertRaises(RuntimeError):
            core.save_config(b)

    def test_batch_does_not_report_old_repositories(self):
        core.save_status({"repos": {"old": {"success": False}}})
        result = core.run_all()
        self.assertEqual(result["repos"], {})
        self.assertIn("old", core.load_status()["repos"])

    def test_review_confirmation_commits(self):
        (self.repo / "a.txt").write_text("reviewed\n")
        core.stage_and_generate_message(str(self.repo))
        result = core.finalize_commit(str(self.repo), "reviewed")
        self.assertTrue(result["success"], result)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_failed_add_is_not_success(self):
        (self.repo / "a.txt").write_text("changed")
        original = core._run
        def fail_add(args, **kwargs):
            if args[:2] == ["git", "add"]:
                return subprocess.CompletedProcess(args, 1, "", "simulated add failure")
            return original(args, **kwargs)
        with patch.object(core, "_run", side_effect=fail_add):
            result = core.commit_repo(str(self.repo), message="bad")
        self.assertFalse(result["success"])
        self.assertEqual(self.git("show", ":a.txt"), "base")

    def test_upstream_other_than_origin_is_used(self):
        remote = self.base / "remote.git"
        self.git("init", "--bare", str(remote))
        self.git("remote", "add", "company", str(remote))
        self.git("config", "branch.main.remote", "company")
        self.git("config", "branch.main.merge", "refs/heads/delivery")
        result = core.sync_repo(str(self.repo))
        self.assertTrue(result["success"], result)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.git("rev-parse", "refs/heads/delivery", cwd=remote))

    def test_stale_status_preserves_other_repository(self):
        a, b = core.load_status(), core.load_status()
        a["repos"]["one"] = {"success": True}
        b["repos"]["two"] = {"success": False}
        core.save_status(a)
        core.save_status(b)
        self.assertEqual(set(core.load_status()["repos"]), {"one", "two"})

    def test_environment_token_bound_to_host(self):
        with patch.dict(os.environ, {core.GITLAB_TOKEN_ENV: "test-token", "GIT_AUTOSYNC_GITLAB_HOST": "gitlab.example.com"}):
            self.assertIsNone(core.resolve_gitlab_token("other.example.com"))
            self.assertEqual(core.resolve_gitlab_token("gitlab.example.com"), "test-token")

    def test_legacy_token_refused(self):
        cfg = core.load_config()
        cfg["gitlabToken"] = "old-token"
        core.save_config(cfg)
        with patch.dict(os.environ, {core.GITLAB_TOKEN_ENV: ""}), self.assertRaises(RuntimeError):
            core.resolve_gitlab_token("gitlab.example.com")

    def test_scheduler_exit_failure(self):
        with patch.object(core, "run_all", return_value={"repos": {"repo": {"success": False, "message": "pending"}}}), patch.object(core, "notify_windows"):
            self.assertEqual(run_sync.main(), 1)

    def test_cli_failure_exit(self):
        with patch.object(core, "push_repo_checked", return_value={"success": False, "message": "failed"}):
            with self.assertRaises(SystemExit) as raised:
                app.main_args_for_test = None
                app.cmd_push(app.build_parser().parse_args(["push", "--repo", str(self.repo)]))
            self.assertEqual(raised.exception.code, 1)

    def test_ai_disabled_never_calls_runner(self):
        (self.repo / "a.txt").write_text("changed")
        with patch.object(core, "_resolve_agent") as resolve:
            result = core.stage_and_generate_message(str(self.repo))
            self.assertIsNone(result["error"], result)
            resolve.assert_not_called()


class RuntimeTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_dpapi_round_trip(self):
        record = credentials.store("gitlab.example.com", "unit-test-token")
        self.assertNotIn("unit-test-token", json.dumps(record))
        self.assertEqual(credentials.resolve(record, "gitlab.example.com"), "unit-test-token")
        self.assertIsNone(credentials.resolve(record, "other.example.com"))

    def test_windows_scheduler_restores_previous_definition(self):
        old = "<Task>old</Task>"
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "run_sync.py"
            target.touch()
            with patch.object(scheduler, "_task_names", return_value=["test"]), \
                 patch.object(scheduler, "checked", side_effect=[old, RuntimeError("verification failed")]), \
                 patch.object(scheduler, "_xml", return_value="<Task>new</Task>"), \
                 patch.object(scheduler, "_put_task") as put:
                with self.assertRaises(RuntimeError):
                    scheduler.install(target, ["12:00"], "test", True)
                self.assertEqual(put.call_args_list[-1].args, ("test", old))

    def test_cron_preserves_unrelated_jobs(self):
        old = "0 1 * * * backup\n0 2 * * * old # git-autosync\n"
        written = []
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "run sync.py"
            target.touch()
            def read():
                return written[-1] if written else old
            with patch.object(scheduler, "_read_cron", side_effect=read), \
                 patch.object(scheduler, "checked", side_effect=lambda args, input=None: written.append(input)):
                scheduler.install(target, ["12:30"], "test", False)
        self.assertIn("0 1 * * * backup", written[0])
        self.assertNotIn("old # git-autosync", written[0])
        self.assertIn("30 12 * * *", written[0])

    def test_timeout_is_bounded(self):
        with self.assertRaises(RuntimeError):
            runtime_safety.run_process([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.1)

    def test_invalid_schedules_rejected_before_process(self):
        for value in ([], ["24:00"], ["1:30"], ["12:00", "12:00"], ["12:00\nanything"]):
            with self.subTest(value=value), patch.object(scheduler, "run_process") as run:
                with self.assertRaises(ValueError):
                    scheduler.install("missing", value, "test", True)
                run.assert_not_called()

    def test_os_lock_excludes_another_process(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resource.lock"
            with runtime_safety.file_lock(path):
                code = "from runtime_safety import file_lock; import sys\nwith file_lock(sys.argv[1], timeout=0.1): pass"
                result = subprocess.run([sys.executable, "-B", "-c", code, str(path)],
                                        env={**os.environ, "PYTHONPATH": str(Path(core.__file__).parent)},
                                        capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
