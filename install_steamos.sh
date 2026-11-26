#!/usr/bin/env bash
set -euo pipefail

# Installer for SteamOS / Steam Deck (survives SteamOS immutable root updates
# because everything lives inside ~/.local/share/WinYandexMusicRPC).

APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/WinYandexMusicRPC"
VENV_DIR="$APP_DIR/venv"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Installing WinYandexMusicRPC for SteamOS / Linux ==="
mkdir -p "$APP_DIR"

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 not found. Please install Python 3.12+ (or use distrobox/flatpak)."
    exit 1
fi

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -e "$REPO_DIR"

# Desktop entry for Desktop Mode application launcher
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/WinYandexMusicRPC.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Yandex Music RPC
Comment=Yandex Music Discord Rich Presence
Exec="$VENV_DIR/bin/python" "$REPO_DIR/gui_app.py"
Icon=$REPO_DIR/assets/YMRPC_ico.ico
Terminal=false
Categories=AudioVideo;Music;
EOF

# Background systemd user service so RPC works in Steam Gaming Mode too
SYSTEMD_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$SYSTEMD_DIR"
cat > "$SYSTEMD_DIR/winyandexmusicrpc.service" <<EOF
[Unit]
Description=WinYandexMusicRPC (Yandex Music Discord Rich Presence)
After=graphical-session.target

[Service]
Type=simple
WorkingDirectory=$REPO_DIR
ExecStart=$VENV_DIR/bin/python $REPO_DIR/gui_app.py --headless
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload || true
    systemctl --user enable --now winyandexmusicrpc.service || true
    echo "Background service enabled (works in Gaming Mode too)."
fi

echo "Done! Launch 'Yandex Music RPC' from Desktop Mode menu or check status:"
echo "  systemctl --user status winyandexmusicrpc.service"
