import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
import copy
import contextlib
import functools
import fnmatch
import re
import threading
import uuid
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from runtime_safety import file_lock, atomic_json, Snapshot, merge_snapshot, redact, run_process
from scheduler import validate_schedules
import scheduler
import credentials

IS_WINDOWS = platform.system() == "Windows"

CONFIG_DIR = Path(os.environ.get("GIT_AUTOSYNC_HOME", str(Path.home() / ".git-autosync")))
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
    "mrTargetBranch": "main",
    "aiEnabled": False,
    "repoPolicies": {},
}

GITLAB_TOKEN_ENV = "GIT_AUTOSYNC_GITLAB_TOKEN"

AGENT_ORDER = ["claude", "codex", "opencode"]
OPENCODE_SAFE_AGENT = "git-autosync-safe"


def ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config():
    ensure_config_dir()
    with file_lock(CONFIG_DIR / "state.lock"):
        if not CONFIG_FILE.exists():
            atomic_json(CONFIG_FILE, copy.deepcopy(DEFAULT_CONFIG))
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config.json deve conter um objeto JSON; arquivo preservado.")
    return Snapshot({**copy.deepcopy(DEFAULT_CONFIG), **data})


def save_config(cfg):
    ensure_config_dir()
    with file_lock(CONFIG_DIR / "state.lock"):
        current = load_config() if CONFIG_FILE.exists() else copy.deepcopy(DEFAULT_CONFIG)
        merged = merge_snapshot(current, cfg)
        validate_schedules(merged.get("schedules", []))
        atomic_json(CONFIG_FILE, merged)
        if isinstance(cfg, Snapshot):
            cfg.clear()
            cfg.update(merged)
            cfg.baseline = copy.deepcopy(merged)


def load_status():
    ensure_config_dir()
    if not STATUS_FILE.exists():
        return Snapshot({"lastSyncRun": None, "repos": {}})
    return Snapshot(json.loads(STATUS_FILE.read_text(encoding="utf-8")))


def save_status(status):
    ensure_config_dir()
    with file_lock(CONFIG_DIR / "state.lock"):
        current = load_status() if STATUS_FILE.exists() else {"lastSyncRun": None, "repos": {}}
        merged = merge_snapshot(current, status)
        atomic_json(STATUS_FILE, merged)
        if isinstance(status, Snapshot):
            status.clear()
            status.update(merged)
            status.baseline = copy.deepcopy(merged)


def write_log(repo_path, message):
    ensure_config_dir()
    line = redact(f"{datetime.now():%Y-%m-%d %H:%M:%S} [{repo_path}] {message}")
    with file_lock(CONFIG_DIR / "log.lock"):
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 5 * 1024 * 1024:
            for number in range(3, 0, -1):
                source = Path(str(LOG_FILE) + (f".{number}" if number else ""))
                if source.exists():
                    if number == 3:
                        source.unlink()
                    else:
                        os.replace(source, Path(str(LOG_FILE) + f".{number + 1}"))
            os.replace(LOG_FILE, Path(str(LOG_FILE) + ".1"))
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    print(line)


