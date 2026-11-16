#!/usr/bin/env bash
#
# auto-login.sh
# Turns automatic login on (or off) in the display manager, so a machine with no monitor opens the
# desktop session at boot: the remote desktop server, the virtual monitor and virtual-monitor over
# SSH all need that session. Usually run by the app: virtual-monitor --auto-login [on|off].
#
# Finds the display manager from display-manager.service: GDM, SDDM, LightDM or greetd (COSMIC's
# cosmic-greeter included). Keeps a *.before-auto-login copy of every file it edits.
#
# Usage:
#   sudo bash scripts/auto-login.sh USER [on|off]
#
# ROOT=/folder reads and writes the files under /folder instead of / (used by the tests).

set -euo pipefail

fail() {
    echo "$1" >&2
    exit 1
}

[[ "$(id -u)" -eq 0 ]] || fail "Run with sudo."

ROOT="${ROOT:-}"
USER_NAME="${1:-}"
STATE="${2:-on}"
SESSION_FOLDERS=("$ROOT/usr/share/wayland-sessions" "$ROOT/usr/share/xsessions")

[[ "$USER_NAME" =~ ^[a-z_][a-z0-9_.-]*$ ]] || fail "Give the user: sudo bash scripts/auto-login.sh <user> [on|off]"
[[ "$STATE" == on || "$STATE" == off ]] || fail "Use on or off, not $STATE."
id "$USER_NAME" >/dev/null 2>&1 || fail "User $USER_NAME does not exist."

# Rewrites a file in place, keeping its owner and permissions
rewrite() {
    local file="$1" content="$2"
    printf '%s\n' "$content" > "$file"
}

backup() {
    local file="$1"
    [[ -f "$file" && ! -f "$file.before-auto-login" ]] || return 0
    cp "$file" "$file.before-auto-login"
}

# Name of the unit display-manager.service points to (gdm3, sddm, lightdm, greetd...), or nothing
display_manager() {
    local unit="$ROOT/etc/systemd/system/display-manager.service"
    [[ -L "$unit" ]] || return 0
    basename "$(readlink "$unit")" .service
}

# The first desktop session installed, Wayland before X11
session_file() {
    local folder file
    for folder in "${SESSION_FOLDERS[@]}"; do
        for file in "$folder"/*.desktop; do
            [[ -f "$file" ]] || continue
            echo "$file"
            return
        done
    done
}

session_name() {
    local file
    file="$(session_file)"
    [[ -n "$file" ]] || return 0
    basename "$file" .desktop
}

configure_gdm() {
    local file="$ROOT/etc/$1/custom.conf" content
    mkdir -p "$(dirname "$file")"
    backup "$file"
    [[ -f "$file" ]] || : > "$file"
    grep -q '^\[daemon\]' "$file" || echo "[daemon]" >> "$file"

    content="$(awk -v state="$STATE" -v user="$USER_NAME" '
        /^[[:space:]]*AutomaticLogin(Enable)?[[:space:]]*=/ { next }
        { print }
        /^\[daemon\]/ && state == "on" { print "AutomaticLoginEnable=true"; print "AutomaticLogin=" user }
    ' "$file")"
    rewrite "$file" "$content"
    echo "    $file"
}

configure_sddm() {
    local file="$ROOT/etc/sddm.conf.d/virtual-monitor-autologin.conf"
    rm -f "$file"
    [[ "$STATE" == on ]] || return 0

    mkdir -p "$(dirname "$file")"
    printf '[Autologin]\nUser=%s\nSession=%s\n' "$USER_NAME" "$(session_name)" > "$file"
    echo "    $file"
}

# Some distributions only let members of the autologin group log in automatically
join_autologin_group() {
    grep -q '^autologin:' "$ROOT/etc/group" 2>/dev/null || return 0
    gpasswd -a "$USER_NAME" autologin
}

configure_lightdm() {
    local file="$ROOT/etc/lightdm/lightdm.conf.d/60-virtual-monitor-autologin.conf" session
    rm -f "$file"
    [[ "$STATE" == on ]] || return 0

    mkdir -p "$(dirname "$file")"
    printf '[Seat:*]\nautologin-user=%s\nautologin-user-timeout=0\n' "$USER_NAME" > "$file"
    session="$(session_name)"
    [[ -z "$session" ]] || echo "autologin-session=$session" >> "$file"
    join_autologin_group
    echo "    $file"
}

greetd_config() {
    local file
    for file in "$ROOT/etc/greetd/cosmic-greeter.toml" "$ROOT/etc/greetd/config.toml"; do
        [[ -f "$file" ]] || continue
        echo "$file"
        return
    done
}

# The command greetd runs for the automatic session: COSMIC's, else the first session's Exec line
greetd_command() {
    local file
    if command -v start-cosmic >/dev/null 2>&1; then
        echo start-cosmic
        return
    fi

    file="$(session_file)"
    [[ -n "$file" ]] || return 0
    sed -n 's/^Exec=//p' "$file" | head -n 1
}

configure_greetd() {
    local file command content
    file="$(greetd_config)"
    [[ -n "$file" ]] || fail "greetd has no configuration in $ROOT/etc/greetd."
    backup "$file"

    # The [initial_session] table is the automatic login; drop the old one before adding the new
    content="$(awk '/^\[initial_session\]/ { skip = 1; next } /^\[/ { skip = 0 } !skip' "$file")"
    rewrite "$file" "$content"
    echo "    $file"
    [[ "$STATE" == on ]] || return 0

    command="$(greetd_command)"
    [[ -n "$command" ]] || fail "No desktop session found for greetd to start."
    printf '\n[initial_session]\ncommand = "%s"\nuser = "%s"\n' "$command" "$USER_NAME" >> "$file"
}

MANAGER="$(display_manager)"
echo "==> Automatic login of $USER_NAME: $STATE (${MANAGER:-no display manager})"
case "$MANAGER" in
    gdm3) configure_gdm gdm3 ;;
    gdm) configure_gdm gdm ;;
    sddm) configure_sddm ;;
    lightdm) configure_lightdm ;;
    greetd | cosmic-greeter) configure_greetd ;;
    *) fail "Unknown display manager (${MANAGER:-none}): turn automatic login on in its settings." ;;
esac

echo
echo "Done. It takes effect at the next boot: sudo reboot"
[[ "$STATE" == on ]] || exit 0
echo "Anyone at the machine now gets the desktop without a password; remote access keeps its own."
