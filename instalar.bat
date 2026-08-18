@echo off
rem Duplo clique neste arquivo pra instalar o Git AutoSync no Windows.
rem Detecta Python automaticamente; se nao achar, tenta a versao standalone
rem (executavel pronto, sem precisar de Python) ou explica como resolver.
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python installer\install.py
    goto :fim
)
where python3 >nul 2>nul
if %ERRORLEVEL%==0 (
    python3 installer\install.py
    goto :fim
)

echo.
echo Python nao foi encontrado nesta maquina.
echo.
if exist "python\dist\git-autosync.exe" (
    echo Encontrei um executavel ja pronto em python\dist\ - esse NAO precisa
    echo de Python instalado. Instalando a versao standalone...
    echo.
    call installer\install_standalone.bat
    goto :fim
)

echo Pra instalar, escolha uma das opcoes:
echo.
echo   1. Instale o Python (https://www.python.org/downloads/) - marque a
echo      caixa "Add python.exe to PATH" na tela do instalador - e rode este
echo      arquivo de novo.
echo.
echo   2. Peca pra alguem do time que ja tenha Python instalado rodar:
echo        python\build_windows.ps1
echo      e te passar os dois arquivos gerados em python\dist\
echo      (git-autosync.exe e git-autosync-sync.exe). Com eles no lugar,
echo      rode este instalar.bat de novo - vai direto pra versao standalone,
echo      sem precisar de Python nesta maquina.
echo.

:fim
pause
