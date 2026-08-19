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
    "theme": "system",
    "viewMode": "card",
    "aiAgent": "auto",
    "scheduleAgent": None,
}

AGENT_ORDER = ["claude", "codex", "opencode"]
OPENCODE_SAFE_AGENT = "git-autosync-safe"


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


def _run(args, cwd=None, timeout=None, input=None):
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, input=input,
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
    target_p = Path(root_path)
    for t in cfg["targets"]:
        if t.get("type") == "root" and Path(t["path"]) == target_p:
            excluded = t.setdefault("exclude", [])
            if repo_path not in excluded:
                excluded.append(repo_path)
            save_config(cfg)
            return True
    return False


def include_repo_in_root(root_path, repo_path):
    """Desfaz exclude_repo_from_root()."""
    cfg = load_config()
    target_p = Path(root_path)
    for t in cfg["targets"]:
        if t.get("type") == "root" and Path(t["path"]) == target_p:
            excluded = t.get("exclude", [])
            if repo_path in excluded:
                excluded.remove(repo_path)
                save_config(cfg)
            return True
    return False


# ---- agentes de IA (Claude / Codex / OpenCode) pra gerar a mensagem ----
#
# Os 3 sao chamados com o diff ja embutido no prompt (nunca pedimos pra eles
# "olharem o repo") - assim nenhum precisa de acesso a arquivo/shell pra
# responder, o que evita ter que confiar 100% nas flags de sandbox de cada
# CLI (testado na pratica: o --sandbox read-only do codex, por exemplo, falha
# no Windows se o modelo tenta rodar git sozinho pra ler o diff - com o diff
# ja no prompt, ele nunca tenta).

def _run_claude_prompt(prompt, cwd):
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return None
    try:
        proc = _run(
            [claude_bin, "-p", prompt, "--output-format", "text",
             "--disallowedTools", "Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch"],
            cwd=cwd, timeout=120,
        )
        return proc.stdout.strip() or None
    except Exception:
        return None


def _run_codex_prompt(prompt, cwd):
    """`codex` no Windows e um shim .CMD (instalado via npm) - passar o
    prompt (que tem o diff embutido, varias linhas) como argumento de linha
    de comando corrompe/perde conteudo nesses shims. Manda via stdin (`-`
    como prompt = le da stdin) em vez de argv."""
    codex_bin = shutil.which("codex")
    if not codex_bin:
        return None
    out_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as tmp:
            out_path = tmp.name
        _run(
            [codex_bin, "exec", "--sandbox", "read-only", "--skip-git-repo-check",
             "-C", cwd, "-o", out_path, "-"],
            cwd=cwd, timeout=120, input=prompt,
        )
        text = Path(out_path).read_text(encoding="utf-8", errors="replace").strip()
        return text or None
    except Exception:
        return None
    finally:
        if out_path:
            try:
                os.unlink(out_path)
            except OSError:
                pass


def _ensure_opencode_safe_agent():
    """Garante que ~/.config/opencode/opencode.json tem um agente sem
    write/edit/bash/webfetch pra gerar a mensagem - so complementa o
    arquivo (merge), nunca sobrescreve plugins/mcp/etc que a pessoa ja
    tiver configurado."""
    cfg_path = Path.home() / ".config" / "opencode" / "opencode.json"
    try:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if cfg_path.exists():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        agents = data.setdefault("agent", {})
        if OPENCODE_SAFE_AGENT not in agents:
            agents[OPENCODE_SAFE_AGENT] = {
                "description": "Gera texto a partir de um prompt, sem tocar em arquivos "
                               "nem rodar comandos (usado pelo git-autosync pra gerar "
                               "mensagem de commit).",
                "permission": {"write": "deny", "edit": "deny", "bash": "deny", "webfetch": "deny"},
            }
            cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _run_opencode_prompt(prompt, cwd):
    """`opencode` no Windows tambem e um shim .CMD - mesmo motivo do codex,
    manda o prompt via stdin (sem argumento de mensagem) em vez de argv."""
    opencode_bin = shutil.which("opencode")
    if not opencode_bin:
        return None
    _ensure_opencode_safe_agent()
    try:
        proc = _run(
            [opencode_bin, "run", "--dir", cwd, "--agent", OPENCODE_SAFE_AGENT, "--format", "json"],
            cwd=cwd, timeout=120, input=prompt,
        )
        text = None
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            if event.get("type") == "text":
                part_text = (event.get("part") or {}).get("text")
                if part_text:
                    text = part_text
        return text.strip() if text else None
    except Exception:
        return None


_AGENT_RUNNERS = {
    "claude": _run_claude_prompt,
    "codex": _run_codex_prompt,
    "opencode": _run_opencode_prompt,
}


def _detect_calling_agent():
    """Best-effort: quem esta rodando este processo agora (uma skill do
    Claude Code/Codex/OpenCode, ou nada detectavel). CLAUDECODE=1 e
    confirmado oficialmente; os sinais de Codex/OpenCode sao best-effort -
    se nao baterem, so cai em None (usa a preferencia geral normalmente)."""
    if os.environ.get("CLAUDECODE") == "1":
        return "claude"
    if "CODEX_SANDBOX" in os.environ or "CODEX_SANDBOX_NETWORK_DISABLED" in os.environ:
        return "codex"
    if os.environ.get("OPENCODE") == "1":
        return "opencode"
    return None


