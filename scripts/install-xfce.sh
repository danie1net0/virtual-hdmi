#!/usr/bin/env bash
#
# install-xfce.sh
# Installs a light session (XFCE on X11 + LightDM, with auto-login) next to
# GNOME, for the monitorless machine. GNOME stays installed: only the login
# manager changes from GDM to LightDM. This script restarts nothing.
#
# Usage (on the machine, in the project folder):
#   sudo bash scripts/install-xfce.sh [user]           # default: the GDM auto-login user
#
# ROOT=/folder writes the files under /folder instead of / (used by the tests).
#
# To go back to GNOME with GDM:
#   sudo systemctl enable gdm3.service && sudo reboot

set -euo pipefail

[[ "$(id -u)" -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }

ROOT="${ROOT:-}"
USER_NAME="${1:-$(sed -n 's/^AutomaticLogin *= *//p' "$ROOT/etc/gdm3/custom.conf" 2>/dev/null | tail -1 || true)}"
[[ -n "$USER_NAME" ]] || { echo "Give the user: sudo bash scripts/install-xfce.sh <user>" >&2; exit 1; }
id "$USER_NAME" >/dev/null || { echo "User $USER_NAME does not exist." >&2; exit 1; }

echo "==> Installing XFCE, LightDM and the X server"
export DEBIAN_FRONTEND=noninteractive
echo "lightdm shared/default-x-display-manager select lightdm" | debconf-set-selections
apt-get update
apt-get install -y --no-install-recommends \
    xfce4 xfce4-terminal xfce4-settings lightdm lightdm-gtk-greeter \
    xserver-xorg xserver-xorg-core x11-xserver-utils dbus-x11

# Polkit agent: pkexec from the Install EDID button needs one to ask for the password
agent=""
for package in policykit-1-gnome polkit-gnome lxpolkit mate-polkit; do
    if apt-cache policy "$package" 2>/dev/null | grep -q '^ *Candidate: *[^( ]'; then
        agent="$package"
        break
    fi
done
if [[ -n "$agent" ]]; then
    apt-get install -y --no-install-recommends "$agent"
    echo "    polkit agent: $agent"
else
    echo "    Warning: no polkit agent available; the Install EDID button will not ask for the password." >&2
fi

echo "==> Auto-login of $USER_NAME in the XFCE session"
mkdir -p "$ROOT/etc/lightdm/lightdm.conf.d" "$ROOT/etc/X11"
cat > "$ROOT/etc/lightdm/lightdm.conf.d/50-autologin-xfce.conf" <<EOF
[Seat:*]
autologin-user=$USER_NAME
autologin-user-timeout=0
autologin-session=xfce
user-session=xfce
EOF

echo "==> LightDM as the login manager"
echo /usr/sbin/lightdm > "$ROOT/etc/X11/default-display-manager"
systemctl enable --force lightdm.service

echo
echo "Done. Reboot with: sudo reboot"
echo "After boot: python3 virtual-monitor.py --list    (should show X11 (xrandr))"
echo "To go back to GNOME: sudo systemctl enable gdm3.service && sudo reboot"
