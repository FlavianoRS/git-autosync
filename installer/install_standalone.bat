@echo off
rem Instalador standalone: usa os .exe ja empacotados em python\dist\
rem (git-autosync.exe / git-autosync-sync.exe), sem exigir Python nesta
rem maquina. Alguem do time precisa ter gerado esses .exe antes, com
rem python\build_windows.ps1 (isso sim exige Python, mas so na maquina
rem de quem gera - quem so instala nao precisa de nada).
setlocal enabledelayedexpansion
cd /d "%~dp0.."

set "DIST=%CD%\python\dist"
set "EXE_GUI=%DIST%\git-autosync.exe"
set "EXE_SYNC=%DIST%\git-autosync-sync.exe"
set "BINDIR=%USERPROFILE%\.git-autosync\bin"

if not exist "%EXE_GUI%" (
    echo Nao encontrei "%EXE_GUI%".
    echo Peca pra alguem com Python gerar com: python\build_windows.ps1
    goto :fim
)
if not exist "%EXE_SYNC%" (
    echo Nao encontrei "%EXE_SYNC%".
    echo Peca pra alguem com Python gerar com: python\build_windows.ps1
    goto :fim
)

echo === Instalador standalone Git AutoSync (sem Python) ===
echo.

if not exist "%BINDIR%" mkdir "%BINDIR%"
copy /y "%EXE_GUI%" "%BINDIR%\git-autosync.exe" >nul
copy /y "%EXE_SYNC%" "%BINDIR%\git-autosync-sync.exe" >nul
echo Copiado para %BINDIR%
echo.

set "INSTALL_TASK=s"
set /p INSTALL_TASK="Instalar tarefa agendada (commit+push automatico as 17:30)? (s/n) [s]: "
if /i "%INSTALL_TASK%"=="s" (
    schtasks /Create /TN "GitAutoSyncPy_0" /TR "\"%BINDIR%\git-autosync-sync.exe\"" /SC DAILY /ST 17:30 /F >nul
    echo   Tarefa agendada instalada (17:30). Pra mudar o horario depois, use a GUI
    echo   (aba Agendamento) ou "%BINDIR%\git-autosync.exe" set-schedule "HH:mm".
)
echo.

set "ENABLE_TRAY=s"
set /p ENABLE_TRAY="Habilitar icone na bandeja, iniciando com o login? (s/n) [s]: "
if /i "%ENABLE_TRAY%"=="s" (
    set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
    (
        echo @echo off
        echo start "" "%BINDIR%\git-autosync.exe" --tray
    ) > "%STARTUP%\GitAutoSyncTray.bat"
    echo   Tray configurada para iniciar com o login.
)
echo.

set "SHORTCUT=s"
set /p SHORTCUT="Criar atalho na area de trabalho? (s/n) [s]: "
if /i "%SHORTCUT%"=="s" (
    powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%USERPROFILE%\Desktop\Git AutoSync.lnk'); $s.TargetPath='%BINDIR%\git-autosync.exe'; $s.WorkingDirectory='%BINDIR%'; $s.Save()"
    echo   Atalho criado na area de trabalho.
)

echo.
echo Instalacao concluida. Falta so adicionar seus repositorios:
echo   "%BINDIR%\git-autosync.exe" add "<caminho do repo>" --type repo
echo Ou abra a GUI direto: "%BINDIR%\git-autosync.exe"

:fim
pause