def _resolve_agent(explicit=None):
    if explicit:
        return explicit
    cfg = load_config()
    preferred = cfg.get("aiAgent", "auto")
    if preferred and preferred != "auto":
        return preferred
    for name in AGENT_ORDER:
        if shutil.which(name):
            return name
    return None


def pin_schedule_agent_if_created_by_skill():
    """Chamada quando a tarefa agendada e instalada/atualizada (install,
    set-schedule, enable-tray). Se quem esta chamando e um agente
    detectavel E a rodada agendada ainda nao tem um agente fixado, fixa -
    so na primeira vez; nao sobrescreve uma escolha ja feita (por skill ou
    manualmente)."""
    detected = _detect_calling_agent()
    if not detected:
        return
    cfg = load_config()
    if cfg.get("scheduleAgent"):
        return
    cfg["scheduleAgent"] = detected
    save_config(cfg)


def _generate_commit_message(repo_path, agent=None):
    """Assume que ja tem alteracoes staged. Gera a mensagem via o agente
    resolvido (explicito, ou a preferencia configurada, ou o primeiro
    disponivel), com fallback se nenhum estiver disponivel ou responder."""
    diff = _run(["git", "diff", "--staged"], cwd=repo_path).stdout
    if len(diff) > 12000:
        diff = diff[:12000] + "\n...(diff truncado)..."

    prompt = (
        "Gere APENAS uma mensagem de commit no padrao Conventional Commits "
        "(feat:, fix:, chore:, docs:, refactor:, etc), em portugues, uma linha, "
        "maximo 72 caracteres, baseada no diff abaixo. Responda SOMENTE com a "
        f"mensagem, sem aspas, sem explicacao, sem markdown.\n\n{diff}"
    )

    resolved = _resolve_agent(agent)
    commit_msg = None
    if resolved:
        runner = _AGENT_RUNNERS.get(resolved)
        if runner:
            try:
                commit_msg = runner(prompt, repo_path)
            except Exception:
                commit_msg = None

    if not commit_msg:
        commit_msg = f"chore: auto-commit {datetime.now():%Y-%m-%d %H:%M}"
        write_log(repo_path, f"aviso: agente '{resolved}' nao retornou mensagem, usando fallback."
                              if resolved else "aviso: nenhum agente de IA disponivel, usando fallback.")
    return commit_msg


