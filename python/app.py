import argparse
import json
import subprocess
import sys
import threading
from pathlib import Path

import autosync_core as core


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
        tag = "[OK]" if r["success"] else "[ERRO]"
        print(f"{tag} {path}")
        print(f"     ultima execucao: {r['lastRun']} | alteracoes: {r['hadChanges']} | {r['message']}")


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


def cmd_set_schedule(args):
    times = [t.strip() for t in args.times.split(",") if t.strip()]
    cfg = core.load_config()
    cfg["schedules"] = times
    core.save_config(cfg)
    sync_target, _ = self_paths()
    core.install_schedule(sync_target, schedules=times, task_name=cfg["taskName"])
    print(f"Horarios atualizados: {', '.join(times)}")


def cmd_run_now(args):
    print("Rodando sync agora...")
    status = core.run_all()
    for path, r in status["repos"].items():
        tag = "[OK]" if r["success"] else "[ERRO]"
        print(f"{tag} {path}: {r['message']}")


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


# ---------------- GUI (Tkinter) ----------------

def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    cfg = core.load_config()

    root = tk.Tk()
    root.title("Git AutoSync")
    root.geometry("780x520")

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=8, pady=8)

    # --- Targets tab ---
    tab_targets = ttk.Frame(nb)
    nb.add(tab_targets, text="Diretorios")

    columns = ("path", "type", "enabled")
    tree = ttk.Treeview(tab_targets, columns=columns, show="headings", height=12)
    for c, w in zip(columns, (480, 80, 80)):
        tree.heading(c, text=c)
        tree.column(c, width=w)
    tree.pack(fill="both", expand=True, padx=6, pady=6)

    def refresh_targets():
        tree.delete(*tree.get_children())
        for t in cfg["targets"]:
            tree.insert("", "end", iid=t["path"], values=(t["path"], t["type"], t.get("enabled", True)))

    refresh_targets()

    form = ttk.Frame(tab_targets)
    form.pack(fill="x", padx=6, pady=6)
    path_var = tk.StringVar()
    type_var = tk.StringVar(value="repo")
    ttk.Entry(form, textvariable=path_var, width=60).pack(side="left", padx=4)

    def browse():
        d = filedialog.askdirectory()
        if d:
            path_var.set(d)

    ttk.Button(form, text="Procurar...", command=browse).pack(side="left", padx=4)
    ttk.Combobox(form, textvariable=type_var, values=["repo", "root"], width=6, state="readonly").pack(side="left", padx=4)

    def add_target():
        p = path_var.get().strip()
        if not p or not Path(p).exists():
            messagebox.showerror("Erro", "Caminho invalido ou inexistente.")
            return
        if any(t["path"] == p for t in cfg["targets"]):
            messagebox.showinfo("Aviso", "Esse alvo ja esta na lista.")
            return
        cfg["targets"].append({"path": p, "type": type_var.get(), "enabled": True})
        core.save_config(cfg)
        refresh_targets()
        path_var.set("")

    ttk.Button(form, text="Adicionar", command=add_target).pack(side="left", padx=4)

    def remove_selected():
        sel = tree.selection()
        if not sel:
            return
        cfg["targets"] = [t for t in cfg["targets"] if t["path"] not in sel]
        core.save_config(cfg)
        refresh_targets()

    def toggle_selected():
        sel = tree.selection()
        if not sel:
            return
        for t in cfg["targets"]:
            if t["path"] in sel:
                t["enabled"] = not t.get("enabled", True)
        core.save_config(cfg)
        refresh_targets()

    btns = ttk.Frame(tab_targets)
    btns.pack(fill="x", padx=6, pady=(0, 6))
    ttk.Button(btns, text="Remover selecionado", command=remove_selected).pack(side="left", padx=4)
    ttk.Button(btns, text="Ativar/desativar selecionado", command=toggle_selected).pack(side="left", padx=4)

    # --- Schedule tab ---
    tab_sched = ttk.Frame(nb)
    nb.add(tab_sched, text="Horarios")

    ttk.Label(tab_sched, text="Horarios (HH:mm separados por virgula):").pack(anchor="w", padx=8, pady=(12, 2))
    times_var = tk.StringVar(value=", ".join(cfg.get("schedules", [])))
    ttk.Entry(tab_sched, textvariable=times_var, width=40).pack(anchor="w", padx=8)

    def save_schedule():
        times = [t.strip() for t in times_var.get().split(",") if t.strip()]
        if not times:
            messagebox.showerror("Erro", "Informe ao menos um horario HH:mm.")
            return
        cfg["schedules"] = times
        core.save_config(cfg)
        sync_target, _ = self_paths()
        core.install_schedule(sync_target, schedules=times, task_name=cfg["taskName"])
        messagebox.showinfo("OK", f"Horarios salvos e tarefa agendada atualizada: {', '.join(times)}")

    ttk.Button(tab_sched, text="Salvar e reinstalar tarefa agendada", command=save_schedule).pack(anchor="w", padx=8, pady=8)

    ttk.Separator(tab_sched, orient="horizontal").pack(fill="x", padx=8, pady=12)

    def do_enable_tray():
        _, gui_target = self_paths()
        core.enable_tray_autostart(gui_target)
        messagebox.showinfo("OK", "Tray habilitada. Vai iniciar com o login.")

    def do_disable_tray():
        core.disable_tray_autostart()
        messagebox.showinfo("OK", "Tray desabilitada.")

    def do_uninstall():
        core.uninstall_schedule()
        core.disable_tray_autostart()
        messagebox.showinfo("OK", "Tarefa agendada e tray removidos.")

    tray_frame = ttk.Frame(tab_sched)
    tray_frame.pack(anchor="w", padx=8, pady=4)
    ttk.Button(tray_frame, text="Habilitar tray (autostart)", command=do_enable_tray).pack(side="left", padx=4)
    ttk.Button(tray_frame, text="Desabilitar tray", command=do_disable_tray).pack(side="left", padx=4)
    ttk.Button(tray_frame, text="Desinstalar tudo", command=do_uninstall).pack(side="left", padx=4)

    # --- Status tab ---
    tab_status = ttk.Frame(nb)
    nb.add(tab_status, text="Status")

    status_columns = ("path", "success", "changes", "lastRun", "message")
    status_tree = ttk.Treeview(tab_status, columns=status_columns, show="headings", height=14)
    widths = (260, 60, 60, 130, 260)
    for c, w in zip(status_columns, widths):
        status_tree.heading(c, text=c)
        status_tree.column(c, width=w)
    status_tree.pack(fill="both", expand=True, padx=6, pady=6)

    def refresh_status():
        status_tree.delete(*status_tree.get_children())
        status = core.load_status()
        for path, r in status.get("repos", {}).items():
            status_tree.insert("", "end", values=(path, r["success"], r["hadChanges"], r["lastRun"], r["message"]))

    refresh_status()

    run_now_btn = None

    def run_now_bg():
        run_now_btn.config(state="disabled", text="Rodando...")

        def worker():
            core.run_all()
            root.after(0, on_done)

        def on_done():
            refresh_status()
            run_now_btn.config(state="normal", text="Rodar agora")

        threading.Thread(target=worker, daemon=True).start()

    status_btns = ttk.Frame(tab_status)
    status_btns.pack(fill="x", padx=6, pady=(0, 6))
    run_now_btn = ttk.Button(status_btns, text="Rodar agora", command=run_now_bg)
    run_now_btn.pack(side="left", padx=4)
    ttk.Button(status_btns, text="Atualizar", command=refresh_status).pack(side="left", padx=4)

    root.mainloop()


# ---------------- Tray (pystray) ----------------

def run_tray():
    import pystray
    from PIL import Image, ImageDraw

    def make_icon(color):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((4, 4, 60, 60), fill=color, outline=(0, 0, 0, 255), width=2)
        return img

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

def build_parser():
    parser = argparse.ArgumentParser(prog="git-autosync")
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

    p = sub.add_parser("set-schedule")
    p.add_argument("times", help='ex: "12:00,17:30"')
    p.set_defaults(func=cmd_set_schedule)

    p = sub.add_parser("run-now")
    p.set_defaults(func=cmd_run_now)

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
