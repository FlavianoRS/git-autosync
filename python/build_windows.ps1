# Empacota o Git AutoSync em dois executaveis standalone (nao precisa Python instalado
# na maquina de destino). Rodar este script NO WINDOWS.
#
# Gera em .\dist\:
#   git-autosync.exe       -> GUI + tray (janela, sem console). Tambem aceita args de CLI,
#                              mas sem console a saida de texto nao aparece - para CLI use
#                              "python app.py <comando>" direto.
#   git-autosync-sync.exe  -> usado pela tarefa agendada/cron, roda silencioso, loga em arquivo.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

pyinstaller --noconfirm git-autosync.spec
pyinstaller --noconfirm git-autosync-sync.spec

Write-Host ""
Write-Host "Prontos em: $PSScriptRoot\dist\git-autosync.exe e dist\git-autosync-sync.exe"