def _do_commit(repo_path, message):
    """Roda `git commit -F <message>` sobre o que ja estiver staged. Retorna
    o hash do commit (ou None)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as tmp:
        tmp.write(message)
        tmp_path = tmp.name
    try:
        _run(["git", "commit", "-F", tmp_path], cwd=repo_path)
    finally:
        os.unlink(tmp_path)
    write_log(repo_path, f"commit local ok: {message}")
    return _run(["git", "rev-parse", "HEAD"], cwd=repo_path).stdout.strip() or None


def stage_and_generate_message(repo_path, agent=None):
    """Da `git add -A` e gera a mensagem de commit (agente/fallback), SEM
    commitar - pra revisar/editar antes de confirmar (dialogo da GUI, ou
    --review no CLI). Retorna dict: hadChanges, message (None se
    hadChanges False), error. Cancelar depois disso? chame unstage()."""
    if not (Path(repo_path) / ".git").exists():
        return {"hadChanges": False, "message": None, "error": "nao e repositorio git"}
    try:
        status = _run(["git", "status", "--porcelain"], cwd=repo_path)
        if not status.stdout.strip():
            return {"hadChanges": False, "message": None, "error": None}
        _run(["git", "add", "-A"], cwd=repo_path)
        return {"hadChanges": True, "message": _generate_commit_message(repo_path, agent=agent), "error": None}
    except Exception as exc:
        return {"hadChanges": False, "message": None, "error": str(exc)}


def unstage(repo_path):
    """Desfaz o `git add -A` de stage_and_generate_message() quando o
    usuario cancela a revisao - deixa o repo como estava antes do clique."""
    _run(["git", "reset"], cwd=repo_path)


def finalize_commit(repo_path, message):
    """Commita o que ja estiver staged (ver stage_and_generate_message) com
    a mensagem informada (revisada/editada ou nao). Mesmo formato de
    retorno de commit_repo()."""
    result = {
        "path": repo_path,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "success": False,
        "hadChanges": True,
        "message": "",
        "commitHash": None,
    }
    try:
        result["commitHash"] = _do_commit(repo_path, message)
        result["success"] = True
        result["message"] = f"commit: {message}"
    except Exception as exc:
        result["message"] = f"erro inesperado: {exc}"
        write_log(repo_path, f"ERRO: {exc}")
    return result


def finalize_sync(repo_path, message, push_decider=None):
    """Como finalize_commit() + push (com a mesma checagem de conexao de
    sync_repo) - usado depois de revisar a mensagem gerada por
    stage_and_generate_message(). Mesmo formato de retorno de sync_repo()."""
    commit_result = finalize_commit(repo_path, message)
    if not commit_result["success"]:
        commit_result["pushed"] = False
        return commit_result

    proceed, _ = _resolve_push_availability(repo_path, push_decider)
    if not proceed:
        write_log(repo_path, "aviso: remoto inacessivel, commit feito sem push.")
        commit_result["pushed"] = False
        commit_result["message"] += " | push pulado (remoto inacessivel)"
        return commit_result

    push_result = push_repo(repo_path)
    commit_result["success"] = push_result["success"]
    commit_result["pushed"] = push_result["success"]
    commit_result["message"] = f"{commit_result['message']} | {push_result['message']}"
    return commit_result


def commit_repo(repo_path, message=None, agent=None):
    """Stages and commits pending changes (no push). Returns dict: path, time,
    success, hadChanges, message, commitHash.

    message: mensagem customizada pro commit - quando informada, pula a
    geracao automatica (diff + agente/fallback) e usa ela direto. Pensado
    pra acao individual (GUI/CLI de um repo so); commit_all() nao aceita,
    ja que uma mensagem so nao faz sentido pra varios repos de uma vez.
    agent: forca um agente especifico ("claude"/"codex"/"opencode") pra
    essa chamada, ignorando a preferencia configurada."""
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

        commit_msg = message or _generate_commit_message(repo_path, agent=agent)

        result["commitHash"] = _do_commit(repo_path, commit_msg)
        result["success"] = True
        result["message"] = f"commit: {commit_msg}"
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


def sync_repo(repo_path, push_decider=None, message=None, agent=None):
    """Commit followed by push — used pela tarefa agendada e pelo comando
    `sync`. Returns dict: path, time, success, hadChanges, message.

    Antes de commitar, verifica se o remoto esta acessivel (ver
    _resolve_push_availability) - se nao estiver e ninguem topar tentar de
    novo, segue so commitando, sem dar push nessa rodada. `message`/`agent`
    (ver commit_repo) so fazem sentido pra chamada de um repo so."""
    proceed, _ = _resolve_push_availability(repo_path, push_decider)
    skip_push = not proceed
    if skip_push:
        write_log(repo_path, "aviso: remoto inacessivel, commitando sem dar push nesta rodada.")

    commit_result = commit_repo(repo_path, message=message, agent=agent)
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


def run_all(push_decider=None, agent=None):
    """Commit + push every enabled target — used by the scheduled task and
    the `run-now` CLI command. Ver sync_repo() pro que push_decider faz.

    agent explicito (ex: --agent no CLI) tem prioridade; sem ele, usa
    cfg["scheduleAgent"] (se fixado - ver pin_schedule_agent_if_created_by_skill);
    sem os dois, cada commit resolve o agente normalmente (cfg["aiAgent"]/auto)."""
    cfg = load_config()
    paths = resolve_targets(cfg.get("targets", []))
    resolved_agent = agent or cfg.get("scheduleAgent")
    status = load_status()
    for p in paths:
        r = sync_repo(p, push_decider=push_decider, agent=resolved_agent)
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


def commit_all(agent=None):
    """Commit-only pass over every enabled target (no push) — used by the
    manual 'Commitar tudo' action in the GUI/CLI."""
    cfg = load_config()
    paths = resolve_targets(cfg.get("targets", []))
    status = load_status()
    for p in paths:
        r = commit_repo(p, agent=agent)
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

# ---- notificacao nativa (usada quando a rodada agendada tem falha de push) ----

def notify_windows(title, message, timeout_ms=8000):
    """Balao/toast nativo do Windows (NotifyIcon.ShowBalloonTip), sem
    depender de nenhum icone de bandeja ja aberto - dispara e esquece
    (Popen, nao espera terminar). No-op fora do Windows."""
    if not IS_WINDOWS:
        return
    icon_path = str(Path(__file__).resolve().parent / "assets" / "icon.ico")
    ps_script = (
        "Add-Type -AssemblyName System.Windows.Forms\n"
        "Add-Type -AssemblyName System.Drawing\n"
        "$ni = New-Object System.Windows.Forms.NotifyIcon\n"
        "try { $ni.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon($env:GAS_ICON) }\n"
        "catch { $ni.Icon = [System.Drawing.SystemIcons]::Warning }\n"
        "$ni.Visible = $true\n"
        "$ni.ShowBalloonTip([int]$env:GAS_TIMEOUT, $env:GAS_TITLE, $env:GAS_MSG, "
        "[System.Windows.Forms.ToolTipIcon]::Warning)\n"
        "Start-Sleep -Milliseconds ([int]$env:GAS_TIMEOUT + 500)\n"
        "$ni.Dispose()\n"
    )
    env = {
        **os.environ,
        "GAS_ICON": icon_path,
        "GAS_TITLE": title,
        "GAS_MSG": message,
        "GAS_TIMEOUT": str(timeout_ms),
    }
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
            env=env, **_no_window_flags(),
        )
    except Exception:
        pass


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
