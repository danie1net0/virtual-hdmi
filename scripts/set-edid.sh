#!/usr/bin/env bash
#
# set-edid.sh
# Gives the virtual monitor a new EDID right away, with no reboot, so the desktop offers a
# resolution the installed EDID lacks: the screen of whatever client connects. Usually run by the
# app (virtual-monitor --size, or the Other size row), which generates the EDID with the size asked
# for and the default modes.
#
# Writes the EDID to the kernel's override for the output (debugfs:
# /sys/kernel/debug/dri/N/OUTPUT/edid_override), then disconnects and reconnects the output
# (/sys/class/drm/cardN-OUTPUT/status), so the desktop reads its modes again. The override lasts
# until the next boot, so the script keeps a copy in /var/lib/virtual-monitor and, with systemd,
# the virtual-monitor-edid service sets it again at every boot, before the login screen.
#
# Needs the output set up by install-edid.sh, whose video=OUTPUT:e keeps it connected, and a
# driver with the override. Kernel lockdown (Secure Boot on some distributions) hides debugfs,
# and NVIDIA's own modules have no override: there, install the modes with install-edid.sh
# (virtual-monitor --install-edid --modes '...') and reboot.
#
# Usage (from the project folder):
#   sudo bash scripts/set-edid.sh EDID OUTPUT   sets EDID on OUTPUT now and at every boot
#   sudo bash scripts/set-edid.sh --boot        sets the kept EDID again (the service runs it)
#   sudo bash scripts/set-edid.sh --reset       goes back to the installed EDID
# OUTPUT is the name after "cardN-" in /sys/class/drm, like HDMI-A-1.
#
# ROOT=/folder works under /folder instead of / (used by the tests).

set -euo pipefail

