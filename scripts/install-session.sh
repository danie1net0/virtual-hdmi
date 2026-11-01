#!/usr/bin/env bash
#
# install-session.sh
# Installs keep-session.sh as a systemd service, so the auto-login session
# becomes the active one again if GDM opens the login screen on top of it.
#
# Usage (on the machine, in the project folder):
#   sudo bash scripts/install-session.sh
#
# ROOT=/folder writes the files under /folder instead of / (used by the tests).
#
# To undo:
#   sudo systemctl disable --now keep-session.service
#   sudo rm /etc/systemd/system/keep-session.service /usr/local/sbin/keep-session.sh

set -euo pipefail

[[ "$(id -u)" -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }

DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="${ROOT:-}"
SCRIPT="/usr/local/sbin/keep-session.sh"
SERVICE="$ROOT/etc/systemd/system/keep-session.service"

echo "==> Installing $SCRIPT"
mkdir -p "$ROOT/usr/local/sbin" "$(dirname "$SERVICE")"
install -m 755 "$DIR/keep-session.sh" "$ROOT$SCRIPT"

echo "==> Creating the keep-session.service service"
cat > "$SERVICE" <<EOF
[Unit]
Description=Keeps the GDM auto-login session active
After=gdm.service
Wants=gdm.service

[Service]
Type=simple
ExecStart=$SCRIPT

[Install]
WantedBy=graphical.target
EOF

systemctl daemon-reload
systemctl enable keep-session.service
echo
echo "Done. The service runs during the first 5 minutes of each boot."
echo "Log: journalctl -u keep-session"
