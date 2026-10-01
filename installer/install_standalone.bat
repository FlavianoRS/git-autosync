@echo off
rem Instalador standalone: usa os .exe ja empacotados em python\dist\
rem (git-autosync.exe / git-autosync-sync.exe), sem exigir Python nesta
rem maquina. Alguem do time precisa ter gerado esses .exe antes, com
rem python\build_windows.ps1 (isso sim exige Python, mas so na maquina
rem de quem gera - quem so instala nao precisa de nada).
rem
rem Este arquivo hoje so faz as perguntas: quem instala e o
rem install-standalone.ps1, o mesmo script que o instalador do Sankhya Hub
rem chama em modo silencioso. Ter dois instaladores independentes saia caro:
rem a tarefa agendada era criada aqui com schtasks direto, com um nome que a
rem interface do autosync nao reconhecia como dela - e a reinstalacao
rem deixava duas tarefas rodando o mesmo sync.
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PS1=%CD%\install-standalone.ps1"
if not exist "%PS1%" (
    echo Nao encontrei "%PS1%".
    goto :fim
)

echo === Instalador standalone Git AutoSync (sem Python) ===
echo.

set "OPCOES="

set "INSTALL_TASK=s"
set /p INSTALL_TASK="Instalar tarefa agendada (commit+push automatico as 17:30)? (s/n) [s]: "
if /i "!INSTALL_TASK!"=="s" set "OPCOES=!OPCOES! -TaskTime 17:30"

set "ENABLE_TRAY=s"
set /p ENABLE_TRAY="Habilitar icone na bandeja, iniciando com o login? (s/n) [s]: "
if /i "!ENABLE_TRAY!"=="s" set "OPCOES=!OPCOES! -EnableTray"

set "SHORTCUT=s"
set /p SHORTCUT="Criar atalhos (area de trabalho e menu Iniciar)? (s/n) [s]: "
if /i "!SHORTCUT!"=="s" set "OPCOES=!OPCOES! -Shortcut"

set "SKILLS=s"
set /p SKILLS="Instalar a skill do git-autosync para os agentes de IA? (s/n) [s]: "
if /i "!SKILLS!"=="s" set "OPCOES=!OPCOES! -Skills"

set "ADDPATH=n"
set /p ADDPATH="Adicionar a pasta bin ao PATH do usuario? (s/n) [n]: "
if /i "!ADDPATH!"=="s" set "OPCOES=!OPCOES! -AddToPath"

echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" !OPCOES!
if errorlevel 1 (
    echo.
    echo A instalacao falhou. Nada foi agendado.
    goto :fim
)

echo.
echo Instalacao concluida. Falta so adicionar seus repositorios:
echo   "%USERPROFILE%\.git-autosync\bin\git-autosync.exe" add "<caminho do repo>" --type repo
echo Ou abra a GUI direto: "%USERPROFILE%\.git-autosync\bin\git-autosync.exe"

:fim
pause
