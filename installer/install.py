#!/usr/bin/env python3
"""Wizard de instalacao do Git AutoSync.

Deixa escolher Interface grafica / CLI / Skill (Claude Code ou Codex) -
pode marcar mais de um - e ja prepara o ambiente pra cada parte escolhida
(venv, dependencias, tarefa agendada, tray, atalho, copia da skill).

Roda igual em Windows e Linux: `python installer/install.py`.
"""
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON_DIR = REPO_ROOT / "python"
SKILL_SOURCE = REPO_ROOT / "skill" / "SKILL.md"
VERSION = (PYTHON_DIR / "VERSION").read_text(encoding="utf-8").strip()

STATE_DIR = Path.home() / ".git-autosync"
VENV_DIR = STATE_DIR / "venv"

SKILL_FILES = [
    "app.py", "autosync_core.py", "gui.py", "gui_launcher.pyw", "run_sync.py",
    "requirements.txt", "VERSION", "build_windows.ps1", "build_linux.sh",
]


def ask(prompt, default=None):
    suffix = f" [{default}]" if default else ""
    resp = input(f"{prompt}{suffix}: ").strip()
    return resp or (default or "")


def confirm(prompt, default_yes):
    default = "s" if default_yes else "n"
    return ask(f"{prompt} (s/n)", default=default).lower().startswith("s")


# ---------------- pre-requisitos ----------------

def check_prereqs():
    print("Verificando pre-requisitos...")
    if shutil.which("git") is None:
        print("  [ERRO] git nao encontrado no PATH. Instale o git antes de continuar.")
        sys.exit(1)
    print("  [OK] git encontrado.")
    if shutil.which("claude") is None:
        print("  [aviso] claude CLI nao encontrado - mensagens de commit vao usar o")
        print("          fallback 'chore: auto-commit <data>'. Nao impede a instalacao.")
    else:
        print("  [OK] claude CLI encontrado.")


def ask_components():
    print()
    print("O que voce quer instalar? (pode marcar mais de um, separado por virgula)")
    print("  1. Interface grafica + tray")
    print("  2. CLI (linha de comando)")
    print("  3. Skill (Claude Code / Codex)")
    raw = ask("Opcoes", default="1,2")
    picked = {p.strip() for p in raw.split(",") if p.strip()}
    return {"gui": "1" in picked, "cli": "2" in picked, "skill": "3" in picked}


# ---------------- venv ----------------

def venv_python(venv_dir):
    return venv_dir / ("Scripts/python.exe" if IS_WINDOWS else "bin/python3")


def venv_pythonw(venv_dir):
    return (venv_dir / "Scripts" / "pythonw.exe") if IS_WINDOWS else venv_python(venv_dir)


def create_venv():
    if VENV_DIR.exists():
        print(f"Reusando venv existente em {VENV_DIR}")
        return
    print(f"Criando venv em {VENV_DIR} ...")
    subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)


def pip_install_requirements():
    py = venv_python(VENV_DIR)
    print("Instalando dependencias da GUI (customtkinter, pystray, Pillow)...")
    subprocess.run([str(py), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=True)
    subprocess.run([str(py), "-m", "pip", "install", "--quiet", "-r",
                     str(PYTHON_DIR / "requirements.txt")], check=True)


# ---------------- atalho (Windows .lnk / Linux .desktop) ----------------

def create_shortcut(launcher):
    try:
        if IS_WINDOWS:
            pythonw = venv_pythonw(VENV_DIR)
            lnk_path = Path(os.environ["USERPROFILE"]) / "Desktop" / "Git AutoSync.lnk"
            ps_script = (
                '$sc = (New-Object -ComObject WScript.Shell).CreateShortcut($env:GAS_LNK)\n'
                '$sc.TargetPath = $env:GAS_PYTHONW\n'
                '$sc.Arguments = \'"\' + $env:GAS_LAUNCHER + \'"\'\n'
                '$sc.WorkingDirectory = Split-Path $env:GAS_LAUNCHER\n'
                '$sc.Save()\n'
            )
            env = {**os.environ, "GAS_LNK": str(lnk_path), "GAS_PYTHONW": str(pythonw),
                    "GAS_LAUNCHER": str(launcher)}
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_script],
                            check=True, capture_output=True, text=True, env=env)
            print(f"  Atalho criado: {lnk_path}")
        else:
            apps_dir = Path.home() / ".local" / "share" / "applications"
            apps_dir.mkdir(parents=True, exist_ok=True)
            desktop_file = apps_dir / "git-autosync.desktop"
            desktop_file.write_text(
                "[Desktop Entry]\nType=Application\nName=Git AutoSync\n"
                f"Exec={venv_python(VENV_DIR)} {launcher}\nTerminal=false\n",
                encoding="utf-8",
            )
            print(f"  Atalho criado: {desktop_file}")
    except Exception as exc:
        print(f"  (aviso) nao consegui criar o atalho automatico: {exc}")


# ---------------- instalacao por componente ----------------

def install_gui():
    print("\n--- Interface grafica + tray ---")
    create_venv()
    pip_install_requirements()
    py = venv_python(VENV_DIR)
    launcher = PYTHON_DIR / "gui_launcher.pyw"

    if confirm("Habilitar tarefa agendada + tray no login agora?", default_yes=True):
        subprocess.run([str(py), str(PYTHON_DIR / "app.py"), "enable-tray"], check=False)

    if confirm("Criar atalho na area de trabalho?", default_yes=True):
        create_shortcut(launcher)

    print(f"\nGUI instalada. Pra abrir manualmente: \"{venv_pythonw(VENV_DIR)}\" \"{launcher}\"")


def install_cli(components):
    print("\n--- CLI ---")
    py = venv_python(VENV_DIR) if VENV_DIR.exists() else Path(sys.executable)
    default_yes = not components["gui"]
    if confirm("Instalar a tarefa agendada agora (so commit+push automatico, sem GUI/tray)?",
               default_yes=default_yes):
        subprocess.run([str(py), str(PYTHON_DIR / "app.py"), "install"], check=False)
    print(f"\nCLI pronta. Exemplo: \"{py}\" \"{PYTHON_DIR / 'app.py'}\" status")


def install_skill():
    print("\n--- Skill (Claude Code / Codex) ---")
    targets = [Path.home() / ".claude" / "skills" / "git-autosync"]
    if (Path.home() / ".codex").exists():
        targets.append(Path.home() / ".codex" / "skills" / "git-autosync")

    skill_md = SKILL_SOURCE.read_text(encoding="utf-8")
    skill_md = re.sub(r"(?m)^version:\s*.*$", f"version: {VERSION}", skill_md, count=1)

    for target in targets:
        scripts_dir = target / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        for name in SKILL_FILES:
            src = PYTHON_DIR / name
            if src.exists():
                shutil.copy2(src, scripts_dir / name)
        (target / "SKILL.md").write_text(skill_md, encoding="utf-8")
        print(f"  Skill instalada em: {target}")


def main():
    print(f"=== Instalador Git AutoSync v{VERSION} ===\n")
    check_prereqs()
    components = ask_components()
    if not any(components.values()):
        print("Nada selecionado, saindo.")
        return

    if components["gui"]:
        install_gui()
    if components["cli"]:
        install_cli(components)
    if components["skill"]:
        install_skill()

    print("\nInstalacao concluida.")


if __name__ == "__main__":
    main()
