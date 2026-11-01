#!/usr/bin/env bash
# Tests scripts/keep-session.sh with loginctl simulated.
source "$(dirname "$0")/lib.sh"

SCRIPT="$PROJECT/scripts/keep-session.sh"

# Each session becomes a file "id" with the loginctl show-session properties
session() {
    local id="$1" class="$2" name="$3" type="$4" seat="$5" active="$6"
    printf 'Class=%s\nName=%s\nType=%s\nSeat=%s\nActive=%s\n' "$class" "$name" "$type" "$seat" "$active" > "$CASE/sessions/$id"
}

machine() {
    new_case
    mkdir -p "$ROOT/etc/gdm3" "$CASE/sessions"
    printf '[daemon]\nAutomaticLoginEnable=True\nAutomaticLogin=%s\n' "${1-daniel}" > "$ROOT/etc/gdm3/custom.conf"
    stub loginctl "d=\"$CASE/sessions\"
case \"\$1\" in
    list-sessions) for f in \"\$d\"/*; do [[ -e \"\$f\" ]] && echo \"\$(basename \"\$f\") 1000 user seat0 tty2\"; done ;;
    show-session) cat \"\$d/\$2\" ;;
esac"
    stub sleep
}

# Runs a single pass (window = interval)
once() {
    WINDOW_SECONDS=1 INTERVAL=1 run_script "$SCRIPT"
}

echo "# no auto-login"
new_case
stub loginctl
run_script "$SCRIPT"
status_is 0 "no GDM exits with 0"
contains "$OUT" "Auto-login not configured" "explains why it does nothing"
not_called loginctl

machine ""
once
status_is 0 "empty AutomaticLogin exits with 0"
not_called loginctl

echo "# login screen on top of the session"
machine daniel
session c1 greeter gdm wayland seat0 yes
session 2 user daniel wayland seat0 no
once
status_is 0 "reactivates the session"
called "loginctl activate 2"
contains "$OUT" "Login screen (c1) active with session 2 of daniel" "explains what it did"
called "sleep 1"

machine daniel
session c1 greeter gdm wayland seat0 yes
session 3 user daniel x11 seat0 no
DRY_RUN=1 WINDOW_SECONDS=1 INTERVAL=1 run_script "$SCRIPT"
status_is 0 "DRY_RUN exits with 0"
contains "$OUT" "session 3 of daniel" "DRY_RUN shows what it would do"
not_called "loginctl activate"

machine daniel
session c1 greeter gdm wayland seat0 yes
session 5 user daniel x11 seat0 no
WINDOW_SECONDS=6 INTERVAL=2 run_script "$SCRIPT"
check "checks WINDOW_SECONDS/INTERVAL times" test "$(grep -c '^loginctl activate 5$' "$CALLS")" = 3
check "sleeps INTERVAL between checks" test "$(grep -c '^sleep 2$' "$CALLS")" = 3

machine daniel
session c1 greeter gdm wayland seat0 yes
session 2 user daniel wayland seat0 no
WINDOW_SECONDS=0 run_script "$SCRIPT"
status_is 0 "zero window checks nothing"
not_called loginctl

echo "# nothing to do"
cases=(
    "inactive greeter|c1 greeter gdm wayland seat0 no|2 user daniel wayland seat0 no"
    "session already active|c1 greeter gdm wayland seat0 yes|2 user daniel wayland seat0 yes"
    "session of another user|c1 greeter gdm wayland seat0 yes|2 user maria wayland seat0 no"
    "terminal session|c1 greeter gdm wayland seat0 yes|2 user daniel tty seat0 no"
    "session without seat|c1 greeter gdm wayland seat0 yes|2 user daniel wayland - no"
    "session on another seat|c1 greeter gdm wayland seat0 yes|2 user daniel wayland seat1 no"
    "only the login screen|c1 greeter gdm wayland seat0 yes"
    "no sessions|"
)
for case_def in "${cases[@]}"; do
    IFS='|' read -r description first second <<< "$case_def"
    machine daniel
    for definition in "$first" "${second:-}"; do
        [[ -n "$definition" ]] || continue
        read -r id class name type seat active <<< "$definition"
        [[ "$seat" != - ]] || seat=""
        session "$id" "$class" "$name" "$type" "$seat" "$active"
    done
    once
    status_is 0 "$description: exits with 0"
    not_called "loginctl activate"
done

machine daniel
session c1 greeter gdm wayland seat0 yes
session 2 user daniel wayland seat0 no
stub loginctl 'case "$1" in list-sessions) echo "c1 120 gdm seat0 tty1"; echo "2 1000 daniel seat0 tty2" ;; show-session) [[ "$2" == c1 ]] && printf "Active=yes\nSeat=seat0\nName=gdm\nType=wayland\nClass=greeter\n" || printf "Name=daniel\nClass=user\nActive=no\nType=wayland\nSeat=seat0\n" ;; activate) exit 1 ;; esac'
once
status_is 1 "reads properties out of order and fails if activate fails"
called "loginctl activate 2"

summary
