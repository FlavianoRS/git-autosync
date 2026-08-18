#!/usr/bin/env bash
# Instalador standalone: usa os binarios ja empacotados em python/dist/
# (git-autosync / git-autosync-sync), sem exigir Python nesta maquina.
# Alguem do time precisa ter gerado esses binarios antes, com
# ./python/build_linux.sh (isso sim exige Python, mas so na maquina de
# quem gera - quem so instala nao precisa de nada).
set -e
cd "$(dirname "$0")/.."

DIST="$(pwd)/python/dist"
BIN_GUI="$DIST/git-autosync"
BIN_SYNC="$DIST/git-autosync-sync"
BINDIR="$HOME/.git-autosync/bin"

if [ ! -f "$BIN_GUI" ] || [ ! -f "$BIN_SYNC" ]; then
    echo "Nao encontrei $BIN_GUI / $BIN_SYNC."
    echo "Peca pra alguem com Python gerar com: ./python/build_linux.sh"
    exit 1
fi

echo "=== Instalador standalone Git AutoSync (sem Python) ==="
echo

mkdir -p "$BINDIR"
cp "$BIN_GUI" "$BINDIR/git-autosync"
cp "$BIN_SYNC" "$BINDIR/git-autosync-sync"
chmod +x "$BINDIR/git-autosync" "$BINDIR/git-autosync-sync"
echo "Copiado para $BINDIR"
echo

read -r -p "Instalar tarefa cron (commit+push automatico as 17:30)? (s/n) [s]: " INSTALL_TASK
INSTALL_TASK=${INSTALL_TASK:-s}
if [[ "$INSTALL_TASK" =~ ^[sS]$ ]]; then
    (crontab -l 2>/dev/null | grep -v '# git-autosync'; echo "30 17 * * * \"$BINDIR/git-autosync-sync\" # git-autosync") | crontab -
    echo "  Tarefa cron instalada (17:30)."
fi
echo

read -r -p "Criar atalho de menu (.desktop)? (s/n) [s]: " SHORTCUT
SHORTCUT=${SHORTCUT:-s}
if [[ "$SHORTCUT" =~ ^[sS]$ ]]; then
    mkdir -p "$HOME/.local/share/applications"
    cat > "$HOME/.local/share/applications/git-autosync.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Git AutoSync
Exec=$BINDIR/git-autosync
Terminal=false
EOF
    echo "  Atalho criado."
fi

echo
echo "Instalacao concluida. Falta so adicionar seus repositorios:"
echo "  $BINDIR/git-autosync add <caminho do repo> --type repo"
echo "Ou abra a GUI direto: $BINDIR/git-autosync"