[[ "$(id -u)" -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }

ROOT="${ROOT:-}"
KEPT_FOLDER="$ROOT/var/lib/virtual-monitor"
KEPT_EDID="$KEPT_FOLDER/edid.bin"
KEPT_OUTPUT="$KEPT_FOLDER/output"
# Where the service finds the script at boot; SCRIPT_COPY is the same file under ROOT
SCRIPT_COPY_PATH="/usr/local/lib/virtual-monitor/set-edid.sh"
SCRIPT_COPY="$ROOT$SCRIPT_COPY_PATH"
SERVICE_NAME="virtual-monitor-edid.service"
SERVICE="$ROOT/etc/systemd/system/$SERVICE_NAME"
# At boot the video driver may still be loading
BOOT_WAIT_SECONDS=30
# Long enough for the desktop to see the output gone before it comes back
DISCONNECTED_SECONDS=2
NO_OUTPUT="the outputs are the names after cardN- in /sys/class/drm"
NO_OVERRIDE="its driver has no EDID override (debugfs hidden by kernel lockdown, or NVIDIA's own modules). Install the modes instead and reboot: virtual-monitor --install-edid --modes '...'"

fail() {
    echo "$1" >&2
    exit 1
}

check_output_name() {
    [[ "$OUTPUT" =~ ^[A-Za-z]+(-[A-Za-z]+)?-[0-9]+$ ]] || fail "Invalid OUTPUT: $OUTPUT (like HDMI-A-1 or DP-1)"
}

check_edid() {
    [[ -f "$1" ]] || fail "$1 not found"
    [[ "$(wc -c < "$1" | tr -d ' ')" -eq 256 ]] || fail "$1 is not 256 bytes; it does not look like an EDID."
}

# The cardN-OUTPUT folder of the output; nothing, and a failure, when the machine has no such output
output_folder() (
    for folder in "$ROOT"/sys/class/drm/card[0-9]*-"$OUTPUT"; do
        [[ -e "$folder/status" ]] && echo "$folder" && return
    done
)

# The EDID override of the output in the folder $1: debugfs numbers the GPUs like the cardN folders
override_path() (
    name="${1##*/}"
    card="${name#card}"
    echo "$ROOT/sys/kernel/debug/dri/${card%%-*}/$OUTPUT/edid_override"
)

# Sets OUTPUT_FOLDER, STATUS_FILE and OVERRIDE for OUTPUT; fails when the machine has no such output
locate_output() {
    OUTPUT_FOLDER="$(output_folder)"
    [[ -n "$OUTPUT_FOLDER" ]] || return

    STATUS_FILE="$OUTPUT_FOLDER/status"
    OVERRIDE="$(override_path "$OUTPUT_FOLDER")"
}

has_override() {
    locate_output && [[ -e "$OVERRIDE" ]]
}

# Waits until the output and its override exist; the caller then runs locate_output itself
wait_for_output() (
    for ((attempt = 0; attempt < BOOT_WAIT_SECONDS; attempt++)); do
        has_override && return
        sleep 1
    done

    has_override
)

# The desktop reads the modes again only when the output comes back: a hotplug event alone does not
# make every desktop look again. "on" is what video=OUTPUT:e set at boot.
reconnect() {
    echo off > "$STATUS_FILE"
    sleep "$DISCONNECTED_SECONDS"
    echo on > "$STATUS_FILE"
}

write_service() {
    mkdir -p "$(dirname "$SERVICE")"
    cat > "$SERVICE" <<EOF
[Unit]
Description=Virtual monitor EDID chosen in the app
After=systemd-modules-load.service sys-kernel-debug.mount
Before=display-manager.service

[Service]
Type=oneshot
ExecStart=/usr/bin/env bash $SCRIPT_COPY_PATH --boot

[Install]
WantedBy=graphical.target
EOF
}

# The copy that the service runs belongs to root: a script in the user's folder could be changed
# to run anything as root at boot
install_service() {
    mkdir -p "$(dirname "$SCRIPT_COPY")"
    install -m 755 "$0" "$SCRIPT_COPY"
    write_service
    systemctl daemon-reload
    systemctl enable --quiet "$SERVICE_NAME"
}

# Keeps the EDID for --boot and --reset; with systemd, a service sets it again at every boot
keep() {
    mkdir -p "$KEPT_FOLDER"
    install -m 644 "$EDID_SOURCE" "$KEPT_EDID"
    echo "$OUTPUT" > "$KEPT_OUTPUT"

    if ! command -v systemctl >/dev/null; then
        echo "Done: $OUTPUT has the new modes until the next boot; without systemd, nothing sets them again at boot."
        return
    fi

    install_service
    echo "Done: $OUTPUT has the new modes now and at every boot. To go back to the installed EDID: sudo bash $SCRIPT_COPY_PATH --reset"
}

forget() {
    if command -v systemctl >/dev/null; then
        systemctl disable --quiet "$SERVICE_NAME"
    fi

    rm -f "$SERVICE" "$KEPT_EDID" "$KEPT_OUTPUT" "$SCRIPT_COPY"
}

set_now() {
    EDID_SOURCE="$1"
    OUTPUT="$2"
    check_edid "$EDID_SOURCE"
    check_output_name
    locate_output || fail "No output $OUTPUT: $NO_OUTPUT"
    [[ -e "$OVERRIDE" ]] || fail "No EDID override for $OUTPUT: $NO_OVERRIDE"

    echo "==> Setting the EDID of $OUTPUT"
    cat "$EDID_SOURCE" > "$OVERRIDE"
    reconnect
    keep
}

set_at_boot() {
    [[ -e "$KEPT_OUTPUT" ]] || { echo "No EDID kept: nothing to set."; return; }

    OUTPUT="$(cat "$KEPT_OUTPUT")"
    EDID_SOURCE="$KEPT_EDID"
    check_output_name
    check_edid "$EDID_SOURCE"
    wait_for_output || fail "No EDID override for $OUTPUT after $BOOT_WAIT_SECONDS s: $NO_OVERRIDE"
    locate_output

    cat "$EDID_SOURCE" > "$OVERRIDE"
    reconnect
    echo "$OUTPUT has the kept EDID."
}

reset() {
    [[ -e "$KEPT_OUTPUT" ]] || { echo "No EDID kept: the installed one is in use."; return; }

    OUTPUT="$(cat "$KEPT_OUTPUT")"
    check_output_name
    forget
    has_override || { echo "The kept EDID is gone; the installed one comes back at the next boot."; return; }

    echo reset > "$OVERRIDE"
    reconnect
    echo "$OUTPUT is back to the installed EDID."
}

USAGE="Usage: set-edid.sh EDID OUTPUT | --boot | --reset"

case "${1:-}" in
    --boot) set_at_boot ;;
    --reset) reset ;;
    "" | -*) fail "$USAGE" ;;
    *)
        [[ $# -eq 2 ]] || fail "$USAGE"
        set_now "$1" "$2"
        ;;
esac
