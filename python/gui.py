"""Interface grafica do Git AutoSync (customtkinter): sidebar + cards de
status por repositorio + historico de commits + agendamento + log.

Todo acesso ao git roda em background thread (run_bg) — a janela nunca trava
enquanto um commit/push/consulta de log esta em andamento.
"""
import os
import threading
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox

import customtkinter as ctk

import app as app_module
import autosync_core as core

ctk.set_appearance_mode("system")
ctk.set_default_color_theme("blue")

_icon_photo = None  # mantem referencia viva (Tk descarta PhotoImage sem dono)


def _apply_window_icon_once(win):
    global _icon_photo
    if core.IS_WINDOWS:
        ico = app_module.asset_path("assets", "icon.ico")
        if ico.exists():
            win.iconbitmap(default=str(ico))
    png = app_module.asset_path("assets", "icon.png")
    if png.exists():
        from PIL import Image, ImageTk
        if _icon_photo is None:
            _icon_photo = ImageTk.PhotoImage(Image.open(png))
        win.iconphoto(True, _icon_photo)


def _set_window_icon(win):
    """customtkinter reseta o icone da janela pra o padrao (arquivo .py/feather)
    depois que ela termina de se redesenhar/aplicar o tema — reaplicar so uma
    vez no __init__ nao e suficiente. Reaplica de novo em alguns momentos
    seguintes pra garantir que o icone final (barra de tarefas/alt-tab) fique
    o nosso, nao o do interpretador Python."""
    def apply():
        try:
            _apply_window_icon_once(win)
        except Exception:
            pass

    apply()
    for delay in (150, 400, 900):
        try:
            win.after(delay, apply)
        except Exception:
            pass

SIDEBAR_WIDTH = 210
HISTORY_PRESETS = [("7 dias", "7d"), ("30 dias", "30d"), ("90 dias", "90d"), ("Tudo", "all")]
CARD_GRID_COLS = 3


def _place_repo_cards(cards, compact):
    """Modo Lista: 1 card por linha (pack), como sempre foi. Modo Cards:
    grade horizontal fixa de CARD_GRID_COLS colunas."""
    if compact:
        for card in cards:
            card.pack(fill="x", pady=3)
    else:
        for i, card in enumerate(cards):
            card.grid(row=i // CARD_GRID_COLS, column=i % CARD_GRID_COLS, padx=8, pady=8, sticky="n")


def _since_from_preset(preset):
    days = {"7d": 7, "30d": 30, "90d": 90}.get(preset)
    if days is None:
        return None
    from datetime import timedelta
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")


def human_relative(ts_str):
    if not ts_str:
        return "nunca"
    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ts_str
    delta = datetime.now() - dt
    seconds = delta.total_seconds()
    if seconds < 60:
        return "agora mesmo"
    if seconds < 3600:
        return f"ha {int(seconds // 60)} min"
    if seconds < 86400:
        return f"ha {int(seconds // 3600)} h"
    return f"ha {int(seconds // 86400)} dia(s)"


def run_bg(fn, on_done, root):
    """Runs fn() in a background thread; on_done(result) runs back on the
    Tk main thread once fn() returns."""
    def worker():
        try:
            result = fn()
        except Exception as exc:
            result = exc
        try:
            root.after(0, lambda: on_done(result))
        except RuntimeError:
            pass  # janela ja foi fechada antes do resultado voltar

    threading.Thread(target=worker, daemon=True).start()


class PushUnavailableDialog(ctk.CTkToplevel):
    """Popup mostrado (na thread principal) quando o remoto de um repo esta
    inacessivel bem antes de comitar. Bloqueia so a thread de background que
    esta rodando o sync — a janela principal continua responsiva."""

    def __init__(self, master, repo_path, on_choice, give_up_label="Apenas commit"):
        super().__init__(master)
        self.title("Push indisponivel")
        self.geometry("480x200")
        self.resizable(False, False)
        _set_window_icon(self)
        self.on_choice = on_choice
        self.protocol("WM_DELETE_WINDOW", lambda: self._choose(False))

        ctk.CTkLabel(self, text="Nao foi possivel acessar o remoto agora:",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=16, pady=(20, 4))
        ctk.CTkLabel(self, text=repo_path, text_color="gray", wraplength=440, justify="left").pack(
            anchor="w", padx=16, pady=(0, 16))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=8)
        ctk.CTkButton(row, text="Tentar novamente", width=160,
                      command=lambda: self._choose(True)).pack(side="left", padx=6)
        ctk.CTkButton(row, text=give_up_label, width=160, fg_color="gray40",
                      command=lambda: self._choose(False)).pack(side="left", padx=6)

        self.grab_set()

    def _choose(self, retry):
        self.on_choice(retry)
        self.destroy()


def make_gui_push_decider(root, give_up_label="Apenas commit"):
    """Fabrica um push_decider (ver core.sync_repo/push_repo_checked) que,
    quando chamado numa thread de background, pede pro thread principal
    abrir o PushUnavailableDialog e espera a resposta antes de continuar.
    give_up_label troca o texto do botao de desistir - "Apenas commit" no
    fluxo de sync (ainda vai commitar), "Cancelar" num push puro (nao ha
    commit nenhum acontecendo)."""

    def decider(repo_path):
        result = {"retry": False}
        answered = threading.Event()

        def on_choice(retry):
            result["retry"] = retry
            answered.set()

        root.after(0, lambda: PushUnavailableDialog(root, repo_path, on_choice, give_up_label))
        answered.wait()
        return result["retry"]

    return decider


