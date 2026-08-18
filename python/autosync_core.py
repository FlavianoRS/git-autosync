import json
import os
import platform
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"

CONFIG_DIR = Path.home() / ".git-autosync"
CONFIG_FILE = CONFIG_DIR / "config.json"
STATUS_FILE = CONFIG_DIR / "status.json"
LOG_FILE = CONFIG_DIR / "autosync.log"

CRON_MARKER = "# git-autosync"

DEFAULT_CONFIG = {
    "schedules": ["17:30"],
    "targets": [],
    "taskName": "GitAutoSyncPy",
    "trayEnabled": False,
}


def ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config():
    ensure_config_dir()
    if not CONFIG_FILE.exists():
        cfg = dict(DEFAULT_CONFIG)
        save_config(cfg)
        return cfg
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def save_config(cfg):
    ensure_config_dir()
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def load_status():
    ensure_config_dir()
    if not STATUS_FILE.exists():
        return {"lastSyncRun": None, "repos": {}}
    return json.loads(STATUS_FILE.read_text(encoding="utf-8"))


def save_status(status):
    ensure_config_dir()
    STATUS_FILE.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")


def write_log(repo_path, message):
    ensure_config_dir()
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} [{repo_path}] {message}"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def _run(args, cwd=None, timeout=None):
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )


def resolve_targets(targets):
    paths = []
    for t in targets:
        if not t.get("enabled", True):
            continue
        p = Path(t["path"])
        if t.get("type") == "root":
            if p.is_dir():
                for child in sorted(p.iterdir()):
                    if child.is_dir() and (child / ".git").exists():
                        paths.append(str(child))
        else:
            paths.append(str(p))
    return paths


def sync_repo(repo_path):
    """Returns dict: path, time, success, hadChanges, message."""
    result = {
        "path": repo_path,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "success": False,
        "hadChanges": False,
        "message": "",
    }

    if not (Path(repo_path) / ".git").exists():
        result["message"] = "nao e repositorio git, pulando"
        write_log(repo_path, f"ERRO: {result['message']}.")
        return result

    try:
        status = _run(["git", "status", "--porcelain"], cwd=repo_path)
        if not status.stdout.strip():
            result["success"] = True
            result["message"] = "sem alteracoes, nada a fazer"
            write_log(repo_path, result["message"])
            return result

        result["hadChanges"] = True
        _run(["git", "add", "-A"], cwd=repo_path)

        diff = _run(["git", "diff", "--staged"], cwd=repo_path).stdout
        if len(diff) > 12000:
            diff = diff[:12000] + "\n...(diff truncado)..."

        prompt = (
            "Gere APENAS uma mensagem de commit no padrao Conventional Commits "
            "(feat:, fix:, chore:, docs:, refactor:, etc), em portugues, uma linha, "
            "maximo 72 caracteres, baseada no diff abaixo. Responda SOMENTE com a "
            f"mensagem, sem aspas, sem explicacao, sem markdown.\n\n{diff}"
        )

        commit_msg = None
        claude_bin = shutil.which("claude")
        if claude_bin:
            try:
                proc = _run(
                    [claude_bin, "-p", prompt, "--output-format", "text",
                     "--disallowedTools", "Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch"],
                    cwd=repo_path, timeout=120,
                )
                commit_msg = proc.stdout.strip()
            except Exception:
                commit_msg = None

        if not commit_msg:
            commit_msg = f"chore: auto-commit {datetime.now():%Y-%m-%d %H:%M}"
            write_log(repo_path, "aviso: claude nao retornou mensagem, usando fallback.")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as tmp:
            tmp.write(commit_msg)
            tmp_path = tmp.name
        try:
            _run(["git", "commit", "-F", tmp_path], cwd=repo_path)
        finally:
            os.unlink(tmp_path)
        write_log(repo_path, f"commit local ok: {commit_msg}")

        push = _run(["git", "push"], cwd=repo_path)
        if push.returncode == 0:
            result["success"] = True
            result["message"] = f"commit: {commit_msg} | push ok"
            write_log(repo_path, "push ok.")
        else:
            result["success"] = False
            push_err = (push.stderr or push.stdout).strip()
            result["message"] = f"commit: {commit_msg} | push FALHOU: {push_err}"
            write_log(repo_path, f"AVISO: push falhou -> {push_err}")
    except Exception as exc:
        result["message"] = f"erro inesperado: {exc}"
        write_log(repo_path, f"ERRO: {exc}")

    return result


