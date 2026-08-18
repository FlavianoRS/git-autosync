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
BIN_DIR = STATE_DIR / "bin"

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
    icon_ico = PYTHON_DIR / "assets" / "icon.ico"
    icon_png = PYTHON_DIR / "assets" / "icon.png"
    try:
        if IS_WINDOWS:
            pythonw = venv_pythonw(VENV_DIR)
            lnk_path = Path(os.environ["USERPROFILE"]) / "Desktop" / "Git AutoSync.lnk"
            ps_script = (
                '$sc = (New-Object -ComObject WScript.Shell).CreateShortcut($env:GAS_LNK)\n'
                '$sc.TargetPath = $env:GAS_PYTHONW\n'
                '$sc.Arguments = \'"\' + $env:GAS_LAUNCHER + \'"\'\n'
                '$sc.WorkingDirectory = Split-Path $env:GAS_LAUNCHER\n'
                'if ($env:GAS_ICON) { $sc.IconLocation = $env:GAS_ICON }\n'
                '$sc.Save()\n'
            )
            env = {**os.environ, "GAS_LNK": str(lnk_path), "GAS_PYTHONW": str(pythonw),
                    "GAS_LAUNCHER": str(launcher),
                    "GAS_ICON": str(icon_ico) if icon_ico.exists() else ""}
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_script],
                            check=True, capture_output=True, text=True, env=env)
            print(f"  Atalho criado: {lnk_path}")
        else:
            apps_dir = Path.home() / ".local" / "share" / "applications"
            apps_dir.mkdir(parents=True, exist_ok=True)
            desktop_file = apps_dir / "git-autosync.desktop"
            icon_line = f"Icon={icon_png}\n" if icon_png.exists() else ""
            desktop_file.write_text(
                "[Desktop Entry]\nType=Application\nName=Git AutoSync\n"
                f"Exec={venv_python(VENV_DIR)} {launcher}\nTerminal=false\n{icon_line}",
                encoding="utf-8",
            )
            print(f"  Atalho criado: {desktop_file}")
    except Exception as exc:
        print(f"  (aviso) nao consegui criar o atalho automatico: {exc}")


# ---------------- comando global 'git-autosync' ----------------

def create_cli_shim(py):
    """Cria um lancador chamado 'git-autosync' (nao 'app.py') pra rodar de
    dentro de qualquer repositorio: git-autosync commit|push|sync [--repo X]."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    app_py = PYTHON_DIR / "app.py"
    if IS_WINDOWS:
        shim = BIN_DIR / "git-autosync.bat"
        shim.write_text(f'@echo off\r\n"{py}" "{app_py}" %*\r\n', encoding="utf-8")
    else:
        shim = BIN_DIR / "git-autosync"
        shim.write_text(f'#!/usr/bin/env bash\nexec "{py}" "{app_py}" "$@"\n', encoding="utf-8")
        shim.chmod(shim.stat().st_mode | 0o111)
    return shim


def ensure_on_path(bin_dir):
    if IS_WINDOWS:
        current = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Environment]::GetEnvironmentVariable('Path','User')"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        entries = [e for e in current.split(";") if e]
        if str(bin_dir) in entries:
            print(f"  {bin_dir} ja esta no PATH do usuario.")
            return
        if not confirm(f"Adicionar {bin_dir} ao PATH (pra chamar 'git-autosync' de qualquer lugar)?",
                       default_yes=True):
            print(f"  Ok, PATH nao alterado. Pra usar sem isso, chame o script direto: {bin_dir}\\git-autosync.bat")
            return
        new_value = f"{current};{bin_dir}" if current else str(bin_dir)
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Environment]::SetEnvironmentVariable('Path', $env:GAS_NEWPATH, 'User')"],
            check=True, capture_output=True, text=True,
            env={**os.environ, "GAS_NEWPATH": new_value},
        )
        print("  PATH atualizado (variavel de usuario). Abra um terminal novo pra 'git-autosync' funcionar.")
    else:
        path_entries = os.environ.get("PATH", "").split(os.pathsep)
        if str(bin_dir) in path_entries:
            print(f"  {bin_dir} ja esta no PATH.")
            return
        print(f"  Adicione ao seu shell rc (~/.bashrc, ~/.zshrc, etc) e abra um terminal novo:")
        print(f'    export PATH="{bin_dir}:$PATH"')


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

    create_cli_shim(py)
    ensure_on_path(BIN_DIR)

    print(f"\nCLI pronta. Dentro de um repositorio: git-autosync commit | push | sync")
    print(f"Selecionando outro repo: git-autosync commit --repo <caminho>")
    print(f"(sem o comando no PATH, chame direto: \"{py}\" \"{PYTHON_DIR / 'app.py'}\" status)")


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