class PushFixDialog(ctk.CTkToplevel):
    """Popup mostrado quando um `git push` falha por um motivo com correcao
    conhecida (ver core.diagnose_push_failure) - mostra o comando sugerido
    e deixa executar na hora ou so cancelar (nunca corrige sem essa
    confirmacao explicita)."""

    def __init__(self, master, repo_path, explain, cmd, on_choice):
        super().__init__(master)
        self.title("Push falhou - corrigir?")
        self.geometry("520x240")
        self.resizable(False, False)
        _set_window_icon(self)
        self.on_choice = on_choice
        self.protocol("WM_DELETE_WINDOW", lambda: self._choose(False))

        ctk.CTkLabel(self, text="Push falhou:", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=16, pady=(20, 2))
        ctk.CTkLabel(self, text=repo_path, text_color="gray", wraplength=480, justify="left").pack(
            anchor="w", padx=16)
        ctk.CTkLabel(self, text=explain, wraplength=480, justify="left").pack(
            anchor="w", padx=16, pady=(8, 0))

        ctk.CTkLabel(self, text="Comando sugerido:", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=16, pady=(12, 2))
        ctk.CTkLabel(self, text=cmd, font=ctk.CTkFont(family="Consolas", size=12),
                     wraplength=480, justify="left").pack(anchor="w", padx=16)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=20)
        ctk.CTkButton(row, text="Executar agora", width=160, command=lambda: self._choose(True)).pack(
            side="left", padx=6)
        ctk.CTkButton(row, text="Cancelar", width=160, fg_color="gray40",
                      command=lambda: self._choose(False)).pack(side="left", padx=6)

        self.grab_set()

    def _choose(self, run):
        self.on_choice(run)
        self.destroy()


def make_gui_autofix_confirm(root):
    """Fabrica um autofix_confirm (ver core.push_repo_with_autofix) que pede
    pro thread principal abrir o PushFixDialog e espera a resposta."""

    def confirm(repo_path, kind, explain, cmd):
        result = {"run": False}
        answered = threading.Event()

        def on_choice(run):
            result["run"] = run
            answered.set()

        root.after(0, lambda: PushFixDialog(root, repo_path, explain, cmd, on_choice))
        answered.wait()
        return result["run"]

    return confirm


class CreateMRDialog(ctk.CTkToplevel):
    """Aberto pelo botao "Criar MR": pede branch de destino (pre-preenchida
    com a config) e titulo opcional, depois chama core.create_merge_request
    em background (a branch protegida so aceita mudanca via MR, nunca push
    direto)."""

    def __init__(self, master, repo_path, on_confirm):
        super().__init__(master)
        self.title("Criar Merge Request")
        self.geometry("480x280")
        self.resizable(False, False)
        _set_window_icon(self)
        self.on_confirm = on_confirm

        cfg = core.load_config()
        default_target = cfg.get("mrTargetBranch", "main")

        ctk.CTkLabel(self, text=repo_path, text_color="gray", wraplength=440, justify="left").pack(
            anchor="w", padx=16, pady=(16, 10))

        ctk.CTkLabel(self, text="Branch de destino (protegida, ex: main):").pack(anchor="w", padx=16)
        self.target_var = ctk.StringVar(value=default_target)
        ctk.CTkEntry(self, textvariable=self.target_var, width=200).pack(anchor="w", padx=16, pady=(2, 10))

        ctk.CTkLabel(self, text="Titulo (opcional - default: '<origem> -> <destino>'):").pack(anchor="w", padx=16)
        self.title_var = ctk.StringVar()
        ctk.CTkEntry(self, textvariable=self.title_var, width=440).pack(anchor="w", padx=16, pady=(2, 16))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=8)
        ctk.CTkButton(row, text="Criar MR", width=160, command=self._confirm).pack(side="left", padx=6)
        ctk.CTkButton(row, text="Cancelar", width=160, fg_color="gray40", command=self.destroy).pack(
            side="left", padx=6)

        self.grab_set()

    def _confirm(self):
        target = self.target_var.get().strip() or "main"
        title = self.title_var.get().strip() or None
        self.destroy()
        self.on_confirm(target, title)


class CommitReviewDialog(ctk.CTkToplevel):
    """Aberto antes de cada Commitar/Sincronizar individual: fica staging +
    gerando a mensagem (via IA/fallback) em background e mostra o resultado
    editavel - confirma pra commitar com o texto final (editado ou nao),
    cancela pra desfazer o staging (core.unstage) sem commitar nada."""

    def __init__(self, master, repo_path, on_confirm, confirm_label="Commitar"):
        super().__init__(master)
        self.title("Revisar mensagem do commit")
        self.geometry("560x300")
        self.resizable(False, False)
        _set_window_icon(self)
        self.repo_path = repo_path
        self.on_confirm = on_confirm
        self.root = master
        self.had_changes = False
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        ctk.CTkLabel(self, text="Mensagem do commit (gerada automaticamente - edite se quiser):",
                     font=ctk.CTkFont(weight="bold"), wraplength=520, justify="left").pack(
            anchor="w", padx=16, pady=(16, 8))

        self.textbox = ctk.CTkTextbox(self, height=110)
        self.textbox.insert("1.0", "gerando mensagem automaticamente...")
        self.textbox.configure(state="disabled")
        self.textbox.pack(fill="x", padx=16)

        self.status_lbl = ctk.CTkLabel(self, text="", text_color="gray", font=ctk.CTkFont(size=11))
        self.status_lbl.pack(anchor="w", padx=16, pady=(6, 0))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=20)
        self.confirm_btn = ctk.CTkButton(row, text=confirm_label, width=170, command=self._confirm, state="disabled")
        self.confirm_btn.pack(side="left", padx=6)
        ctk.CTkButton(row, text="Cancelar", width=170, fg_color="gray40", command=self._cancel).pack(side="left", padx=6)

        self.grab_set()
        run_bg(lambda: core.stage_and_generate_message(repo_path), self._on_staged, master)

    def _on_staged(self, result):
        if not self.winfo_exists():
            core.unstage(self.repo_path)
            return
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")

        if isinstance(result, Exception) or result.get("error"):
            err = result.get("error") if isinstance(result, dict) else str(result)
            self.status_lbl.configure(text=f"Erro ao preparar commit: {err}", text_color="#c0392b")
            self.textbox.configure(state="disabled")
            return

        if not result["hadChanges"]:
            self.status_lbl.configure(text="Sem alteracoes pendentes - nada a commitar.")
            self.textbox.configure(state="disabled")
            return

        self.had_changes = True
        self.textbox.insert("1.0", result["message"])
        self.confirm_btn.configure(state="normal")
        self.status_lbl.configure(text="Revise/edite se quiser, depois confirme.")

    def _confirm(self):
        text = self.textbox.get("1.0", "end").strip()
        if not text:
            messagebox.showerror("Erro", "A mensagem nao pode ficar vazia.", parent=self)
            return
        self.destroy()
        self.on_confirm(text)

    def _cancel(self):
        if self.had_changes:
            run_bg(lambda: core.unstage(self.repo_path), lambda r: None, self.root)
        self.destroy()


