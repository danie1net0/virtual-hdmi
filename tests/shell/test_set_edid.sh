#!/usr/bin/env bash
# Tests scripts/set-edid.sh with the system root in a temporary folder.
source "$(dirname "$0")/lib.sh"

SCRIPT="$PROJECT/scripts/set-edid.sh"
EDID="$PROJECT/edid/virtual-monitor.bin"
SERVICE_NAME="virtual-monitor-edid.service"

# The second GPU has the virtual monitor on HDMI-A-1. As decoys, the first GPU has an override for
# HDMI-A-1 and a card0-HDMI-A-1 folder with no status, and card1-HDMI-A-10 is another output.
machine() {
    new_case
    STATUS_FILE="$ROOT/sys/class/drm/card1-HDMI-A-1/status"
    OVERRIDE="$ROOT/sys/kernel/debug/dri/1/HDMI-A-1/edid_override"
    DECOY="$ROOT/sys/kernel/debug/dri/0/HDMI-A-1/edid_override"
    mkdir -p "$(dirname "$STATUS_FILE")" "$(dirname "$OVERRIDE")" "$(dirname "$DECOY")" "$ROOT/sys/class/drm/card1-HDMI-A-10" \
        "$ROOT/sys/class/drm/card0-HDMI-A-1"
    echo connected > "$STATUS_FILE"
    echo connected > "$ROOT/sys/class/drm/card1-HDMI-A-10/status"
    : > "$OVERRIDE"
    : > "$DECOY"
    # sleep records the status the desktop sees while it waits
    stub sleep "echo \"status: \$(cat '$STATUS_FILE')\" >> '$CALLS'"
    stub systemctl
}

# What --boot or --reset finds: the EDID and the output kept by an earlier run
kept() {
    mkdir -p "$ROOT/var/lib/virtual-monitor"
    cp "$EDID" "$ROOT/var/lib/virtual-monitor/edid.bin"
    echo "$1" > "$ROOT/var/lib/virtual-monitor/output"
}

# A service and a script copy, as an earlier run left them
installed_service() {
    mkdir -p "$ROOT/etc/systemd/system" "$ROOT/usr/local/lib/virtual-monitor"
    : > "$ROOT/etc/systemd/system/$SERVICE_NAME"
    : > "$ROOT/usr/local/lib/virtual-monitor/set-edid.sh"
}

echo "# permissions and input"
machine
FAKE_UID=1000 run_script "$SCRIPT" "$EDID" HDMI-A-1
status_is 1 "fails without root"
contains "$ERRORS" "Run with sudo." "asks for sudo"
check "writes nothing without root" test ! -s "$OVERRIDE"

for arguments in "" "-x" "$EDID" "$EDID HDMI-A-1 extra"; do
    machine
    # shellcheck disable=SC2086
    run_script "$SCRIPT" $arguments
    status_is 1 "usage for: ${arguments:-no arguments}"
    contains "$ERRORS" "Usage: set-edid.sh EDID OUTPUT | --boot | --reset" "shows the usage for: ${arguments:-no arguments}"
done

# Without ROOT, as on a real machine; the usage stops it before it reads or writes anything
machine
UNSET_ROOT=1 run_script "$SCRIPT"
status_is 1 "runs without ROOT"
contains "$ERRORS" "Usage: set-edid.sh" "without ROOT, gets to the usage"
not_contains "$ERRORS" "unbound" "without ROOT, uses no unset variable"

machine
run_script "$SCRIPT" "$CASE/missing.bin" HDMI-A-1
status_is 1 "a missing EDID fails"
contains "$ERRORS" "missing.bin not found" "says which file is missing"

machine
mkdir -p "$CASE/folder.bin"
run_script "$SCRIPT" "$CASE/folder.bin" HDMI-A-1
status_is 1 "a folder is no EDID"
contains "$ERRORS" "folder.bin not found" "says the folder is not the EDID"

machine
printf 'short' > "$CASE/short.bin"
run_script "$SCRIPT" "$CASE/short.bin" HDMI-A-1
status_is 1 "a file that is not 256 bytes fails"
contains "$ERRORS" "is not 256 bytes" "explains the size"
check "does not write an invalid file" test ! -s "$OVERRIDE"

for output in "HDMI_A_1" "HDMI-A-1;reboot" "1HDMI-1" "HDMI-A-B-1" "HDMI-A"; do
    machine
    run_script "$SCRIPT" "$EDID" "$output"
    status_is 1 "rejects the output name $output"
    contains "$ERRORS" "Invalid OUTPUT: $output (like HDMI-A-1 or DP-1)" "explains the output name $output"
done

