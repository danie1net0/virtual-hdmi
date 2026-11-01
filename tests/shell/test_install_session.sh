#!/usr/bin/env bash
# Tests scripts/install-session.sh with the system root in a temporary folder.
source "$(dirname "$0")/lib.sh"

SCRIPT="$PROJECT/scripts/install-session.sh"
SERVICE="etc/systemd/system/keep-session.service"

new_case
stub systemctl
FAKE_UID=1000 run_script "$SCRIPT"
status_is 1 "fails without root"
contains "$ERRS" "Run with sudo." "asks for sudo"
not_called systemctl

new_case
stub systemctl
run_script "$SCRIPT"
status_is 0 "installs the service"
check "copies keep-session.sh" cmp "$PROJECT/scripts/keep-session.sh" "$ROOT/usr/local/sbin/keep-session.sh"
check "installed script is executable" test -x "$ROOT/usr/local/sbin/keep-session.sh"
check "service points to the real path, without the test root" grep -qx "ExecStart=/usr/local/sbin/keep-session.sh" "$ROOT/$SERVICE"
check "service starts after GDM" grep -qx "After=gdm.service" "$ROOT/$SERVICE"
check "service joins graphical.target" grep -qx "WantedBy=graphical.target" "$ROOT/$SERVICE"
called "systemctl daemon-reload"
called "systemctl enable keep-session.service"
check "reloads before enabling" test "$(grep '^systemctl' "$CALLS" | head -1)" = "systemctl daemon-reload"
contains "$OUT" "journalctl -u keep-session" "shows where to see the log"

run_script "$SCRIPT"
status_is 0 "reinstalls over the previous one"

new_case
stub systemctl 'exit 1'
run_script "$SCRIPT"
status_is 1 "systemctl failure stops the install"
not_contains "$OUT" "Done" "does not say it finished"

summary