class AddRepoDialog(ctk.CTkToplevel):
    def __init__(self, master, on_added):
        super().__init__(master)
        self.title("Adicionar repositorio")
        self.geometry("520x300")
        self.minsize(520, 300)
        self.resizable(False, False)
        self.on_added = on_added
        _set_window_icon(self)
        self.grab_set()

        ctk.CTkLabel(self, text="Caminho:").pack(anchor="w", padx=16, pady=(16, 2))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=16)
        self.path_var = ctk.StringVar()
        ctk.CTkEntry(row, textvariable=self.path_var, width=340).pack(side="left")
        ctk.CTkButton(row, text="Procurar...", width=90, command=self._browse).pack(side="left", padx=(8, 0))

        ctk.CTkLabel(self, text="Tipo:").pack(anchor="w", padx=16, pady=(12, 2))
        self.type_var = ctk.StringVar(value="repo")
        ctk.CTkOptionMenu(self, values=["repo", "root"], variable=self.type_var, width=140).pack(anchor="w", padx=16)

        ctk.CTkButton(self, text="Adicionar", width=160, height=36, command=self._add).pack(pady=28)

    def _browse(self):
        d = filedialog.askdirectory(parent=self)
        if d:
            self.path_var.set(d)

    def _add(self):
        path = self.path_var.get().strip()
        if not path:
            messagebox.showerror("Erro", "Informe um caminho.", parent=self)
            return
        from pathlib import Path
        if not Path(path).exists():
            messagebox.showerror("Erro", "Caminho nao existe.", parent=self)
            return
        cfg = core.load_config()
        if any(t["path"] == path for t in cfg["targets"]):
            messagebox.showinfo("Aviso", "Esse alvo ja esta na lista.", parent=self)
            return
        cfg["targets"].append({"path": path, "type": self.type_var.get(), "enabled": True})
        core.save_config(cfg)
        self.on_added()
        self.destroy()


class CommitListPanel(ctk.CTkFrame):
    """Small scrollable list of {hash, date, message} rows."""

    def __init__(self, master):
        super().__init__(master, fg_color=("gray90", "gray17"))
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=8, pady=8)

    def set_loading(self):
        for w in self.body.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.body, text="carregando...", text_color="gray").pack(anchor="w")

    def set_commits(self, commits):
        for w in self.body.winfo_children():
            w.destroy()
        if not commits:
            ctk.CTkLabel(self.body, text="(sem commits no periodo)", text_color="gray").pack(anchor="w")
            return
        for c in commits:
            date = c["date"][:16].replace("T", " ")
            row = ctk.CTkFrame(self.body, fg_color="transparent")
            row.pack(fill="x", anchor="w", pady=1)
            ctk.CTkLabel(row, text=date, width=130, anchor="w", text_color="gray").pack(side="left")
            ctk.CTkLabel(row, text=c["message"], anchor="w", justify="left").pack(side="left", fill="x", expand=True)


