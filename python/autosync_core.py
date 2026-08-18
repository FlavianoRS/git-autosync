import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
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


def _no_window_flags():
    """Suppresses the console flash Windows shows for each subprocess spawned
    from a windowed (GUI/pythonw) process."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WINDOWS else {}


def _run(args, cwd=None, timeout=None):
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
        **_no_window_flags(),
    )


def resolve_targets(targets):
    return [d["path"] for d in resolve_targets_detailed(targets)]


def resolve_targets_detailed(targets, skip_disabled=True):
    """Como resolve_targets(), mas devolve um dict por repositorio real com
    sourceType/sourcePath/enabled - usado pela GUI pra saber se um repo veio
    de um alvo 'repo' direto (editavel/removivel individualmente) ou de
    dentro de um alvo 'root' (herdado - quem controla e a pasta-raiz, nao o
    repo). skip_disabled=False inclui tambem os alvos desativados (a GUI
    precisa disso pra mostrar o botao "Ativar"; commit_all/push_all/run_all
    usam o default, que so considera os habilitados)."""
    resolved = []
    for t in targets:
        enabled = t.get("enabled", True)
        if skip_disabled and not enabled:
            continue
        p = Path(t["path"])
        if t.get("type") == "root":
            excluded = set(t.get("exclude", []))
            if p.is_dir():
                for child in sorted(p.iterdir()):
                    if str(child) in excluded:
                        continue
                    if child.is_dir() and (child / ".git").exists():
                        resolved.append({
                            "path": str(child),
                            "sourceType": "root",
                            "sourcePath": str(p),
                            "enabled": enabled,
                        })
        else:
            resolved.append({
                "path": str(p),
                "sourceType": "repo",
                "sourcePath": str(p),
                "enabled": enabled,
            })
    return resolved


def find_owning_root(root_or_repo_path):
    """Acha o alvo tipo 'root' que e pai direto de root_or_repo_path (usado
    pra excluir/incluir um repo especifico de dentro de uma pasta-raiz)."""
    cfg = load_config()
    p = Path(root_or_repo_path).resolve()
    for t in cfg.get("targets", []):
        if t.get("type") == "root" and Path(t["path"]).resolve() == p.parent:
            return t["path"]
    return None


def exclude_repo_from_root(root_path, repo_path):
    """Adiciona repo_path na lista de exclusao do alvo root em root_path -
    resolve_targets_detailed() passa a pular esse repo. Nao afeta o
    repositorio em si, so o que o autosync considera dentro daquela pasta."""
    cfg = load_config()
    for t in cfg["targets"]:
        if t.get("type") == "root" and t["path"] == root_path:
            excluded = t.setdefault("exclude", [])
            if repo_path not in excluded:
                excluded.append(repo_path)
            save_config(cfg)
            return True
    return False


def include_repo_in_root(root_path, repo_path):
    """Desfaz exclude_repo_from_root()."""
    cfg = load_config()
    for t in cfg["targets"]:
        if t.get("type") == "root" and t["path"] == root_path:
            excluded = t.get("exclude", [])
            if repo_path in excluded:
                excluded.remove(repo_path)
                save_config(cfg)
            return True
    return False


def commit_repo(repo_path):
    """Stages and commits pending changes (no push). Returns dict: path, time,
    success, hadChanges, message, commitHash."""
    result = {
        "path": repo_path,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "success": False,
        "hadChanges": False,
        "message": "",
        "commitHash": None,
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

        result["success"] = True
        result["message"] = f"commit: {commit_msg}"
        result["commitHash"] = _run(["git", "rev-parse", "HEAD"], cwd=repo_path).stdout.strip() or None
        write_log(repo_path, f"commit local ok: {commit_msg}")
    except Exception as exc:
        result["message"] = f"erro inesperado: {exc}"
        write_log(repo_path, f"ERRO: {exc}")

    return result


def push_repo(repo_path):
    """Pushes whatever is already committed locally. Returns dict: path, time,
    success, message."""
    result = {
        "path": repo_path,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "success": False,
        "message": "",
    }

    if not (Path(repo_path) / ".git").exists():
        result["message"] = "nao e repositorio git, pulando"
        write_log(repo_path, f"ERRO: {result['message']}.")
        return result

    try:
        push = _run(["git", "push"], cwd=repo_path)
        if push.returncode == 0:
            result["success"] = True
            result["message"] = "push ok"
            write_log(repo_path, "push ok.")
        else:
            push_err = (push.stderr or push.stdout).strip()
            result["message"] = f"push FALHOU: {push_err}"
            write_log(repo_path, f"AVISO: push falhou -> {push_err}")
    except Exception as exc:
        result["message"] = f"erro inesperado: {exc}"
        write_log(repo_path, f"ERRO: {exc}")

    return result


def has_remote(repo_path):
    result = _run(["git", "remote"], cwd=repo_path)
    return bool(result.stdout.strip())


def _kill_process_tree(pid):
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                        capture_output=True, **_no_window_flags())
    else:
        import signal
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except Exception:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass


def _run_hard_timeout(args, cwd, timeout):
    """Como _run(), mas garante que o timeout e respeitado de verdade.

    git (no Windows, pra remotos http/https) as vezes deixa um processo
    auxiliar de rede que herda os pipes de stdout/stderr - matar so o
    processo principal (o que subprocess.run+timeout faz) nao fecha esses
    pipes, e o communicate() final fica esperando o auxiliar por conta
    propria (~20s+ de timeout de conexao do Windows), ignorando na pratica
    o timeout pedido. Aqui, ao expirar, mata a arvore de processos inteira
    antes de tentar ler a saida de novo."""
    proc = subprocess.Popen(
        args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", **_no_window_flags(),
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc.pid)
        try:
            stdout, stderr = proc.communicate(timeout=3)
        except Exception:
            stdout, stderr = "", "timeout"
        return subprocess.CompletedProcess(args, -1, stdout, stderr)


def check_remote_reachable(repo_path, timeout=8):
    """True/False if the repo has a remote and it is/isn't reachable right
    now (network + credenciais). None if the repo has no remote configured
    at all (nada pra verificar, nada pra fazer push)."""
    if not has_remote(repo_path):
        return None
    try:
        result = _run_hard_timeout(["git", "ls-remote", "--exit-code", "origin"], cwd=repo_path, timeout=timeout)
    except Exception:
        return False
    return result.returncode == 0


def _resolve_push_availability(repo_path, push_decider):
    """Checa se da pra tentar um push agora, com retry opcional.

    Retorna (proceed, reachable). `reachable` e o resultado mais recente de
    check_remote_reachable() (True/False/None). `proceed` e False so quando
    o remoto esta configurado e inacessivel E quem decide (push_decider, ou
    o retry automatico sem decider) desistiu.

    - push_decider(repo_path), quando informado, e chamado a cada tentativa
      falha - deve retornar True pra tentar de novo (reverifica a conexao)
      ou False pra desistir.
    - sem push_decider (uso nao interativo, ex: tarefa agendada), tenta de
      novo silenciosamente algumas vezes e desiste se continuar sem acesso -
      nunca fica esperando input pra sempre."""
    reachable = check_remote_reachable(repo_path)
    if reachable is not False:
        return True, reachable

    if push_decider is not None:
        while reachable is False and push_decider(repo_path):
            reachable = check_remote_reachable(repo_path)
    else:
        for _ in range(2):
            time.sleep(2)
            reachable = check_remote_reachable(repo_path)
            if reachable is not False:
                break

    return reachable is not False, reachable


def push_repo_checked(repo_path, push_decider=None):
    """Como push_repo(), mas primeiro verifica se o remoto esta acessivel
    (ver _resolve_push_availability) - evita disparar um `git push` que ja
    se sabe de antemao que vai falhar, e da chance de tentar de novo antes
    de desistir. Mesmo formato de retorno de push_repo()."""
    proceed, _ = _resolve_push_availability(repo_path, push_decider)
    if not proceed:
        write_log(repo_path, "aviso: push cancelado, remoto inacessivel.")
        return {
            "path": repo_path,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "success": False,
            "message": "push cancelado (remoto inacessivel)",
        }
    return push_repo(repo_path)


def sync_repo(repo_path, push_decider=None):
    """Commit followed by push — used pela tarefa agendada e pelo comando
    `sync`. Returns dict: path, time, success, hadChanges, message.

    Antes de commitar, verifica se o remoto esta acessivel (ver
    _resolve_push_availability) - se nao estiver e ninguem topar tentar de
    novo, segue so commitando, sem dar push nessa rodada."""
    proceed, _ = _resolve_push_availability(repo_path, push_decider)
    skip_push = not proceed
    if skip_push:
        write_log(repo_path, "aviso: remoto inacessivel, commitando sem dar push nesta rodada.")

    commit_result = commit_repo(repo_path)
    if not commit_result["success"] or not commit_result["hadChanges"] or skip_push:
        result = {k: commit_result[k] for k in ("path", "time", "success", "hadChanges", "message")}
        result["pushed"] = False
        if skip_push and commit_result["success"]:
            result["message"] += " | push pulado (remoto inacessivel)"
        return result

    push_result = push_repo(repo_path)
    return {
        "path": repo_path,
        "time": push_result["time"],
        "success": push_result["success"],
        "hadChanges": True,
        "pushed": push_result["success"],
        "message": f"{commit_result['message']} | {push_result['message']}",
    }


def _update_status_entry(status, repo_path, **fields):
    repos = status.setdefault("repos", {})
    entry = repos.setdefault(repo_path, {})
    entry.update(fields)
    return entry


def run_all(push_decider=None):
    """Commit + push every enabled target — used by the scheduled task and
    the `run-now` CLI command. Ver sync_repo() pro que push_decider faz."""
    cfg = load_config()
    paths = resolve_targets(cfg.get("targets", []))
    status = load_status()
    for p in paths:
        r = sync_repo(p, push_decider=push_decider)
        _update_status_entry(
            status, p,
            lastRun=r["time"], success=r["success"],
            hadChanges=r["hadChanges"], message=r["message"],
        )
        if r.get("pushed"):
            _update_status_entry(status, p, lastPush=r["time"])
    status["lastSyncRun"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_status(status)
    return status


def commit_all():
    """Commit-only pass over every enabled target (no push) — used by the
    manual 'Commitar tudo' action in the GUI/CLI."""
    cfg = load_config()
    paths = resolve_targets(cfg.get("targets", []))
    status = load_status()
    for p in paths:
        r = commit_repo(p)
        _update_status_entry(
            status, p,
            lastRun=r["time"], success=r["success"],
            hadChanges=r["hadChanges"], message=r["message"],
        )
    status["lastSyncRun"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_status(status)
    return status


def push_all(push_decider=None):
    """Push-only pass over every enabled target — used by the manual
    'Push tudo' action in the GUI/CLI. Ver push_repo_checked() pro que
    push_decider faz."""
    cfg = load_config()
    paths = resolve_targets(cfg.get("targets", []))
    status = load_status()
    for p in paths:
        r = push_repo_checked(p, push_decider=push_decider)
        if r["success"]:
            _update_status_entry(status, p, lastPush=r["time"], message=r["message"])
        else:
            _update_status_entry(status, p, message=r["message"])
    save_status(status)
    return status


def has_pending_changes(repo_path):
    """True if the working tree has uncommitted changes (git status --porcelain)."""
    status = _run(["git", "status", "--porcelain"], cwd=repo_path)
    return bool(status.stdout.strip())


def get_unpushed_count(repo_path):
    """Number of local commits not yet on the upstream branch, or None if the
    branch has no upstream configured."""
    upstream = _run(["git", "rev-parse", "--abbrev-ref", "@{u}"], cwd=repo_path)
    if upstream.returncode != 0:
        return None
    count = _run(["git", "rev-list", "--count", "@{u}..HEAD"], cwd=repo_path)
    try:
        return int(count.stdout.strip())
    except ValueError:
        return None


def get_commit_log(repo_path, since=None, limit=50):
    """Returns [{hash, date, message}, ...], newest first. `since` is an ISO
    date/datetime string understood by `git log --since`."""
    args = ["git", "log", f"--format=%H|%cI|%s", f"-n{limit}"]
    if since:
        args.append(f"--since={since}")
    proc = _run(args, cwd=repo_path)
    if proc.returncode != 0:
        return []
    commits = []
    for line in proc.stdout.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            commits.append({"hash": parts[0], "date": parts[1], "message": parts[2]})
    return commits


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
                capture_output=True, text=True, **_no_window_flags(),
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
                            capture_output=True, text=True, **_no_window_flags())
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
