#!/usr/bin/env bash
#
# keep-session.sh
# Sometimes GDM 50 opens the login screen after the auto-login has already
# happened, and the user session keeps running on another VT, in the background.
# With no monitor, this leaves Jump Desktop capturing the login screen.
# This script runs as root during the first minutes after boot and, if the login
# screen is active on seat0 while the auto-login user's graphical session
# exists, gives the seat back to that session.
#
# Installed by install-session.sh as a systemd service.
# DRY_RUN=1 only shows what it would do (no root needed).
# WINDOW_SECONDS and INTERVAL change how long it checks and how often.
# ROOT=/folder reads the GDM configuration under /folder (used by the tests).

set -euo pipefail

WINDOW_SECONDS="${WINDOW_SECONDS:-300}"
INTERVAL="${INTERVAL:-2}"
ROOT="${ROOT:-}"

# Prints "id class name type seat active" of each session, separated by tabs
# (the seat is empty in some sessions, and loginctl does not follow the -p order)
list_sessions() {
    local id
    for id in $(loginctl list-sessions --no-legend | awk '{print $1}'); do
        loginctl show-session "$id" -p Class -p Name -p Type -p Seat -p Active | awk -F= -v id="$id" '
            { prop[$1] = substr($0, length($1) + 2) }
            END { printf "%s\t%s\t%s\t%s\t%s\t%s\n", id, prop["Class"], prop["Name"], prop["Type"], prop["Seat"], prop["Active"] }'
    done
}

check() {
    local user_name="$1" sessions active_greeter user_session
    sessions="$(list_sessions)"
    active_greeter="$(awk -F'\t' '$2 == "greeter" && $6 == "yes" {print $1; exit}' <<<"$sessions")"
    user_session="$(awk -F'\t' -v u="$user_name" '$2 == "user" && $3 == u && ($4 == "wayland" || $4 == "x11") && $5 == "seat0" && $6 == "no" {print $1; exit}' <<<"$sessions")"
    [[ -n "$active_greeter" && -n "$user_session" ]] || return 0

    echo "Login screen ($active_greeter) active with session $user_session of $user_name in the background; reactivating the session."
    [[ "${DRY_RUN:-0}" == 1 ]] || loginctl activate "$user_session"
}

user_name="$(sed -n 's/^AutomaticLogin *= *//p' "$ROOT/etc/gdm3/custom.conf" 2>/dev/null | tail -1 || true)"
[[ -n "$user_name" ]] || { echo "Auto-login not configured in GDM; nothing to do."; exit 0; }

for ((i = 0; i < WINDOW_SECONDS / INTERVAL; i++)); do
    check "$user_name"
    sleep "$INTERVAL"
done
