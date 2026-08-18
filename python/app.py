import argparse
import json
import subprocess
import sys
import threading
from pathlib import Path

import autosync_core as core


def resource_dir():
    """Base dir to find bundled resources (VERSION, assets/) — the PyInstaller
    onefile extraction dir when frozen, or this file's folder when run from source."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def asset_path(*parts):
    return resource_dir().joinpath(*parts)


def self_paths():
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
        sync_target = base / ("git-autosync-sync.exe" if core.IS_WINDOWS else "git-autosync-sync")
        gui_target = Path(sys.executable)
    else:
        base = Path(__file__).resolve().parent
        sync_target = base / "run_sync.py"
        gui_target = base / "app.py"
    return sync_target, gui_target


# ---------------- CLI ----------------

def cmd_status(args):
    status = core.load_status()
    if args.json:
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return
    print(f"Ultima rodada geral: {status.get('lastSyncRun')}\n")
    for path, r in status.get("repos", {}).items():
        tag = "[OK]" if r.get("success") else "[ERRO]"
        print(f"{tag} {path}")
        print(f"     ultima execucao: {r.get('lastRun')} | alteracoes: {r.get('hadChanges')} | "
              f"ultimo push: {r.get('lastPush') or 'nunca'} | {r.get('message', '')}")


def cmd_list(args):
    cfg = core.load_config()
    print(f"Horarios agendados: {', '.join(cfg.get('schedules', []))}")
    print(f"Tarefa: {cfg.get('taskName')}")
    print(f"Tray habilitada: {cfg.get('trayEnabled')}\n")
    print("Alvos configurados:")
    for i, t in enumerate(cfg.get("targets", []), 1):
        tag = "ROOT (varre subpastas git)" if t.get("type") == "root" else "REPO"
        en = "ativo" if t.get("enabled", True) else "desativado"
        print(f"  {i}. [{tag}][{en}] {t['path']}")
        for excl in t.get("exclude", []):
            print(f"       excluido: {excl}")


def cmd_add(args):
    p = Path(args.path)
    if not p.exists():
        print(f"Caminho nao existe: {args.path}", file=sys.stderr)
        sys.exit(1)
    cfg = core.load_config()
    if any(t["path"] == str(p) for t in cfg["targets"]):
        print(f"Alvo ja existe: {p}")
        return
    cfg["targets"].append({"path": str(p), "type": args.type, "enabled": True})
    core.save_config(cfg)
    print(f"Adicionado ({args.type}): {p}")


def cmd_remove(args):
    target_path = str(Path(args.path))
    cfg = core.load_config()
    before = len(cfg["targets"])
    cfg["targets"] = [t for t in cfg["targets"] if t["path"] != target_path]
    core.save_config(cfg)
    if len(cfg["targets"]) == before:
        print("Nenhum alvo encontrado com esse caminho.")
    else:
        print(f"Removido: {target_path}")


def cmd_exclude(args):
    repo_path = str(Path(args.path).resolve())
    root_path = core.find_owning_root(repo_path)
    if not root_path:
        print(f"Nenhum alvo tipo root tem {repo_path} como subpasta direta.", file=sys.stderr)
        sys.exit(1)
    core.exclude_repo_from_root(root_path, repo_path)
    print(f"Excluido de '{root_path}': {repo_path}")


def cmd_include(args):
    repo_path = str(Path(args.path).resolve())
    root_path = core.find_owning_root(repo_path)
    if not root_path:
        print(f"Nenhum alvo tipo root tem {repo_path} como subpasta direta.", file=sys.stderr)
        sys.exit(1)
    core.include_repo_in_root(root_path, repo_path)
    print(f"Removido da exclusao de '{root_path}': {repo_path}")


def cmd_set_schedule(args):
    times = [t.strip() for t in args.times.split(",") if t.strip()]
    cfg = core.load_config()
    cfg["schedules"] = times
    core.save_config(cfg)
    sync_target, _ = self_paths()
    core.install_schedule(sync_target, schedules=times, task_name=cfg["taskName"])
    print(f"Horarios atualizados: {', '.join(times)}")


def _make_cli_push_decider(cancel_label):
    """Chamado quando o remoto de um repo esta inacessivel, antes de
    commitar/dar push. Pergunta no terminal [T]/[C]; sem terminal interativo
    (rodando de um script/tarefa), so avisa e segue (cancel_label descreve o
    que acontece ao desistir: 'apenas commit' pro fluxo de sync, 'cancelar'
    pro de push puro)."""
    def decider(repo_path):
        if not sys.stdin.isatty():
            print(f"[aviso] {repo_path}: remoto inacessivel agora, {cancel_label}.")
            return False
        while True:
            choice = input(f"[aviso] {repo_path}: remoto inacessivel agora. "
                            f"[T] tentar novamente  [C] {cancel_label}: ").strip().lower()
            if choice == "t":
                return True
            if choice == "c":
                return False
            print("Resposta invalida, digite T ou C.")
    return decider


_cli_sync_decider = _make_cli_push_decider("apenas commit")
_cli_push_only_decider = _make_cli_push_decider("cancelar o push")


def _resolve_repo_arg(repo_arg):
    """--repo <caminho>, ou o diretorio atual se omitido."""
    return str(Path(repo_arg).resolve()) if repo_arg else str(Path.cwd())


def _print_batch_result(status):
    for path, r in status["repos"].items():
        tag = "[OK]" if r.get("success") else "[ERRO]"
        print(f"{tag} {path}: {r.get('message', '')}")


def cmd_commit(args):
    if args.all:
        print("Verificando e commitando (sem push) em todos os alvos configurados...")
        _print_batch_result(core.commit_all())
        return
    path = _resolve_repo_arg(args.repo)
    r = core.commit_repo(path)
    tag = "[OK]" if r["success"] else "[ERRO]"
    print(f"{tag} {path}: {r['message']}")


def cmd_push(args):
    if args.all:
        print("Dando push em todos os alvos configurados...")
        _print_batch_result(core.push_all(push_decider=_cli_push_only_decider))
        return
    path = _resolve_repo_arg(args.repo)
    r = core.push_repo_checked(path, push_decider=_cli_push_only_decider)
    tag = "[OK]" if r["success"] else "[ERRO]"
    print(f"{tag} {path}: {r['message']}")


def cmd_sync(args):
    if args.all:
        print("Rodando sync (commit + push) em todos os alvos configurados...")
        _print_batch_result(core.run_all(push_decider=_cli_sync_decider))
        return
    path = _resolve_repo_arg(args.repo)
    r = core.sync_repo(path, push_decider=_cli_sync_decider)
    tag = "[OK]" if r["success"] else "[ERRO]"
    print(f"{tag} {path}: {r['message']}")


SINCE_PRESETS = {"7d": 7, "30d": 30, "90d": 90}


def _since_arg(since):
    if not since or since == "all":
        return None
    days = SINCE_PRESETS.get(since)
    if days is None:
        print(f"periodo invalido: {since} (use 7d, 30d, 90d ou all)", file=sys.stderr)
        sys.exit(1)
    import datetime
    return (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")


def cmd_history(args):
    since = _since_arg(args.since)
    cfg = core.load_config()
    if args.repo:
        paths = [str(Path(args.repo))]
    else:
        paths = core.resolve_targets(cfg.get("targets", []))

    result = {}
    for p in paths:
        result[p] = core.get_commit_log(p, since=since, limit=args.limit)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    for p, commits in result.items():
        print(f"\n=== {p} ===")
        if not commits:
            print("  (sem commits no periodo)")
            continue
        for c in commits:
            print(f"  {c['hash'][:8]}  {c['date']}  {c['message']}")


def cmd_install(args):
    cfg = core.load_config()
    sync_target, _ = self_paths()
    core.install_schedule(sync_target, schedules=cfg["schedules"], task_name=cfg["taskName"])
    print(f"Tarefa agendada instalada/atualizada: {', '.join(cfg['schedules'])}")


def cmd_uninstall(args):
    core.uninstall_schedule()
    core.disable_tray_autostart()
    print("Tarefa agendada e autostart da tray removidos.")


def cmd_log(args):
    if not core.LOG_FILE.exists():
        print("Sem log ainda.")
        return
    lines = core.LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-args.lines:]:
        print(line)


def cmd_enable_tray(args):
    cmd_install(args)
    _, gui_target = self_paths()
    core.enable_tray_autostart(gui_target)
    print("Tray habilitada (inicia com o login). Abrindo agora...")
    launch_detached(gui_target, ["--tray"])


def cmd_disable_tray(args):
    core.disable_tray_autostart()
    print("Tray desabilitada (autostart removido). Feche o icone manualmente se estiver aberto.")


def launch_detached(target, extra_args):
    target = Path(target)
    if target.suffix.lower() == ".py":
        subprocess.Popen([sys.executable, str(target), *extra_args])
    else:
        subprocess.Popen([str(target), *extra_args])


# ---------------- GUI ----------------

def run_gui():
    import gui
    gui.run_gui()


# ---------------- Tray (pystray) ----------------

def run_tray():
    import pystray
    from assets.generate_icon import draw_sync_glyph

    def make_icon(color):
        # mesmo desenho do icone.ico da area de trabalho, so com o fundo na
        # cor que indica o status atual (verde/vermelho/amarelo/cinza).
        return draw_sync_glyph(size=64, bg=color)

    icons = {
        "ok": make_icon((34, 139, 34, 255)),
        "err": make_icon((220, 20, 60, 255)),
        "warn": make_icon((255, 200, 0, 255)),
        "idle": make_icon((128, 128, 128, 255)),
    }

    state = {"summary": "carregando...", "icon_key": "idle"}

    def compute_summary():
        status = core.load_status()
        repos = status.get("repos", {})
        if not repos:
            return "idle", "sem execucoes ainda"
        errors = [p for p, r in repos.items() if not r["success"]]
        changed = [p for p, r in repos.items() if r["hadChanges"]]
        if errors:
            return "err", f"{len(errors)} repo(s) com erro"
        if changed:
            return "ok", f"{len(changed)} repo(s) sincronizados"
        return "ok", "tudo em dia"

    def refresh(icon):
        key, summary = compute_summary()
        state["icon_key"] = key
        state["summary"] = summary
        icon.icon = icons[key]
        icon.title = f"Git AutoSync - {summary}"
        icon.update_menu()

    def on_run_now(icon, item):
        state["summary"] = "rodando..."
        state["icon_key"] = "warn"
        icon.icon = icons["warn"]
        icon.update_menu()
        core.run_all()
        refresh(icon)

    def on_open_log(icon, item):
        if core.LOG_FILE.exists():
            if core.IS_WINDOWS:
                import os
                os.startfile(core.LOG_FILE)
            else:
                subprocess.Popen(["xdg-open", str(core.LOG_FILE)])

    def on_open_config(icon, item):
        _, gui_target = self_paths()
        launch_detached(gui_target, ["--gui"])

    def on_quit(icon, item):
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(lambda item: f"Status: {state['summary']}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Rodar agora", on_run_now),
        pystray.MenuItem("Ver log", on_open_log),
        pystray.MenuItem("Abrir configuracao", on_open_config),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sair", on_quit),
    )

    icon = pystray.Icon("git-autosync", icons["idle"], "Git AutoSync", menu)

    def poller():
        import time
        while True:
            refresh(icon)
            time.sleep(60)

    threading.Thread(target=poller, daemon=True).start()
    icon.run()


# ---------------- entry point ----------------

def get_version():
    version_file = asset_path("VERSION")
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return "desconhecida"


def build_parser():
    parser = argparse.ArgumentParser(prog="git-autosync")
    parser.add_argument("--version", action="version", version=f"git-autosync {get_version()}")
    parser.add_argument("--gui", action="store_true", help="abre a interface grafica")
    parser.add_argument("--tray", action="store_true", help="abre o icone da bandeja")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("list")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("add")
    p.add_argument("path")
    p.add_argument("--type", choices=["repo", "root"], default="repo")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("remove")
    p.add_argument("path")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("exclude", help="exclui um repo de dentro de um alvo tipo root")
    p.add_argument("path", help="caminho do repositorio (subpasta direta de um alvo root)")
    p.set_defaults(func=cmd_exclude)

    p = sub.add_parser("include", help="desfaz um exclude anterior")
    p.add_argument("path", help="caminho do repositorio (subpasta direta de um alvo root)")
    p.set_defaults(func=cmd_include)

    p = sub.add_parser("set-schedule")
    p.add_argument("times", help='ex: "12:00,17:30"')
    p.set_defaults(func=cmd_set_schedule)

    p = sub.add_parser("commit", help="commita, sem push (o repo atual por padrao)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--repo", help="caminho do repo (default: diretorio atual)")
    g.add_argument("--all", action="store_true", help="todos os alvos configurados, em vez do repo atual")
    p.set_defaults(func=cmd_commit)

    p = sub.add_parser("push", help="da push do que ja foi commitado (o repo atual por padrao)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--repo", help="caminho do repo (default: diretorio atual)")
    g.add_argument("--all", action="store_true", help="todos os alvos configurados, em vez do repo atual")
    p.set_defaults(func=cmd_push)

    p = sub.add_parser("sync", help="commit + push de verdade (o repo atual por padrao)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--repo", help="caminho do repo (default: diretorio atual)")
    g.add_argument("--all", action="store_true", help="todos os alvos configurados, em vez do repo atual")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("history")
    p.add_argument("--repo", help="caminho de um repo especifico (default: todos os alvos configurados)")
    p.add_argument("--since", default="all", help="7d, 30d, 90d ou all (default: all)")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("install")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("uninstall")
    p.set_defaults(func=cmd_uninstall)

    p = sub.add_parser("log")
    p.add_argument("--lines", type=int, default=40)
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("enable-tray")
    p.set_defaults(func=cmd_enable_tray)

    p = sub.add_parser("disable-tray")
    p.set_defaults(func=cmd_disable_tray)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.tray:
        run_tray()
        return
    if args.gui:
        run_gui()
        return
    if getattr(args, "command", None):
        args.func(args)
        return

    # no args at all -> default to GUI for a friendlier double-click experience
    run_gui()


if __name__ == "__main__":
    main()