echo "# the output and its override"
machine
run_script "$SCRIPT" "$EDID" DP-1
status_is 1 "an output the machine does not have fails"
contains "$ERRORS" "No EDID override for DP-1: its driver has no EDID override (debugfs hidden by kernel lockdown, or NVIDIA's own modules). Install the modes instead and reboot: virtual-monitor --install-edid --modes '...'" "explains what to do instead"
not_called systemctl

machine
mkdir -p "$ROOT/sys/class/drm/card2-DP-1"
run_script "$SCRIPT" "$EDID" DP-1
status_is 1 "a folder with no status is no output"

machine
rm "$OVERRIDE"
run_script "$SCRIPT" "$EDID" HDMI-A-1
status_is 1 "an output with no override fails"
contains "$ERRORS" "No EDID override for HDMI-A-1:" "says the override is missing"
check "does not touch the other GPU's override" test ! -s "$DECOY"
check "leaves the output connected" test "$(cat "$STATUS_FILE")" = connected

echo "# setting an EDID"
# The override takes no file: the script stops there
machine
rm "$OVERRIDE"
mkdir "$OVERRIDE"
run_script "$SCRIPT" "$EDID" HDMI-A-1
status_is 1 "stops when the override does not take the EDID"
check "keeps nothing when the override does not take the EDID" test ! -e "$ROOT/var/lib/virtual-monitor"
check "leaves the output connected when the override does not take the EDID" test "$(cat "$STATUS_FILE")" = connected

machine
run_script "$SCRIPT" "$EDID" HDMI-A-1
status_is 0 "sets the EDID"
check "writes the EDID to the override of the output's GPU" cmp "$EDID" "$OVERRIDE"
check "leaves the other GPU alone" test ! -s "$DECOY"
check "disconnects the output while it waits" test "$(grep '^status: ' "$CALLS")" = "status: off"
called "sleep 2"
check "waits only once" test "$(grep -c '^sleep' "$CALLS")" = 1
check "connects the output again" test "$(cat "$STATUS_FILE")" = on
check "keeps the EDID" cmp "$EDID" "$ROOT/var/lib/virtual-monitor/edid.bin"
check "keeps the output" test "$(cat "$ROOT/var/lib/virtual-monitor/output")" = HDMI-A-1
check "the root copy of the script is this script" cmp "$SCRIPT" "$ROOT/usr/local/lib/virtual-monitor/set-edid.sh"
check "the root copy is executable" test -x "$ROOT/usr/local/lib/virtual-monitor/set-edid.sh"
check "the service is exactly the expected unit" test "$(cat "$ROOT/etc/systemd/system/$SERVICE_NAME")" = "$(printf '%s\n' \
    '[Unit]' \
    'Description=Virtual monitor EDID chosen in the app' \
    'After=systemd-modules-load.service sys-kernel-debug.mount' \
    'Before=display-manager.service' \
    '' \
    '[Service]' \
    'Type=oneshot' \
    'ExecStart=/usr/bin/env bash /usr/local/lib/virtual-monitor/set-edid.sh --boot' \
    '' \
    '[Install]' \
    'WantedBy=graphical.target')"
called "systemctl daemon-reload"
called "systemctl enable --quiet $SERVICE_NAME"
contains "$OUTPUT" "==> Setting the EDID of HDMI-A-1" "says what it sets"
contains "$OUTPUT" "Done: HDMI-A-1 has the new modes now and at every boot. To go back to the installed EDID: sudo bash /usr/local/lib/virtual-monitor/set-edid.sh --reset" "says how to go back"

machine
kept DP-9
printf 'old' > "$ROOT/var/lib/virtual-monitor/edid.bin"
installed_service
run_script "$SCRIPT" "$EDID" HDMI-A-1
status_is 0 "sets an EDID over an earlier one"
check "replaces the kept EDID" cmp "$EDID" "$ROOT/var/lib/virtual-monitor/edid.bin"
check "replaces the kept output" test "$(cat "$ROOT/var/lib/virtual-monitor/output")" = HDMI-A-1
check "replaces the root copy" cmp "$SCRIPT" "$ROOT/usr/local/lib/virtual-monitor/set-edid.sh"
contains "$ROOT/etc/systemd/system/$SERVICE_NAME" "ExecStart=" "writes the service again"

machine
rm "$STUBS/systemctl"
run_script "$SCRIPT" "$EDID" HDMI-A-1
status_is 0 "sets the EDID without systemd"
check "writes the EDID without systemd" cmp "$EDID" "$OVERRIDE"
contains "$OUTPUT" "Done: HDMI-A-1 has the new modes until the next boot; without systemd, nothing sets them again at boot." "says it lasts until the next boot"
not_contains "$OUTPUT" "every boot" "does not promise every boot without systemd"
check "keeps the EDID for a later --boot" cmp "$EDID" "$ROOT/var/lib/virtual-monitor/edid.bin"