def run_all():
    cfg = load_config()
    paths = resolve_targets(cfg.get("targets", []))
    status = load_status()
    repos = status.get("repos", {})
    for p in paths:
        r = sync_repo(p)
        repos[p] = {
            "lastRun": r["time"],
            "success": r["success"],
            "hadChanges": r["hadChanges"],
            "message": r["message"],
        }
    status["repos"] = repos
    status["lastSyncRun"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_status(status)
    return status


# ---- scheduler (OS-native recurring execution) ----

def _sync_command_line(sync_target):
    """sync_target: path to a frozen exe, or a .py script to run with current interpreter."""
    p = Path(sync_target)
    if p.suffix.lower() == ".py":
        import sys
        return f'"{sys.executable}" "{p}"'
    return f'"{p}"'


def install_schedule(sync_target, schedules=None, task_name=None):
    cfg = load_config()
    schedules = schedules or cfg.get("schedules", ["17:30"])
    task_name = task_name or cfg.get("taskName", "GitAutoSyncPy")
    cmd = _sync_command_line(sync_target)

    if IS_WINDOWS:
        uninstall_schedule(task_name)
        for i, t in enumerate(schedules):
            name = f"{task_name}_{i}"
            subprocess.run(
                ["schtasks", "/Create", "/TN", name, "/TR", cmd,
                 "/SC", "DAILY", "/ST", t, "/F"],
                capture_output=True, text=True,
            )
    else:
        existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        lines = [l for l in existing.stdout.splitlines() if CRON_MARKER not in l]
        for t in schedules:
            hh, mm = t.split(":")
            lines.append(f"{int(mm)} {int(hh)} * * * {cmd} {CRON_MARKER}")
        new_crontab = "\n".join(lines) + "\n"
        subprocess.run(["crontab", "-"], input=new_crontab, text=True)


def uninstall_schedule(task_name=None):
    cfg = load_config()
    task_name = task_name or cfg.get("taskName", "GitAutoSyncPy")
    if IS_WINDOWS:
        for i in range(20):
            subprocess.run(["schtasks", "/Delete", "/TN", f"{task_name}_{i}", "/F"],
                            capture_output=True, text=True)
    else:
        existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        lines = [l for l in existing.stdout.splitlines() if CRON_MARKER not in l]
        new_crontab = "\n".join(lines) + ("\n" if lines else "")
        subprocess.run(["crontab", "-"], input=new_crontab, text=True)


# ---- autostart (tray icon on login) ----

def _windows_startup_dir():
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def enable_tray_autostart(tray_target):
    """tray_target: path to frozen tray exe, or a .py script to run with pythonw."""
    p = Path(tray_target)
    if IS_WINDOWS:
        startup = _windows_startup_dir()
        startup.mkdir(parents=True, exist_ok=True)
        bat_path = startup / "GitAutoSyncTray.bat"
        if p.suffix.lower() == ".py":
            import sys
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            runner = pythonw if pythonw.exists() else Path(sys.executable)
            bat_path.write_text(f'@echo off\nstart "" "{runner}" "{p}" --tray\n', encoding="utf-8")
        else:
            bat_path.write_text(f'@echo off\nstart "" "{p}" --tray\n', encoding="utf-8")
    else:
        autostart_dir = Path.home() / ".config" / "autostart"
        autostart_dir.mkdir(parents=True, exist_ok=True)
        desktop_path = autostart_dir / "git-autosync-tray.desktop"
        if p.suffix.lower() == ".py":
            import sys
            exec_line = f'{sys.executable} "{p}" --tray'
        else:
            exec_line = f'"{p}" --tray'
        desktop_path.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Git AutoSync Tray\n"
            f"Exec={exec_line}\n"
            "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
    cfg = load_config()
    cfg["trayEnabled"] = True
    save_config(cfg)


def disable_tray_autostart():
    if IS_WINDOWS:
        bat_path = _windows_startup_dir() / "GitAutoSyncTray.bat"
        if bat_path.exists():
            bat_path.unlink()
    else:
        desktop_path = Path.home() / ".config" / "autostart" / "git-autosync-tray.desktop"
        if desktop_path.exists():
            desktop_path.unlink()
    cfg = load_config()
    cfg["trayEnabled"] = False
    save_config(cfg)
