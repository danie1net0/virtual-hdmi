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
    stub loginctl "folder=\"$CASE/sessions\"
case \"\$1\" in
    list-sessions) for file in \"\$folder\"/*; do [[ -e \"\$file\" ]] && echo \"\$(basename \"\$file\") 1000 user seat0 tty2\"; done ;;
    show-session) cat \"\$folder/\$2\" ;;
    activate) [[ -e \"\$folder/../activate-fails\" ]] && exit 1; exit 0 ;;
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
contains "$OUTPUT" "Auto-login not configured" "explains why it does nothing"
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
contains "$OUTPUT" "Login screen (c1) active with session 2 of daniel" "explains what it did"
called "sleep 1"

machine daniel
session c1 greeter gdm wayland seat0 yes
session 3 user daniel x11 seat0 no
DRY_RUN=1 WINDOW_SECONDS=1 INTERVAL=1 run_script "$SCRIPT"
status_is 0 "DRY_RUN exits with 0"
contains "$OUTPUT" "session 3 of daniel" "DRY_RUN shows what it would do"
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

machine daniel
printf '%s\n' '[daemon]' 'AutomaticLogin = old' 'AutomaticLogin = daniel' '#  AutomaticLogin = user1' > "$ROOT/etc/gdm3/custom.conf"
session c1 greeter gdm wayland seat0 yes
session 2 user daniel wayland seat0 no
once
called "loginctl activate 2"
contains "$OUTPUT" "session 2 of daniel" "uses the last AutomaticLogin line, not a commented one"

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
for case_definition in "${cases[@]}"; do
    IFS='|' read -r description first second <<< "$case_definition"
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
printf 'Active=yes\nSeat=seat0\nName=gdm\nType=wayland\nClass=greeter\n' > "$CASE/sessions/c1"
printf 'Name=daniel\nClass=user\nActive=no\nType=wayland\nSeat=seat0\n' > "$CASE/sessions/2"
: > "$CASE/activate-fails"
once
status_is 1 "reads properties out of order and fails if activate fails"
called "loginctl activate 2"

echo "# defaults"
machine daniel
INTERVAL=300 run_script "$SCRIPT"
check "checks for 300 seconds by default: one pass of 300" test "$(grep -c '^sleep 300$' "$CALLS")" = 1

machine daniel
INTERVAL=301 run_script "$SCRIPT"
not_called sleep

machine daniel
stub sed
UNSET_ROOT=1 run_script "$SCRIPT"
status_is 0 "without ROOT, reads the GDM user"
contains "$OUTPUT" "Auto-login not configured in GDM" "without ROOT, works on /"

summary