echo "# at boot"
machine
run_script "$SCRIPT" --boot
status_is 0 "with nothing kept, --boot succeeds"
contains "$OUTPUT" "No EDID kept: nothing to set." "says there is nothing to set"
check "with nothing kept, leaves the override alone" test ! -s "$OVERRIDE"
not_called sleep

machine
kept HDMI-A-1
run_script "$SCRIPT" --boot
status_is 0 "sets the kept EDID at boot"
check "writes the kept EDID" cmp "$EDID" "$OVERRIDE"
check "disconnects the output at boot while it waits" test "$(grep '^status: ' "$CALLS")" = "status: off"
called "sleep 2"
check "connects the output again at boot" test "$(cat "$STATUS_FILE")" = on
contains "$OUTPUT" "HDMI-A-1 has the kept EDID." "says it set the kept EDID"
not_called systemctl

machine
kept "HDMI-A-1;reboot"
run_script "$SCRIPT" --boot
status_is 1 "rejects a broken kept output"
contains "$ERRORS" "Invalid OUTPUT: HDMI-A-1;reboot" "explains the broken kept output"

machine
kept HDMI-A-1
printf 'short' > "$ROOT/var/lib/virtual-monitor/edid.bin"
run_script "$SCRIPT" --boot
status_is 1 "rejects a broken kept EDID"
contains "$ERRORS" "is not 256 bytes" "explains the broken kept EDID"
check "does not write a broken kept EDID" test ! -s "$OVERRIDE"

machine
kept DP-1
run_script "$SCRIPT" --boot
status_is 1 "fails when the output never shows up"
contains "$ERRORS" "No EDID override for DP-1 after 30 s:" "says how long it waited"
check "checks once a second for 30 s" test "$(grep -c '^sleep 1$' "$CALLS")" = 29

# The driver loads while the script waits: the output shows up at the third check
machine
kept HDMI-A-1
mv "$ROOT/sys/class/drm/card1-HDMI-A-1" "$CASE/later"
stub sleep "echo \"sleep \$*\" > /dev/null; count=\$(grep -c '^sleep 1' '$CALLS'); [[ \$count -lt 2 ]] || mv '$CASE/later' '$ROOT/sys/class/drm/card1-HDMI-A-1' 2> /dev/null; true"
run_script "$SCRIPT" --boot
status_is 0 "waits for the driver at boot"
check "stops waiting once the output is there" test "$(grep -c '^sleep 1$' "$CALLS")" = 2
check "writes the kept EDID once the output is there" cmp "$EDID" "$OVERRIDE"

echo "# going back"
machine
run_script "$SCRIPT" --reset
status_is 0 "with nothing kept, --reset succeeds"
contains "$OUTPUT" "No EDID kept: the installed one is in use." "says the installed EDID is in use"
not_called systemctl
check "with nothing kept, leaves the override alone" test ! -s "$OVERRIDE"

machine
kept HDMI-A-1
installed_service
cp "$EDID" "$OVERRIDE"
run_script "$SCRIPT" --reset
status_is 0 "goes back to the installed EDID"
check "drops the override" test "$(cat "$OVERRIDE")" = reset
check "disconnects the output while it waits on reset" test "$(grep '^status: ' "$CALLS")" = "status: off"
check "connects the output again on reset" test "$(cat "$STATUS_FILE")" = on
called "systemctl disable --quiet $SERVICE_NAME"
for file in var/lib/virtual-monitor/edid.bin var/lib/virtual-monitor/output "etc/systemd/system/$SERVICE_NAME" usr/local/lib/virtual-monitor/set-edid.sh; do
    check "removes $file" test ! -e "$ROOT/$file"
done
contains "$OUTPUT" "HDMI-A-1 is back to the installed EDID." "says it went back"

machine
kept DP-1
installed_service
run_script "$SCRIPT" --reset
status_is 0 "goes back when the output is gone"
check "removes the kept EDID when the output is gone" test ! -e "$ROOT/var/lib/virtual-monitor/edid.bin"
check "removes the service when the output is gone" test ! -e "$ROOT/etc/systemd/system/$SERVICE_NAME"
contains "$OUTPUT" "The kept EDID is gone; the installed one comes back at the next boot." "says when the installed EDID comes back"
not_called sleep

machine
kept HDMI-A-1
rm "$STUBS/systemctl"
run_script "$SCRIPT" --reset
status_is 0 "goes back without systemd"
check "removes the kept output without systemd" test ! -e "$ROOT/var/lib/virtual-monitor/output"

machine
kept "HDMI-A-1;reboot"
installed_service
run_script "$SCRIPT" --reset
status_is 1 "rejects a broken kept output on reset"
check "keeps the files of a broken kept output" test -e "$ROOT/var/lib/virtual-monitor/edid.bin"
not_called systemctl

summary