def _no_window_flags():
    """Suppresses the console flash Windows shows for each subprocess spawned
    from a windowed (GUI/pythonw) process."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WINDOWS else {}


_git_context = threading.local()
_previews = {}


def _run(args, cwd=None, timeout=120, input=None):
    return run_process(args, cwd=cwd, timeout=timeout or 120, input=input,
                       env=getattr(_git_context, "env", None))


def _git(repo_path, *args):
    result = _run(["git", *args], cwd=repo_path)
    if result.returncode:
        raise RuntimeError(redact((result.stderr or result.stdout).strip()) or f"git {args[0]} falhou")
    return result.stdout.strip()


def _repo_guard(fn):
    @functools.wraps(fn)
    def guarded(repo_path, *args, **kwargs):
        try:
            common = _git(repo_path, "rev-parse", "--git-common-dir")
            lock = (Path(repo_path) / common).resolve() / "git-autosync.lock"
            with file_lock(lock):
                return fn(repo_path, *args, **kwargs)
        except Exception as exc:
            return {"path": str(repo_path), "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "success": False, "hadChanges": False, "pushed": False,
                    "message": redact(str(exc)), "error": redact(str(exc)), "commitHash": None}
    return guarded


def _preflight(repo_path):
    _git(repo_path, "rev-parse", "--show-toplevel")
    if _run(["git", "symbolic-ref", "-q", "HEAD"], cwd=repo_path).returncode:
        raise RuntimeError("HEAD destacado: selecione uma branch antes de sincronizar.")
    for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer"):
        path = Path(_git(repo_path, "rev-parse", "--git-path", name))
        if (Path(repo_path) / path).exists():
            raise RuntimeError(f"Operacao Git em andamento ({name}); resolva manualmente.")
    if _git(repo_path, "ls-files", "-u"):
        raise RuntimeError("Conflitos pendentes; resolva antes de sincronizar.")
    policy = _policy(repo_path)
    branch = _current_branch(repo_path)
    if policy.get("allowedBranches") and not any(fnmatch.fnmatchcase(branch, p) for p in policy["allowedBranches"]):
        raise RuntimeError(f"Branch nao permitida pela politica: {branch}")


def _policy(repo_path):
    cfg = load_config()
    key = os.path.normcase(str(Path(repo_path).resolve()))
    return next((v for k, v in cfg.get("repoPolicies", {}).items()
                 if os.path.normcase(str(Path(k).resolve())) == key), {})


@contextlib.contextmanager
def _candidate_index(repo_path, publish=False):
    """Stage into a private index. Failed/cancelled commits preserve the user's index."""
    index = (Path(repo_path) / _git(repo_path, "rev-parse", "--git-path", "index")).resolve()
    index_lock = Path(str(index) + ".lock")
    lock_fd = None
    if publish:
        lock_fd = os.open(index_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    fd, temp_name = tempfile.mkstemp(prefix="autosync-index-", dir=index.parent)
    os.close(fd)
    candidate = Path(temp_name)
    original_env = getattr(_git_context, "env", None)
    try:
        if index.exists():
            shutil.copyfile(index, candidate)
        else:
            candidate.unlink()
        _git_context.env = {**(original_env or {}), "GIT_INDEX_FILE": str(candidate)}
        _git(repo_path, "add", "-A")
        _check_candidate(repo_path)
        yield
        if publish:
            # Successful commit's index becomes the real index; worktree is untouched.
            os.close(lock_fd)
            lock_fd = None
            os.replace(candidate, index)
    finally:
        _git_context.env = original_env
        candidate.unlink(missing_ok=True)
        Path(str(candidate) + ".lock").unlink(missing_ok=True)
        if lock_fd is not None:
            os.close(lock_fd)
        if publish:
            index_lock.unlink(missing_ok=True)


def _check_candidate(repo_path):
    policy = _policy(repo_path)
    names = _git(repo_path, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split("\0")
    denied = [".env", ".env.*", "*.pem", "*.key", "id_rsa", "id_ed25519", "credentials.json"] + policy.get("exclude", [])
    for name in filter(None, names):
        basename = name.rsplit("/", 1)[-1]
        if any(fnmatch.fnmatchcase(name, p) or fnmatch.fnmatchcase(basename, p) for p in denied):
            raise RuntimeError(f"Arquivo sensivel/excluido no commit: {name}")
        if policy.get("include") and not any(fnmatch.fnmatchcase(name, p) for p in policy["include"]):
            raise RuntimeError(f"Arquivo fora da politica de inclusao: {name}")
        size = int(_git(repo_path, "cat-file", "-s", f":{name}"))
        if size > policy.get("maxFileBytes", 5 * 1024 * 1024):
            raise RuntimeError(f"Arquivo excede limite da politica: {name}")
        content = _git(repo_path, "show", f":{name}")
        if re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b(?:glpat-|ghp_|github_pat_)[A-Za-z0-9_-]{15,}|\bAKIA[A-Z0-9]{16}", content):
            raise RuntimeError(f"Possivel segredo detectado: {name}. Revise antes de commitar.")


def _snapshot(repo_path):
    head = _run(["git", "rev-parse", "--verify", "HEAD"], cwd=repo_path)
    return (_git(repo_path, "write-tree"), head.stdout.strip(), _current_branch(repo_path))


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
    unique = {}
    for item in resolved:
        item["path"] = str(Path(item["path"]).resolve())
        unique.setdefault(os.path.normcase(item["path"]), item)
    return list(unique.values())


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
            [claude_bin, "-p", "--output-format", "text",
             "--disallowedTools", "Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch"],
            cwd=cwd, timeout=120, input=prompt,
        )
        return (proc.stdout.strip() or None) if proc.returncode == 0 else None
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
                raise RuntimeError("Configuracao OpenCode invalida; arquivo preservado.")
        agents = data.setdefault("agent", {})
        if OPENCODE_SAFE_AGENT not in agents:
            agents[OPENCODE_SAFE_AGENT] = {
                "description": "Gera texto a partir de um prompt, sem tocar em arquivos "
                               "nem rodar comandos (usado pelo git-autosync pra gerar "
                               "mensagem de commit).",
                "permission": {"write": "deny", "edit": "deny", "bash": "deny", "webfetch": "deny"},
            }
            atomic_json(cfg_path, data)
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
    cfg = load_config()
    if not _policy(repo_path).get("aiEnabled", cfg.get("aiEnabled", False)):
        return f"chore: auto-commit {datetime.now():%Y-%m-%d %H:%M}"
    diff = _git(repo_path, "diff", "--staged", "--no-ext-diff", "--no-textconv")
    if len(diff) > 12000:
        diff = diff[:12000] + "\n...(diff truncado)..."

    prompt = (
        "Voce e uma agente determinística e impessoal, especialista em Git, "
        "responsavel por gerar mensagens de commit no padrao Conventional "
        "Commits com emojis. Nunca se refere a si mesma nem ao usuario, nunca "
        "opina sobre arquitetura/refatoracao/funcionalidade fora do escopo. "
        "Responda somente em portugues do Brasil, em texto plano puro (sem "
        "markdown, sem crases, sem aspas, sem blocos de codigo).\n\n"
        "Passos: (1) analise o diff abaixo; (2) classifique o(s) tipo(s) de "
        "mudanca; se houver mais de um tipo, use o de maior prioridade nesta "
        "ordem: fix > feat > refactor > chore > docs > test > style; "
        "(3) formate a mensagem; (4) confira que a saida segue exatamente o "
        "formato pedido.\n\n"
        "Emojis permitidos (use so o correspondente ao tipo escolhido): "
        "feat=✨, fix=\U0001FA79, refactor=♻️, docs=\U0001F4DA, "
        "chore=\U0001F527, test=\U0001F9EA, style=\U0001F3A8.\n\n"
        "Formato de saida (respeite as quebras de linha abaixo):\n"
        "<emoji><tipo>[escopo opcional]: <descricao curta, max 72 caracteres>\n"
        "\n"
        "<corpo explicando detalhadamente o que mudou e por que, podendo ter "
        "varias linhas, cada uma com no maximo 72 caracteres>\n\n"
        "Nao inclua nada alem da mensagem de commit (sem preambulo, sem "
        "explicacao adicional, sem aspas ao redor da mensagem).\n\n"
        f"diff:\n{diff}"
    )

    resolved = _resolve_agent(agent)
    commit_msg = None
    if resolved:
        runner = _AGENT_RUNNERS.get(resolved)
        if runner:
            try:
                with tempfile.TemporaryDirectory(prefix="git-autosync-ai-") as isolated:
                    commit_msg = runner(prompt, isolated)
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
        before = _run(["git", "rev-parse", "--verify", "HEAD"], cwd=repo_path).stdout.strip()
        _git(repo_path, "commit", "-F", tmp_path)
        after = _git(repo_path, "rev-parse", "--verify", "HEAD")
        if after == before:
            raise RuntimeError("Git nao criou um novo commit.")
    finally:
        os.unlink(tmp_path)
    write_log(repo_path, f"commit local ok: {message}")
    return after


@_repo_guard
def stage_and_generate_message(repo_path, agent=None):
    """Preview using a private index, preserving the user's staged changes."""
    if not (Path(repo_path) / ".git").exists():
        return {"hadChanges": False, "message": None, "error": "nao e repositorio git"}
    try:
        _preflight(repo_path)
        if not _git(repo_path, "status", "--porcelain"):
            return {"hadChanges": False, "message": None, "error": None}
        with _candidate_index(repo_path):
            snapshot = _snapshot(repo_path)
            message = _generate_commit_message(repo_path, agent=agent)
        _previews[os.path.normcase(str(Path(repo_path).resolve()))] = snapshot
        return {"hadChanges": True, "message": message, "error": None}
    except Exception as exc:
        return {"hadChanges": False, "message": None, "error": str(exc)}


def unstage(repo_path):
    """Discard a preview. The user's real index was never modified."""
    _previews.pop(os.path.normcase(str(Path(repo_path).resolve())), None)


@_repo_guard
def finalize_commit(repo_path, message):
    """Commit only if the current candidate still matches the reviewed preview."""
    key = os.path.normcase(str(Path(repo_path).resolve()))
    expected = _previews.pop(key, None)
    if expected is None:
        raise RuntimeError("Previa expirada; gere a mensagem novamente antes de confirmar.")
    return commit_repo(repo_path, message=message, expected=expected)


@_repo_guard
def finalize_sync(repo_path, message, push_decider=None, autofix_confirm=None):
    """Como finalize_commit() + push (com a mesma checagem de conexao de
    sync_repo) - usado depois de revisar a mensagem gerada por
    stage_and_generate_message(). Ver push_repo_with_autofix pro que
    autofix_confirm faz. Mesmo formato de retorno de sync_repo()."""
    commit_result = finalize_commit(repo_path, message)
    if not commit_result["success"]:
        commit_result["pushed"] = False
        commit_result["state"] = "failed"
        return commit_result

    proceed, _ = _resolve_push_availability(repo_path, push_decider)
    if not proceed:
        write_log(repo_path, "aviso: remoto inacessivel, commit feito sem push.")
        commit_result["pushed"] = False
        commit_result["success"] = False
        commit_result["state"] = "pending_push"
        commit_result["message"] += " | push pulado (remoto inacessivel)"
        return commit_result

    push_result = push_repo_with_autofix(repo_path, confirm=autofix_confirm)
    commit_result["success"] = push_result["success"]
    commit_result["pushed"] = push_result["success"]
    commit_result["state"] = "synced" if push_result["success"] else "pending_push"
    commit_result["message"] = f"{commit_result['message']} | {push_result['message']}"
    return commit_result


@_repo_guard
def commit_repo(repo_path, message=None, agent=None, expected=None):
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
        _preflight(repo_path)
        status = _git(repo_path, "status", "--porcelain")
        if not status:
            result["success"] = True
            result["message"] = "sem alteracoes, nada a fazer"
            write_log(repo_path, result["message"])
            return result

        result["hadChanges"] = True
        with _candidate_index(repo_path, publish=True):
            if expected is not None and _snapshot(repo_path) != expected:
                raise RuntimeError("Arquivos ou branch mudaram depois da previa; revise novamente.")
            commit_msg = message or _generate_commit_message(repo_path, agent=agent)
            result["commitHash"] = _do_commit(repo_path, commit_msg)
        result["success"] = True
        result["message"] = f"commit: {commit_msg}"
    except Exception as exc:
        result["message"] = f"erro inesperado: {exc}"
        write_log(repo_path, f"ERRO: {exc}")

    return result


@_repo_guard
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
        _preflight(repo_path)
        remote, branch = _push_target(repo_path)
        push = _run(["git", "push", remote, f"HEAD:refs/heads/{branch}"], cwd=repo_path)
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


def _push_target(repo_path):
    branch = _current_branch(repo_path)
    def config(name):
        return _run(["git", "config", "--get", name], cwd=repo_path).stdout.strip()
    remote = config(f"branch.{branch}.pushRemote") or config("remote.pushDefault") or config(f"branch.{branch}.remote")
    remote = remote or ("origin" if "origin" in _git(repo_path, "remote").splitlines() else "")
    if not remote or remote == "." or remote.startswith("-"):
        raise RuntimeError("Configure um remoto de push valido para esta branch.")
    upstream = config(f"branch.{branch}.merge")
    destination = upstream.removeprefix("refs/heads/") if upstream and remote == config(f"branch.{branch}.remote") else branch
    _git(repo_path, "check-ref-format", "--branch", destination)
    return remote, destination


def _current_branch(repo_path):
    r = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    return r.stdout.strip()


# ---- diagnostico + correcao assistida de push que falhou (ver push_repo_with_autofix) ----
#
# So cobre as duas causas recorrentes que aparecem repetidas no log e tem
# correcao mecanica conhecida: branch nova sem upstream, e branch local
# desatualizada em relacao ao remoto (non-fast-forward). "remoto inacessivel"
# ja tem tratamento proprio (_resolve_push_availability) - nao e um erro de
# push, e feito antes de tentar.

def diagnose_push_failure(err_text):
    """Reconhece o motivo (a partir do stderr/stdout do `git push` que
    falhou) e devolve (kind, explicacao) - (None, None) se nao reconhecido
    (erro de auth, repo nao encontrado, etc - sem correcao mecanica segura)."""
    err_text = err_text or ""
    if "has no upstream branch" in err_text:
        return "no_upstream", "branch local nunca foi enviada, falta configurar o upstream"
    if "[rejected]" in err_text and ("non-fast-forward" in err_text or "fetch first" in err_text):
        return "non_fast_forward", "o remoto tem commits que voce nao tem localmente"
    return None, None


def suggested_fix_command(repo_path, kind):
    remote, branch = _push_target(repo_path)
    if kind == "no_upstream":
        return f"git push -u {remote} HEAD:refs/heads/{branch}"
    if kind == "non_fast_forward":
        return f"git pull --rebase {remote} {branch}  &&  git push {remote} HEAD:refs/heads/{branch}"
    return None


def apply_push_fix(repo_path, kind):
    """Executa a correcao de `kind`. Retorna dict {success, message}."""
    _preflight(repo_path)
    remote, branch = _push_target(repo_path)

    if kind == "no_upstream":
        r = _run(["git", "push", "-u", remote, f"HEAD:refs/heads/{branch}"], cwd=repo_path)
        ok = r.returncode == 0
        msg = "upstream configurado, push feito" if ok else (r.stderr or r.stdout).strip()
        write_log(repo_path, f"auto-fix (no_upstream): {'ok' if ok else 'falhou -> ' + msg}")
        return {"success": ok, "message": msg}

    if kind == "non_fast_forward":
        if _git(repo_path, "status", "--porcelain"):
            return {"success": False, "message": "Rebase exige arvore de trabalho limpa."}
        r = _run(["git", "pull", "--rebase", remote, branch], cwd=repo_path)
        if r.returncode != 0:
            rebase_paths = [_git(repo_path, "rev-parse", "--git-path", n) for n in ("rebase-merge", "rebase-apply")]
            if any((Path(repo_path) / p).exists() for p in rebase_paths):
                _git(repo_path, "rebase", "--abort")
            msg = "rebase automatico deu conflito, abortado - resolva manualmente (git pull --rebase)"
            write_log(repo_path, f"auto-fix (non_fast_forward): falhou -> {msg}")
            return {"success": False, "message": msg}
        push = _run(["git", "push", remote, f"HEAD:refs/heads/{branch}"], cwd=repo_path)
        ok = push.returncode == 0
        msg = "rebase + push ok" if ok else (push.stderr or push.stdout).strip()
        write_log(repo_path, f"auto-fix (non_fast_forward): {'ok' if ok else 'falhou -> ' + msg}")
        return {"success": ok, "message": msg}

    return {"success": False, "message": f"tipo de correcao desconhecido: {kind}"}


@_repo_guard
def push_repo_with_autofix(repo_path, confirm=None):
    """Como push_repo(), mas se o push falhar com uma causa reconhecida
    (ver diagnose_push_failure), oferece corrigir na hora.

    confirm(repo_path, kind, explain, comando_sugerido) -> bool, chamado so
    quando ha uma correcao conhecida pra oferecer - deve retornar True pra
    executar o comando sugerido agora, False pra so registrar a sugestao.
    confirm=None (rodada agendada/nao interativa) nunca corrige sozinho, so
    loga a sugestao - decisao do usuario, nunca automatica sem supervisao."""
    result = push_repo(repo_path)
    result["diagnosis"] = None
    result["autoFixed"] = False
    if result["success"]:
        return result

    kind, explain = diagnose_push_failure(result["message"])
    if not kind:
        return result
    result["diagnosis"] = {"kind": kind, "explain": explain}

    cmd = suggested_fix_command(repo_path, kind)
    if confirm is None:
        write_log(repo_path, f"sugestao: {cmd} ({explain})")
        result["message"] += f" | sugestao: {cmd}"
        return result

    if not confirm(repo_path, kind, explain, cmd):
        write_log(repo_path, "correcao automatica recusada pelo usuario.")
        result["message"] += f" | correcao recusada (sugestao: {cmd})"
        return result

    fix = apply_push_fix(repo_path, kind)
    result["autoFixed"] = fix["success"]
    result["success"] = fix["success"]
    result["message"] += f" | auto-fix: {fix['message']}"
    return result


# ---- Merge Request pra branch protegida via API do GitLab ----
#
# Branch tipo `main` costuma ser protegida (aprovacao obrigatoria) - push
# direto nunca vai funcionar ali, entao a unica forma de "mandar" uma
# mudanca pra ela e abrir uma Merge Request. Usa so a stdlib (urllib) pra
# nao adicionar dependencia so pra isso.

def get_remote_url(repo_path, remote="origin"):
    r = _run(["git", "remote", "get-url", remote], cwd=repo_path)
    return r.stdout.strip() if r.returncode == 0 else None


def parse_git_remote(url):
    """'https://gitlab.host/grupo/sub/projeto.git' ou
    'git@gitlab.host:grupo/sub/projeto.git' -> (host, "grupo/sub/projeto").
    (None, None) se nao reconhecer o formato."""
    if not url:
        return None, None
    url = url.strip()
    if url.startswith("git@"):
        try:
            host_part, path_part = url[len("git@"):].split(":", 1)
        except ValueError:
            return None, None
    else:
        parsed = urllib.parse.urlparse(url)
        host_part = parsed.netloc
        path_part = parsed.path.lstrip("/")
    path_part = path_part[:-4] if path_part.endswith(".git") else path_part
    return (host_part or None), (path_part or None)


def resolve_gitlab_token(host=None):
    cfg = load_config()
    host = credentials.normalize_host(host or cfg.get("gitlabHost"))
    token = os.environ.get(GITLAB_TOKEN_ENV)
    if token:
        allowed = credentials.normalize_host(os.environ.get("GIT_AUTOSYNC_GITLAB_HOST"))
        return token if allowed == host else None
    if cfg.get("gitlabToken"):
        raise RuntimeError("Token legado em texto plano: salve-o novamente com host para migrar ao cofre.")
    return credentials.resolve(cfg.get("gitlabCredential"), host)


def set_gitlab_token(token, host=None):
    """Store an encrypted/OS-vault credential explicitly bound to a host."""
    cfg = load_config()
    host = credentials.normalize_host(host or cfg.get("gitlabHost"))
    if not token or not token.strip():
        raise ValueError("Token vazio.")
    cfg["gitlabCredential"] = credentials.store(host, token.strip())
    cfg["gitlabHost"] = host
    cfg.pop("gitlabToken", None)
    save_config(cfg)


def clear_gitlab_token():
    cfg = load_config()
    credentials.clear(cfg.get("gitlabCredential"))
    cfg.pop("gitlabCredential", None)
    cfg.pop("gitlabToken", None)
    save_config(cfg)


def _gitlab_api_request(host, path, token, method="GET", data=None):
    host = credentials.normalize_host(host)
    url = f"https://{host}/api/v4{path}"
    body = None
    headers = {"PRIVATE-TOKEN": token}
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise RuntimeError("Redirecionamento da API bloqueado para proteger o token.")
    with urllib.request.build_opener(NoRedirect).open(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


@_repo_guard
def create_merge_request(repo_path, target_branch=None, title=None, description=None, source_branch=None):
    """Cria (ou reaproveita, se ja existir uma aberta com a mesma origem/destino)
    uma Merge Request no GitLab de source_branch (default: branch atual) pra
    target_branch (default: config mrTargetBranch, senao 'main') - o unico
    jeito de fazer uma mudanca chegar numa branch protegida. Da push na
    branch de origem antes (precisa estar no remoto pra abrir a MR).
    Retorna dict: success, message, url (None se nao criou/achou)."""
    result = {"success": False, "message": "", "url": None}

    if not (Path(repo_path) / ".git").exists():
        result["message"] = "nao e repositorio git"
        return result

    branch = source_branch or _current_branch(repo_path)
    target = target_branch or load_config().get("mrTargetBranch", "main")
    if branch == target:
        result["message"] = f"branch atual ja e '{target}', nao ha o que propor"
        return result

    remote_url = get_remote_url(repo_path)
    host, project_path = parse_git_remote(remote_url)
    if not host or not project_path:
        result["message"] = f"nao consegui identificar host/projeto GitLab a partir do remote: {remote_url}"
        return result

    _preflight(repo_path)
    token = resolve_gitlab_token(host)
    if not token:
        result["message"] = (f"falta token do GitLab (variavel de ambiente {GITLAB_TOKEN_ENV}, "
                              f"ou rode 'git-autosync set-gitlab-token')")
        return result

    push = _run(["git", "push", "-u", "origin", branch], cwd=repo_path)
    if push.returncode != 0:
        result["message"] = f"push da branch '{branch}' falhou: {(push.stderr or push.stdout).strip()}"
        write_log(repo_path, f"ERRO ao preparar MR: {result['message']}")
        return result

    project_id = urllib.parse.quote(project_path, safe="")
    query = (f"?source_branch={urllib.parse.quote(branch)}"
             f"&target_branch={urllib.parse.quote(target)}&state=opened")
    try:
        existing = _gitlab_api_request(host, f"/projects/{project_id}/merge_requests{query}", token)
    except Exception as exc:
        result["message"] = f"erro ao consultar MRs existentes no GitLab: {exc}"
        write_log(repo_path, f"ERRO ao consultar MR existente: {exc}")
        return result

    if existing:
        mr = existing[0]
        result["success"] = True
        result["url"] = mr["web_url"]
        result["message"] = f"MR ja existente reaproveitada: {mr['web_url']}"
        write_log(repo_path, result["message"])
        return result

    payload = {"source_branch": branch, "target_branch": target, "title": title or f"{branch} -> {target}"}
    if description:
        payload["description"] = description

    try:
        created = _gitlab_api_request(host, f"/projects/{project_id}/merge_requests", token,
                                       method="POST", data=payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        result["message"] = f"GitLab recusou a criacao da MR ({exc.code}): {body}"
        write_log(repo_path, f"ERRO ao criar MR: {result['message']}")
        return result
    except Exception as exc:
        result["message"] = f"erro ao criar MR: {exc}"
        write_log(repo_path, f"ERRO ao criar MR: {exc}")
        return result

    result["success"] = True
    result["url"] = created["web_url"]
    result["message"] = f"MR criada: {created['web_url']}"
    write_log(repo_path, result["message"])
    return result


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
    try:
        return _run(args, cwd=cwd, timeout=timeout)
    except RuntimeError as exc:
        return subprocess.CompletedProcess(args, -1, "", str(exc))


def check_remote_reachable(repo_path, timeout=8):
    """True/False if the repo has a remote and it is/isn't reachable right
    now (network + credenciais). None if the repo has no remote configured
    at all (nada pra verificar, nada pra fazer push)."""
    if not has_remote(repo_path):
        return None
    try:
        remote, _ = _push_target(repo_path)
        # Empty remotes are reachable too; --exit-code would return 2 for them.
        result = _run_hard_timeout(["git", "ls-remote", remote], cwd=repo_path, timeout=timeout)
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


@_repo_guard
def push_repo_checked(repo_path, push_decider=None, autofix_confirm=None):
    """Como push_repo(), mas primeiro verifica se o remoto esta acessivel
    (ver _resolve_push_availability) - evita disparar um `git push` que ja
    se sabe de antemao que vai falhar, e da chance de tentar de novo antes
    de desistir. Se o push falhar por um motivo com correcao conhecida (sem
    upstream / non-fast-forward), ver push_repo_with_autofix. Mesmo formato
    de retorno de push_repo()."""
    proceed, _ = _resolve_push_availability(repo_path, push_decider)
    if not proceed:
        write_log(repo_path, "aviso: push cancelado, remoto inacessivel.")
        return {
            "path": repo_path,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "success": False,
            "message": "push cancelado (remoto inacessivel)",
        }
    return push_repo_with_autofix(repo_path, confirm=autofix_confirm)


@_repo_guard
def sync_repo(repo_path, push_decider=None, message=None, agent=None, autofix_confirm=None):
    """Commit followed by push — used pela tarefa agendada e pelo comando
    `sync`. Returns dict: path, time, success, hadChanges, message.

    Antes de commitar, verifica se o remoto esta acessivel (ver
    _resolve_push_availability) - se nao estiver e ninguem topar tentar de
    novo, segue so commitando, sem dar push nessa rodada. `message`/`agent`
    (ver commit_repo) so fazem sentido pra chamada de um repo so. Ver
    push_repo_with_autofix pro que autofix_confirm faz."""
    proceed, _ = _resolve_push_availability(repo_path, push_decider)
    skip_push = not proceed
    if skip_push:
        write_log(repo_path, "aviso: remoto inacessivel, commitando sem dar push nesta rodada.")

    commit_result = commit_repo(repo_path, message=message, agent=agent)
    if not commit_result["success"] or skip_push:
        result = {k: commit_result[k] for k in ("path", "time", "success", "hadChanges", "message")}
        result["pushed"] = False
        if skip_push and commit_result["success"]:
            result["success"] = False
            result["state"] = "pending_push"
            result["message"] += " | push pulado (remoto inacessivel)"
        return result

    push_result = push_repo_with_autofix(repo_path, confirm=autofix_confirm)
    return {
        "path": repo_path,
        "time": push_result["time"],
        "success": push_result["success"],
        "hadChanges": commit_result["hadChanges"],
        "pushed": push_result["success"],
        "state": "synced" if push_result["success"] else "pending_push",
        "message": f"{commit_result['message']} | {push_result['message']}",
    }


def _update_status_entry(status, repo_path, **fields):
    repos = status.setdefault("repos", {})
    entry = repos.setdefault(repo_path, {})
    entry.update(fields)
    return entry


def run_all(push_decider=None, agent=None, autofix_confirm=None):
    """Commit + push every enabled target — used by the scheduled task and
    the `run-now` CLI command. Ver sync_repo() pro que push_decider e
    autofix_confirm fazem (autofix_confirm=None - o default, usado pela
    tarefa agendada - nunca corrige push sozinho, so loga a sugestao).

    agent explicito (ex: --agent no CLI) tem prioridade; sem ele, usa
    cfg["scheduleAgent"] (se fixado - ver pin_schedule_agent_if_created_by_skill);
    sem os dois, cada commit resolve o agente normalmente (cfg["aiAgent"]/auto)."""
    cfg = load_config()
    return _run_batch(lambda p: sync_repo(p, push_decider=push_decider,
                      agent=agent or cfg.get("scheduleAgent"), autofix_confirm=autofix_confirm), cfg)


def commit_all(agent=None):
    """Commit-only pass over every enabled target (no push) — used by the
    manual 'Commitar tudo' action in the GUI/CLI."""
    return _run_batch(lambda p: commit_repo(p, agent=agent), load_config())


def push_all(push_decider=None, autofix_confirm=None):
    """Push-only pass over every enabled target — used by the manual
    'Push tudo' action in the GUI/CLI. Ver push_repo_checked() pro que
    push_decider e autofix_confirm fazem."""
    return _run_batch(lambda p: push_repo_checked(p, push_decider=push_decider,
                      autofix_confirm=autofix_confirm), load_config(), push_only=True)


def _run_batch(operation, cfg, push_only=False):
    started = time.monotonic()
    run_id = uuid.uuid4().hex
    results = {}
    for path in resolve_targets(cfg.get("targets", [])):
        try:
            result = operation(path)
        except Exception as exc:
            result = {"success": False, "message": redact(str(exc)), "state": "failed"}
        entry = {**result, "lastRun": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "runId": run_id}
        if result.get("pushed") or (push_only and result.get("success")):
            entry["lastPush"] = entry["lastRun"]
        results[path] = entry
        # Persist each completed repository; crashes do not erase earlier results.
        with file_lock(CONFIG_DIR / "state.lock"):
            status = load_status()
            status.setdefault("repos", {}).setdefault(path, {}).update(entry)
            save_status(status)
    summary = {"runId": run_id, "lastSyncRun": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "durationSeconds": round(time.monotonic() - started, 3), "repos": results}
    with file_lock(CONFIG_DIR / "state.lock"):
        status = load_status()
        status.update({k: v for k, v in summary.items() if k != "repos"})
        status["lastRunPaths"] = list(results)
        save_status(status)
    return summary


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
    schedules = cfg.get("schedules", ["17:30"]) if schedules is None else schedules
    task_name = task_name or cfg.get("taskName", "GitAutoSyncPy")
    with file_lock(CONFIG_DIR / "schedule.lock"):
        scheduler.install(sync_target, schedules, task_name, IS_WINDOWS)
        cfg["schedules"] = schedules
        save_config(cfg)


def uninstall_schedule(task_name=None):
    cfg = load_config()
    task_name = task_name or cfg.get("taskName", "GitAutoSyncPy")
    with file_lock(CONFIG_DIR / "schedule.lock"):
        scheduler.uninstall(task_name, IS_WINDOWS)


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


def force_utf8_stdio():
    """Saida em UTF-8 mesmo quando stdout e' um pipe.

    Com stdout redirecionado, o Python usa o code page do Windows (cp1252) e estoura ao
    escrever emoji de mensagem de commit ("'charmap' codec can't encode"). No binario do
    PyInstaller o PYTHONIOENCODING e o PYTHONUTF8 de quem chama sao ignorados, entao a
    troca tem que ser feita aqui. No binario de janela os streams podem ser None.
    """
    import sys

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
