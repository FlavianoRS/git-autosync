#!/usr/bin/env bash
# Rode este arquivo pra instalar o Git AutoSync no Linux/macOS.
# Detecta Python automaticamente; se nao achar, tenta a versao standalone
# (binario pronto, sem precisar de Python) ou explica como resolver.
set -e
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
    python3 installer/install.py
    exit 0
fi
if command -v python >/dev/null 2>&1; then
    python installer/install.py
    exit 0
fi

echo
echo "Python nao foi encontrado nesta maquina."
echo

if [ -f "python/dist/git-autosync" ]; then
    echo "Encontrei um binario ja pronto em python/dist/ - esse NAO precisa de"
    echo "Python instalado. Instalando a versao standalone..."
    echo
    chmod +x installer/install_standalone.sh
    ./installer/install_standalone.sh
    exit 0
fi

echo "Pra instalar, escolha uma das opcoes:"
echo
echo "  1. Instale o Python (https://www.python.org/downloads/) e rode este"
echo "     script de novo."
echo
echo "  2. Peca pra alguem do time que ja tenha Python instalado rodar:"
echo "       ./python/build_linux.sh"
echo "     e te passar os dois arquivos gerados em python/dist/"
echo "     (git-autosync e git-autosync-sync). Com eles no lugar, rode este"
echo "     instalar.sh de novo - vai direto pra versao standalone, sem"
echo "     precisar de Python nesta maquina."
echo
