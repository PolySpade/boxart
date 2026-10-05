#!/bin/bash
# Installs BoxArt for the current user: a virtualenv under ~/.local/share/boxart,
# a `boxart` launcher in ~/.local/bin, and a desktop entry with its icon.
set -euo pipefail
cd "$(dirname "$0")"
APP_ID=io.github.polyspade.BoxArt
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}"
VENV="$PREFIX/boxart/venv"

# Reuse distribution packages for PySide6/Pillow when they are installed.
python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/pip" install --quiet --upgrade .
mkdir -p "$HOME/.local/bin" "$PREFIX/applications" "$PREFIX/icons/hicolor/scalable/apps"
ln -sf "$VENV/bin/boxart" "$HOME/.local/bin/boxart"
install -m 644 "boxart/data/$APP_ID.svg" "$PREFIX/icons/hicolor/scalable/apps/$APP_ID.svg"
sed "s|^Exec=.*|Exec=$VENV/bin/boxart|" "data/$APP_ID.desktop" > "$PREFIX/applications/$APP_ID.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$PREFIX/applications" || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q "$PREFIX/icons/hicolor" || true
echo "Installed. Run 'boxart' or find BoxArt in your application menu."
