#!/usr/bin/env bash
#
# auto-login.sh
# Turns automatic login on (or off) in the display manager, so a machine with no monitor opens the
# desktop session at boot: the remote desktop server, the virtual monitor and virtual-monitor over
# SSH all need that session. Usually run by the app: virtual-monitor --auto-login [on|off].
#
# Finds the display manager from display-manager.service: GDM, SDDM, LightDM or greetd (COSMIC's
# cosmic-greeter included). For greetd it also marks the session as graphical in greetd's PAM
# service, which remote desktop servers need. Keeps a *.before-auto-login copy of every file it edits.
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
rewrite() (
    file="$1" content="$2"
    printf '%s\n' "$content" > "$file"
)

backup() (
    file="$1"
    [[ -e "$file" && ! -e "$file.before-auto-login" ]] || return 0
    cp "$file" "$file.before-auto-login"
)

# Name of the unit display-manager.service points to (gdm3, sddm, lightdm, greetd...), or nothing
display_manager() (
    unit="$ROOT/etc/systemd/system/display-manager.service"
    basename "$(readlink "$unit")" .service
)

# The first desktop session installed, Wayland before X11
session_file() (
    for folder in "${SESSION_FOLDERS[@]}"; do
        for file in "$folder"/*.desktop; do
            [[ -f "$file" ]] || continue
            echo "$file"
            return
        done
    done
)

session_name() (
    file="$(session_file)"
    basename "$file" .desktop
)

configure_gdm() (
    file="$ROOT/etc/$1/custom.conf"
    mkdir -p "$(dirname "$file")"
    backup "$file"
    : >> "$file"
    grep -q '^\[daemon\]' "$file" || echo "[daemon]" >> "$file"

    content="$(awk -v state="$STATE" -v user="$USER_NAME" '
        /^[[:space:]]*AutomaticLogin(Enable)?[[:space:]]*=/ { next }
        { print }
        /^\[daemon\]/ && state == "on" { print "AutomaticLoginEnable=true"; print "AutomaticLogin=" user }
    ' "$file")"
    rewrite "$file" "$content"
    echo "    $file"
)

configure_sddm() (
    file="$ROOT/etc/sddm.conf.d/virtual-monitor-autologin.conf"
    rm -f "$file"
    [[ "$STATE" == on ]] || return 0

    mkdir -p "$(dirname "$file")"
    printf '[Autologin]\nUser=%s\nSession=%s\n' "$USER_NAME" "$(session_name)" > "$file"
    echo "    $file"
)

# Some distributions only let members of the autologin group log in automatically
join_autologin_group() {
    grep -q '^autologin:' "$ROOT/etc/group" 2>/dev/null || return 0
    gpasswd -a "$USER_NAME" autologin
}

configure_lightdm() (
    file="$ROOT/etc/lightdm/lightdm.conf.d/60-virtual-monitor-autologin.conf"
    rm -f "$file"
    [[ "$STATE" == on ]] || return 0

    mkdir -p "$(dirname "$file")"
    printf '[Seat:*]\nautologin-user=%s\nautologin-user-timeout=0\n' "$USER_NAME" > "$file"
    session="$(session_name)"
    [[ -z "$session" ]] || echo "autologin-session=$session" >> "$file"
    join_autologin_group
    echo "    $file"
)

greetd_configuration() (
    for file in "$ROOT/etc/greetd/cosmic-greeter.toml" "$ROOT/etc/greetd/config.toml"; do
        [[ -f "$file" ]] || continue
        echo "$file"
        return
    done
)

# The command greetd runs for the automatic session: COSMIC's, else the first session's Exec line
greetd_command() (
    if command -v start-cosmic >/dev/null; then
        echo start-cosmic
        return
    fi

    file="$(session_file)"
    [[ -n "$file" ]] || return 0
    sed -n 's/^Exec=//p' "$file" | head -n 1
)

# x11 when the only session found is an X11 one, else wayland (COSMIC and the Wayland sessions)
session_type() (
    file="$(session_file)"
    [[ "$file" == */xsessions/* ]] || { echo wayland; return; }
    echo x11
)

# A [general] setting of greetd's configuration (FILE KEY DEFAULT): service is the PAM service it
# logs in with, runfile the file that makes it skip [initial_session] when it starts again
greetd_setting() (
    value="$(awk -F '"' -v key="$2" '/^\[/ { general = ($0 ~ /^\[general\]/) } general && $1 ~ "^[[:space:]]*" key "[[:space:]]*=" { print $2; exit }' "$1")"
    echo "${value:-$3}"
)

# greetd starts [initial_session] without saying it is graphical, so logind records it as a tty
# session and remote desktop servers (Jump Desktop Connect, for one) find no graphical session.
# A pam_env line in greetd's PAM service sets XDG_SESSION_TYPE before pam_systemd reads it.
SESSION_TYPE_FILE="/etc/security/virtual-monitor-session.conf"
PAM_LINE="session optional pam_env.so readenv=0 conffile=$SESSION_TYPE_FILE"

configure_session_type() (
    pam="$ROOT/etc/pam.d/$1"
    [[ -f "$pam" ]] || { echo "    no $pam: the session type stays as greetd sets it"; return 0; }
    backup "$pam"

    content="$(awk -v line="$PAM_LINE" -v state="$STATE" '
        index($0, "virtual-monitor-session.conf") { next }
        { lines[++count] = $0 }
        /^session[[:space:]].*pam_env\.so/ { last_pam_env = count }
        /^(session|@include[[:space:]]+common-session)/ && !first_session { first_session = count }
        END {
            insert_at = first_session
            if (last_pam_env) { insert_at = last_pam_env + 1 }

            for (index_line = 1; index_line <= count; index_line++) {
                if (state == "on" && index_line == insert_at) { print line }
                print lines[index_line]
            }

            if (state == "on" && !insert_at) { print line }
        }
    ' "$pam")"
    rewrite "$pam" "$content"
    echo "    $pam"

    rm -f "$ROOT$SESSION_TYPE_FILE"
    [[ "$STATE" == on ]] || return 0
    mkdir -p "$(dirname "$ROOT$SESSION_TYPE_FILE")"
    echo "XDG_SESSION_TYPE OVERRIDE=$(session_type)" > "$ROOT$SESSION_TYPE_FILE"
    echo "    $ROOT$SESSION_TYPE_FILE"
)

configure_greetd() (
    file="$(greetd_configuration)"
    [[ -n "$file" ]] || fail "greetd has no configuration in $ROOT/etc/greetd."
    backup "$file"

    # The [initial_session] table is the automatic login; drop the old one before adding the new
    content="$(awk '/^\[/ { skip = ($0 ~ /^\[initial_session\]/) } !skip' "$file")"
    rewrite "$file" "$content"
    echo "    $file"

    service="$(greetd_setting "$file" service greetd)"
    [[ "$STATE" == on ]] || { configure_session_type "$service"; return 0; }

    command="$(greetd_command)"
    [[ -n "$command" ]] || fail "No desktop session found for greetd to start."
    configure_session_type "$service"
    printf '\n[initial_session]\ncommand = "%s"\nuser = "%s"\n' "$command" "$USER_NAME" >> "$file"
)

# greetd runs [initial_session] once per boot: restarting it opens the session only without the runfile
greetd_reopen() (
    file="$(greetd_configuration)"
    echo "sudo rm -f $(greetd_setting "$file" runfile /run/greetd.run) && $REOPEN"
)

# The command that opens the session again after logging out
REOPEN="sudo systemctl restart display-manager"
MANAGER="$(display_manager)"
echo "==> Automatic login of $USER_NAME: $STATE (${MANAGER:-no display manager})"
case "$MANAGER" in
    gdm3) configure_gdm gdm3 ;;
    gdm) configure_gdm gdm ;;
    sddm) configure_sddm ;;
    lightdm) configure_lightdm ;;
    greetd | cosmic-greeter) configure_greetd; REOPEN="$(greetd_reopen)" ;;
    *) fail "Unknown display manager (${MANAGER:-none}): turn automatic login on in its settings." ;;
esac

echo
echo "Done. It takes effect at the next boot: sudo reboot"
[[ "$STATE" == on ]] || exit 0
echo "Anyone at the machine now gets the desktop without a password; remote access keeps its own."
echo "Logging out ends the session until the next boot; to open it again: $REOPEN"