class RepoCard(ctk.CTkFrame):
    """One repository: header (badge/last push/actions) + collapsible commit list."""

    CARD_WIDTH = 300

    def __init__(self, master, entry, root, on_changed, history_mode=False, compact=False):
        self.compact = compact
        super().__init__(master, corner_radius=6 if compact else 10, fg_color=("gray95", "gray20"))
        self.entry = entry
        self.path = entry["path"]
        self.manageable = entry["sourceType"] == "repo"
        self.source_path = entry["sourcePath"]
        self.root = root
        self.on_changed = on_changed
        self.history_mode = history_mode
        self.expanded = False
        self.since_preset = "all"
        name = self.path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]

        if compact:
            self._build_list_row(name, entry)
        else:
            self._build_card(name, entry)

        self.panel = None
        self.refresh()

    # ---- layout: modo "Lista" (1 por linha, tudo numa linha so) ----

    def _build_list_row(self, name, entry):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(6, 2))

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", fill="x", expand=True)
        title_row = ctk.CTkFrame(title_box, fg_color="transparent")
        title_row.pack(anchor="w", fill="x")
        ctk.CTkLabel(title_row, text=name, font=ctk.CTkFont(weight="bold", size=12), width=200,
                     anchor="w").pack(side="left")
        if not self.manageable:
            ctk.CTkLabel(title_row, text="(via pasta)", text_color="gray",
                         font=ctk.CTkFont(size=10, slant="italic")).pack(side="left", padx=(6, 0))

        self.pending_badge = ctk.CTkLabel(header, text="...", corner_radius=8, fg_color="gray40",
                                           text_color="white", padx=8, width=100)
        self.pending_badge.pack(side="left", padx=4)
        self.badge = ctk.CTkLabel(header, text="...", corner_radius=8, fg_color="gray40",
                                   text_color="white", padx=8, width=70)
        self.badge.pack(side="left", padx=4)
        self.last_push_lbl = ctk.CTkLabel(header, text="", text_color="gray", font=ctk.CTkFont(size=10))
        self.last_push_lbl.pack(side="left", padx=4)

        actions = header
        buttons = self._button_specs(entry)
        for text, kwargs in buttons:
            ctk.CTkButton(actions, text=text, width=66, **kwargs).pack(side="left", padx=(0, 4))
        self.expand_btn = ctk.CTkButton(actions, text="Ver commits ▾", width=66, fg_color="transparent",
                                         text_color=("gray20", "gray80"), hover_color=("gray85", "gray30"),
                                         command=self._toggle_expand)
        self.expand_btn.pack(side="left")

    # ---- layout: modo "Cards" (grade horizontal, poster estreito) ----

    def _build_card(self, name, entry):
        ctk.CTkFrame(self, width=self.CARD_WIDTH, height=1, fg_color="transparent").pack()  # forca a largura

        # topo: nome + caminho
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 6))
        ctk.CTkLabel(top, text=name, font=ctk.CTkFont(weight="bold"), wraplength=self.CARD_WIDTH - 24,
                     justify="left").pack(anchor="w")
        ctk.CTkLabel(top, text=self.path, text_color="gray", font=ctk.CTkFont(size=11),
                     wraplength=self.CARD_WIDTH - 24, justify="left").pack(anchor="w")
        if not self.manageable:
            ctk.CTkLabel(top, text=f"via pasta: {self.source_path}", text_color="gray",
                         font=ctk.CTkFont(size=11, slant="italic"), wraplength=self.CARD_WIDTH - 24,
                         justify="left").pack(anchor="w")

        # meio: os 2 badges + ultimo push
        middle = ctk.CTkFrame(self, fg_color="transparent")
        middle.pack(fill="x", padx=12, pady=(0, 6))
        self.pending_badge = ctk.CTkLabel(middle, text="...", corner_radius=8, fg_color="gray40",
                                           text_color="white", padx=10, width=self.CARD_WIDTH - 24)
        self.pending_badge.pack(fill="x", pady=(0, 4))
        self.badge = ctk.CTkLabel(middle, text="...", corner_radius=8, fg_color="gray40",
                                   text_color="white", padx=10, width=self.CARD_WIDTH - 24)
        self.badge.pack(fill="x", pady=(0, 4))
        self.last_push_lbl = ctk.CTkLabel(middle, text="ultimo push: ...", text_color="gray",
                                           font=ctk.CTkFont(size=11))
        self.last_push_lbl.pack(anchor="w")

        # base: botoes numa mini-grade de 2 colunas + ver commits full-width
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=12, pady=(0, 10))
        bottom.grid_columnconfigure((0, 1), weight=1)

        buttons = self._button_specs(entry)
        for i, (text, kwargs) in enumerate(buttons):
            ctk.CTkButton(bottom, text=text, **kwargs).grid(
                row=i // 2, column=i % 2, padx=3, pady=3, sticky="ew")

        expand_row = (len(buttons) + 1) // 2
        self.expand_btn = ctk.CTkButton(bottom, text="Ver commits ▾", fg_color="transparent",
                                         text_color=("gray20", "gray80"), hover_color=("gray85", "gray30"),
                                         command=self._toggle_expand)
        self.expand_btn.grid(row=expand_row, column=0, columnspan=2, padx=3, pady=(6, 0), sticky="ew")

    def _button_specs(self, entry):
        """Lista de (texto, kwargs) dos botoes de acao - compartilhada entre
        o modo Lista e o modo Cards, pra nao duplicar a lista de botoes."""
        if self.history_mode:
            return []
        specs = [
            ("Commitar", {"command": self._commit}),
            ("Push", {"command": self._push}),
            ("Sincronizar", {"command": self._sync}),
            ("Criar MR", {"fg_color": "#2a5d8a", "hover_color": "#204a70", "command": self._create_mr}),
        ]
        if self.manageable:
            enabled = entry.get("enabled", True)
            specs.append(("Desativar" if enabled else "Ativar",
                          {"fg_color": "gray50", "command": self._toggle_enabled}))
            specs.append(("Remover", {"fg_color": "#8a2c2c", "hover_color": "#6f2323", "command": self._remove}))
        else:
            specs.append(("Ignorar", {"fg_color": "#8a2c2c", "hover_color": "#6f2323",
                                      "command": self._exclude_from_root}))
        return specs

    # ---- data ----

    def refresh(self):
        if not self.winfo_exists():
            return
        prefix = "" if self.compact else "ultimo push: "
        self.pending_badge.configure(text="...", fg_color="gray40")
        self.badge.configure(text="...", fg_color="gray40")
        self.last_push_lbl.configure(text=f"{prefix}...")

        def load():
            status = core.load_status()
            entry = status.get("repos", {}).get(self.path, {})
            unpushed = core.get_unpushed_count(self.path)
            pending = core.has_pending_changes(self.path)
            return entry, unpushed, pending

        def done(result):
            if not self.winfo_exists():
                return  # card foi destruido (trocou de aba) antes do refresh voltar
            if isinstance(result, Exception):
                self.pending_badge.configure(text="erro", fg_color="#8a2c2c")
                self.badge.configure(text="erro", fg_color="#8a2c2c")
                return
            entry, unpushed, pending = result
            self.last_push_lbl.configure(text=f"{prefix}{human_relative(entry.get('lastPush'))}")

            if pending:
                self.pending_badge.configure(text="alteracao pendente", fg_color="#a67c1a")
            else:
                self.pending_badge.configure(text="sem alteracao", fg_color="#2f7a3d")

            if unpushed is None:
                self.badge.configure(text="sem remoto", fg_color="gray40")
            elif unpushed == 0:
                self.badge.configure(text="tudo enviado", fg_color="#2f7a3d")
            elif unpushed < 5:
                self.badge.configure(text=f"{unpushed} sem push", fg_color="#a67c1a")
            else:
                self.badge.configure(text=f"{unpushed} sem push", fg_color="#8a2c2c")

        run_bg(load, done, self.root)

    def _load_commits(self):
        if self.panel is None:
            return
        self.panel.set_loading()
        since = _since_from_preset(self.since_preset)
        limit = 200 if self.history_mode else 5

        def done(result):
            if not self.winfo_exists() or self.panel is None:
                return
            self.panel.set_commits([] if isinstance(result, Exception) else result)

        run_bg(lambda: core.get_commit_log(self.path, since=since, limit=limit), done, self.root)

    def set_since_preset(self, preset):
        self.since_preset = preset
        if self.expanded:
            self._load_commits()

    # ---- actions ----

    def _toggle_expand(self):
        self.expanded = not self.expanded
        if self.expanded:
            self.expand_btn.configure(text="Ocultar commits ▴")
            self.panel = CommitListPanel(self)
            self.panel.pack(fill="x", padx=12, pady=(0, 10))
            self._load_commits()
        else:
            self.expand_btn.configure(text="Ver commits ▾")
            if self.panel is not None:
                self.panel.destroy()
                self.panel = None

    def _commit(self):
        def on_confirm(message):
            run_bg(lambda: core.finalize_commit(self.path, message), lambda r: self._after_action(r), self.root)
        CommitReviewDialog(self.root, self.path, on_confirm, confirm_label="Commitar")

    def _push(self):
        decider = make_gui_push_decider(self.root, give_up_label="Cancelar")
        autofix = make_gui_autofix_confirm(self.root)
        run_bg(lambda: core.push_repo_checked(self.path, push_decider=decider, autofix_confirm=autofix),
               lambda r: self._after_action(r), self.root)

    def _sync(self):
        def on_confirm(message):
            decider = make_gui_push_decider(self.root, give_up_label="Apenas commit")
            autofix = make_gui_autofix_confirm(self.root)
            run_bg(lambda: core.finalize_sync(self.path, message, push_decider=decider, autofix_confirm=autofix),
                   lambda r: self._after_action(r), self.root)
        CommitReviewDialog(self.root, self.path, on_confirm, confirm_label="Commitar e enviar")

    def _create_mr(self):
        def on_confirm(target, title):
            def done(result):
                if not self.winfo_exists():
                    return
                if isinstance(result, Exception):
                    messagebox.showerror("Erro", str(result))
                elif result["success"]:
                    if messagebox.askyesno("MR pronta", f"{result['message']}\n\nAbrir no navegador?"):
                        webbrowser.open(result["url"])
                else:
                    messagebox.showerror("Erro ao criar MR", result["message"])
                self.refresh()
            run_bg(lambda: core.create_merge_request(self.path, target_branch=target, title=title),
                   done, self.root)
        CreateMRDialog(self.root, self.path, on_confirm)

    def _after_action(self, result):
        if not self.winfo_exists():
            return
        if isinstance(result, Exception):
            messagebox.showerror("Erro", str(result))
        elif not result.get("success"):
            messagebox.showerror("Operacao nao concluida", result.get("message", "Falha desconhecida."))
        self.refresh()
        if self.expanded:
            self._load_commits()

    def _toggle_enabled(self):
        cfg = core.load_config()
        for t in cfg["targets"]:
            if t["path"] == self.path:
                t["enabled"] = not t.get("enabled", True)
        core.save_config(cfg)
        self.on_changed()

    def _remove(self):
        if not messagebox.askyesno("Confirmar", f"Remover {self.path} da lista?"):
            return
        cfg = core.load_config()
        cfg["targets"] = [t for t in cfg["targets"] if t["path"] != self.path]
        core.save_config(cfg)
        self.on_changed()

    def _exclude_from_root(self):
        if not messagebox.askyesno("Confirmar", f"Ignorar {self.path}?\n\n"
                                                  f"O repositorio continua no disco, exatamente como esta - "
                                                  f"o autosync so para de sincroniza-lo dentro da pasta "
                                                  f"{self.source_path}."):
            return
        core.exclude_repo_from_root(self.source_path, self.path)
        self.on_changed()


THEME_OPTIONS = [("Sistema", "system"), ("Claro", "light"), ("Escuro", "dark")]


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        cfg = core.load_config()
        ctk.set_appearance_mode(cfg.get("theme", "system"))
        self.view_mode = cfg.get("viewMode", "card")
        self.title(f"Git AutoSync {app_module.get_version()}")
        self.geometry("1020x640")
        self.minsize(820, 520)
        _set_window_icon(self)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=16, pady=16)

        self.nav_buttons = {}
        self.current_view = None
        self.show_status()

    # ---- sidebar ----

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, width=SIDEBAR_WIDTH, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)

        ctk.CTkLabel(sidebar, text="Git AutoSync", font=ctk.CTkFont(size=18, weight="bold")).pack(
            anchor="w", padx=18, pady=(20, 24))

        ctk.CTkButton(sidebar, text="+ Adicionar repositorio", command=self._open_add_dialog).pack(
            fill="x", padx=14, pady=(0, 16))

        self._nav_frame = sidebar
        self._add_nav_button("Status", self.show_status)
        self._add_nav_button("Historico", self.show_history)
        self._add_nav_button("Agendamento", self.show_schedule)
        self._add_nav_button("Log", self.show_log)

        ctk.CTkLabel(sidebar, text=f"v{app_module.get_version()}", text_color="gray", font=ctk.CTkFont(size=11)).pack(
            side="bottom", pady=(0, 12))

        theme_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        theme_frame.pack(side="bottom", fill="x", padx=14, pady=(0, 4))
        ctk.CTkLabel(theme_frame, text="Tema:", font=ctk.CTkFont(size=11), text_color="gray").pack(anchor="w")
        current_theme = core.load_config().get("theme", "system")
        theme_label = next((l for l, v in THEME_OPTIONS if v == current_theme), "Sistema")
        theme_menu = ctk.CTkOptionMenu(theme_frame, values=[l for l, v in THEME_OPTIONS], width=170,
                                        command=self._on_theme_change)
        theme_menu.set(theme_label)
        theme_menu.pack(anchor="w", pady=(2, 0))

    def _add_nav_button(self, label, command):
        key = label.lower()

        def wrapped():
            command()
            self._highlight_nav(key)

        btn = ctk.CTkButton(self._nav_frame, text=label, anchor="w", fg_color="transparent",
                             text_color=("gray10", "gray90"), hover_color=("gray80", "gray30"),
                             command=wrapped)
        btn.pack(fill="x", padx=10, pady=2)
        self.nav_buttons = getattr(self, "nav_buttons", {})
        self.nav_buttons[key] = btn

    def _highlight_nav(self, key):
        for k, btn in self.nav_buttons.items():
            btn.configure(fg_color=("gray75", "gray28") if k == key else "transparent")

    def _on_theme_change(self, label):
        value = next(v for l, v in THEME_OPTIONS if l == label)
        ctk.set_appearance_mode(value)
        cfg = core.load_config()
        cfg["theme"] = value
        core.save_config(cfg)

    def _clear_content(self):
        for w in self.content.winfo_children():
            w.destroy()

    def _open_add_dialog(self):
        AddRepoDialog(self, on_added=self._refresh_current)

    def _refresh_current(self):
        if self.current_view == "status":
            self.show_status()
        elif self.current_view == "historico":
            self.show_history()

    # ---- Status view ----

    def show_status(self):
        self.current_view = "status"
        self._highlight_nav("status")
        self._clear_content()

        toolbar = ctk.CTkFrame(self.content, fg_color="transparent")
        toolbar.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(toolbar, text="Status dos repositorios", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        btns = ctk.CTkFrame(toolbar, fg_color="transparent")
        btns.pack(side="right")
        self._add_view_mode_toggle(btns, self.show_status)
        ctk.CTkButton(btns, text="Commitar tudo", command=self._commit_all).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Push tudo", command=self._push_all).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Sincronizar tudo", command=self._sync_all).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Atualizar", fg_color="gray40", command=self.show_status).pack(side="left", padx=4)

        cfg = core.load_config()
        entries = core.resolve_targets_detailed(cfg.get("targets", []), skip_disabled=False)
        scroll = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        if not entries:
            ctk.CTkLabel(scroll, text="Nenhum repositorio configurado ainda. Use '+ Adicionar repositorio'.",
                         text_color="gray").pack(pady=20)
            return

        compact = self.view_mode == "list"
        cards = [RepoCard(scroll, e, self, on_changed=self.show_status, compact=compact) for e in entries]
        _place_repo_cards(cards, compact)

    def _add_view_mode_toggle(self, parent, refresh_command):
        """Botao Lista/Card - troca self.view_mode, salva no config e
        reconstroi a view atual."""
        label = "▤ Lista" if self.view_mode == "card" else "▦ Cards"

        def toggle():
            self.view_mode = "list" if self.view_mode == "card" else "card"
            cfg = core.load_config()
            cfg["viewMode"] = self.view_mode
            core.save_config(cfg)
            refresh_command()

        ctk.CTkButton(parent, text=label, width=90, fg_color="gray40", command=toggle).pack(side="left", padx=4)

    def _commit_all(self):
        self._run_global_action(core.commit_all, "Commit em lote concluido.")

    def _push_all(self):
        decider = make_gui_push_decider(self, give_up_label="Cancelar")
        autofix = make_gui_autofix_confirm(self)
        self._run_global_action(lambda: core.push_all(push_decider=decider, autofix_confirm=autofix),
                                 "Push em lote concluido.")

    def _sync_all(self):
        decider = make_gui_push_decider(self, give_up_label="Apenas commit")
        autofix = make_gui_autofix_confirm(self)
        self._run_global_action(lambda: core.run_all(push_decider=decider, autofix_confirm=autofix),
                                 "Sincronizacao em lote concluida.")

    def _run_global_action(self, fn, done_message):
        def done(result):
            if isinstance(result, Exception):
                messagebox.showerror("Erro", str(result))
            else:
                failures = [(path, item.get("message", "falha")) for path, item in result.get("repos", {}).items()
                            if not item.get("success")]
                if failures:
                    details = "\n".join(f"{Path(path).name}: {message}" for path, message in failures[:8])
                    messagebox.showerror("Operacao incompleta", details)
                else:
                    messagebox.showinfo("Concluido", done_message)
            self.show_status()

        run_bg(fn, done, self)

    # ---- Historico view ----

    def show_history(self):
        self.current_view = "historico"
        self._highlight_nav("historico")
        self._clear_content()

        header = ctk.CTkFrame(self.content, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(header, text="Historico de commits", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")

        period_var = ctk.StringVar(value="Tudo")
        cards = []

        def on_period_change(label):
            preset = dict(HISTORY_PRESETS)[label]
            for c in cards:
                c.set_since_preset(preset)

        ctk.CTkOptionMenu(header, values=[l for l, _ in HISTORY_PRESETS], variable=period_var,
                          command=on_period_change, width=120).pack(side="right")
        self._add_view_mode_toggle(header, self.show_history)

        cfg = core.load_config()
        entries = core.resolve_targets_detailed(cfg.get("targets", []), skip_disabled=False)
        scroll = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        if not entries:
            ctk.CTkLabel(scroll, text="Nenhum repositorio configurado ainda.", text_color="gray").pack(pady=20)
            return

        compact = self.view_mode == "list"
        for e in entries:
            cards.append(RepoCard(scroll, e, self, on_changed=self.show_history, history_mode=True, compact=compact))
        _place_repo_cards(cards, compact)

    # ---- Agendamento view (config/monitoramento, sem commit/push manual) ----

    def show_schedule(self):
        self.current_view = "agendamento"
        self._highlight_nav("agendamento")
        self._clear_content()

        ctk.CTkLabel(self.content, text="Agendamento", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(self.content, text="A rodada agendada faz commit + push automaticamente, sem intervencao. "
                                         "Essa tela e so pra configurar horarios/tray, nao dispara sync manual.",
                     text_color="gray", wraplength=640, justify="left").pack(anchor="w", pady=(0, 16))

        cfg = core.load_config()

        row = ctk.CTkFrame(self.content, fg_color="transparent")
        row.pack(fill="x", pady=6)
        ctk.CTkLabel(row, text="Horarios (HH:mm, separados por virgula):").pack(anchor="w")
        times_var = ctk.StringVar(value=", ".join(cfg.get("schedules", [])))
        entry_row = ctk.CTkFrame(self.content, fg_color="transparent")
        entry_row.pack(fill="x", pady=(0, 12))
        ctk.CTkEntry(entry_row, textvariable=times_var, width=300).pack(side="left")

        def save_schedule():
            times = [t.strip() for t in times_var.get().split(",") if t.strip()]
            if not times:
                messagebox.showerror("Erro", "Informe ao menos um horario HH:mm.")
                return
            sync_target, _ = app_module.self_paths()
            try:
                core.install_schedule(sync_target, schedules=times, task_name=cfg["taskName"])
            except Exception as exc:
                messagebox.showerror("Erro ao instalar agendamento", str(exc))
                return
            core.pin_schedule_agent_if_created_by_skill()
            messagebox.showinfo("OK", f"Horarios salvos e tarefa agendada atualizada: {', '.join(times)}")

        ctk.CTkButton(entry_row, text="Salvar e reinstalar tarefa", command=save_schedule).pack(side="left", padx=8)

        ctk.CTkLabel(self.content, text="Agente de IA (gera a mensagem do commit):",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 2))
        agent_row = ctk.CTkFrame(self.content, fg_color="transparent")
        agent_row.pack(fill="x", pady=(0, 4))
        agent_label_by_value = {"auto": "Automatico", "claude": "Claude", "codex": "Codex", "opencode": "OpenCode"}
        agent_value_by_label = {v: k for k, v in agent_label_by_value.items()}

        def on_agent_change(label):
            cfg["aiAgent"] = agent_value_by_label[label]
            core.save_config(cfg)

        agent_menu = ctk.CTkOptionMenu(agent_row, values=list(agent_label_by_value.values()), width=160,
                                        command=on_agent_change)
        agent_menu.set(agent_label_by_value.get(cfg.get("aiAgent", "auto"), "Automatico"))
        agent_menu.pack(side="left")
        ai_var = ctk.BooleanVar(value=cfg.get("aiEnabled", False))
        def change_ai():
            current = core.load_config()
            current["aiEnabled"] = bool(ai_var.get())
            core.save_config(current)
        ctk.CTkCheckBox(agent_row, text="Permitir envio do diff a IA", variable=ai_var,
                        command=change_ai).pack(side="left", padx=12)

        schedule_agent = cfg.get("scheduleAgent")
        if schedule_agent:
            ctk.CTkLabel(self.content, text=f"Rodada agendada fixada em: {agent_label_by_value.get(schedule_agent, schedule_agent)} "
                                             f"(definido quando o agendamento foi criado por uma skill)",
                         text_color="gray", font=ctk.CTkFont(size=11)).pack(anchor="w", pady=(4, 0))

            def clear_schedule_agent():
                cfg["scheduleAgent"] = None
                core.save_config(cfg)
                self.show_schedule()

            ctk.CTkButton(self.content, text="Limpar (usar a preferencia geral na rodada agendada)",
                          fg_color="gray40", command=clear_schedule_agent).pack(anchor="w", pady=(4, 12))
        else:
            ctk.CTkLabel(self.content, text="Rodada agendada usa a preferencia geral acima (nenhum agente fixado).",
                         text_color="gray", font=ctk.CTkFont(size=11)).pack(anchor="w", pady=(4, 12))

        ctk.CTkLabel(self.content, text=f"Tray habilitada: {'sim' if cfg.get('trayEnabled') else 'nao'}",
                     text_color="gray").pack(anchor="w", pady=(0, 6))

        tray_row = ctk.CTkFrame(self.content, fg_color="transparent")
        tray_row.pack(fill="x", pady=4)

        def enable_tray():
            _, gui_target = app_module.self_paths()
            core.enable_tray_autostart(gui_target)
            messagebox.showinfo("OK", "Tray habilitada. Vai iniciar com o login.")
            self.show_schedule()

        def disable_tray():
            core.disable_tray_autostart()
            messagebox.showinfo("OK", "Tray desabilitada.")
            self.show_schedule()

        def uninstall_all():
            if not messagebox.askyesno("Confirmar", "Remover tarefa agendada e autostart da tray?"):
                return
            core.uninstall_schedule()
            core.disable_tray_autostart()
            messagebox.showinfo("OK", "Tarefa agendada e tray removidos.")
            self.show_schedule()

        ctk.CTkButton(tray_row, text="Habilitar tray", command=enable_tray).pack(side="left", padx=(0, 6))
        ctk.CTkButton(tray_row, text="Desabilitar tray", fg_color="gray40", command=disable_tray).pack(side="left", padx=(0, 6))
        ctk.CTkButton(tray_row, text="Desinstalar tudo", fg_color="#8a2c2c", hover_color="#6f2323",
                      command=uninstall_all).pack(side="left", padx=(0, 6))

        # ---- integracao GitLab (Merge Request pra branch protegida) ----

        ctk.CTkLabel(self.content, text="Integracao GitLab (Merge Requests):",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(20, 2))
        ctk.CTkLabel(self.content, text="Necessaria pro botao 'Criar MR' dos cards - branch protegida (ex: main) "
                                         "nao aceita push direto, so via Merge Request.",
                     text_color="gray", wraplength=640, justify="left", font=ctk.CTkFont(size=11)).pack(
            anchor="w", pady=(0, 6))

        has_env_token = bool(os.environ.get(core.GITLAB_TOKEN_ENV))
        has_cfg_token = bool(cfg.get("gitlabCredential"))
        if has_env_token:
            token_status = f"token ativo via variavel de ambiente {core.GITLAB_TOKEN_ENV} (tem prioridade)"
        elif has_cfg_token:
            token_status = f"token protegido para {cfg.get('gitlabHost', '')}"
        else:
            token_status = "nenhum token configurado ainda"
        ctk.CTkLabel(self.content, text=token_status, text_color="gray", font=ctk.CTkFont(size=11)).pack(anchor="w")

        token_row = ctk.CTkFrame(self.content, fg_color="transparent")
        token_row.pack(fill="x", pady=(4, 4))
        token_var = ctk.StringVar()
        host_var = ctk.StringVar(value=cfg.get("gitlabHost", ""))
        ctk.CTkEntry(token_row, textvariable=host_var, width=200,
                     placeholder_text="gitlab.empresa.com").pack(side="left", padx=4)
        ctk.CTkEntry(token_row, textvariable=token_var, width=280, show="*",
                     placeholder_text="Personal Access Token (escopo 'api')").pack(side="left")

        def save_token():
            t = token_var.get().strip()
            if not t:
                messagebox.showerror("Erro", "Informe um token.")
                return
            try:
                core.set_gitlab_token(t, host_var.get())
            except Exception as exc:
                messagebox.showerror("Erro ao salvar token", str(exc))
                return
            messagebox.showinfo("OK", "Token protegido e vinculado ao host informado.")
            self.show_schedule()

        def clear_token():
            core.clear_gitlab_token()
            messagebox.showinfo("OK", "Token removido.")
            self.show_schedule()

        ctk.CTkButton(token_row, text="Salvar", width=90, command=save_token).pack(side="left", padx=(8, 4))
        ctk.CTkButton(token_row, text="Remover", width=90, fg_color="gray40", command=clear_token).pack(side="left")

        target_row = ctk.CTkFrame(self.content, fg_color="transparent")
        target_row.pack(fill="x", pady=(10, 4))
        ctk.CTkLabel(target_row, text="Branch destino padrao das MRs:").pack(side="left")
        mr_target_var = ctk.StringVar(value=cfg.get("mrTargetBranch", "main"))
        ctk.CTkEntry(target_row, textvariable=mr_target_var, width=140).pack(side="left", padx=8)

        def save_mr_target():
            cfg["mrTargetBranch"] = mr_target_var.get().strip() or "main"
            core.save_config(cfg)
            messagebox.showinfo("OK", "Salvo.")

        ctk.CTkButton(target_row, text="Salvar", width=90, command=save_mr_target).pack(side="left")

    # ---- Log view ----

    def show_log(self):
        self.current_view = "log"
        self._highlight_nav("log")
        self._clear_content()

        header = ctk.CTkFrame(self.content, fg_color="transparent")
        header.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(header, text="Log", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        ctk.CTkButton(header, text="Atualizar", command=self.show_log).pack(side="right")

        box = ctk.CTkTextbox(self.content, wrap="none", font=ctk.CTkFont(family="Consolas", size=12))
        box.pack(fill="both", expand=True)
        if core.LOG_FILE.exists():
            text = core.LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]
            box.insert("1.0", "\n".join(text))
        else:
            box.insert("1.0", "Sem log ainda.")
        box.configure(state="disabled")


def _set_windows_app_id():
    """Sem isso, o Windows agrupa a janela na barra de tarefas pelo host do
    processo (pythonw.exe) ou pelo icone associado ao arquivo .py/.pyw sendo
    executado, ignorando o icone que a janela define — e mostra aquele icone
    generico de 'folha com o logo do Python' em vez do nosso. Precisa ser
    chamado ANTES de criar qualquer janela."""
    if not core.IS_WINDOWS:
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GitAutoSync.App")
    except Exception:
        pass


def run_gui():
    _set_windows_app_id()
    app = App()
    app.mainloop()
