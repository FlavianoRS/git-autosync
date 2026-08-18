#!/usr/bin/env bash
# Empacota o Git AutoSync em dois binarios standalone (nao precisa Python instalado
# na maquina de destino). Rodar este script NO LINUX (PyInstaller nao faz cross-compile:
# um binario Linux so pode ser gerado rodando este script em um Linux de verdade).
#
# Pre-requisitos no Linux:
#   sudo apt install python3-tk python3-dev   # tkinter para a GUI
#   pip install pystray Pillow pyinstaller
#   Para o icone da bandeja funcionar, o pystray precisa de um backend de tray do
#   ambiente grafico (AppIndicator/GTK no GNOME, ou similar no KDE/XFCE).
#
# Gera em ./dist/:
#   git-autosync        -> GUI + tray + CLI (binario com terminal, funciona para tudo)
#   git-autosync-sync   -> usado pela tarefa de cron, roda silencioso, loga em arquivo

set -euo pipefail
cd "$(dirname "$0")"

pyinstaller --noconfirm --onefile --name git-autosync app.py
pyinstaller --noconfirm --onefile --name git-autosync-sync run_sync.py

echo ""
echo "Prontos em: $(pwd)/dist/git-autosync e dist/git-autosync-sync"
