#!/usr/bin/env bash
#
# install-edid.sh
# Installs a virtual monitor EDID on a video output, so the machine offers its modes with no
# monitor plugged in: the output looks connected to a monitor with these resolutions.
# Usually run by the app (virtual-monitor --install-edid, or the Install button), which generates
# the EDID and picks a free output.
#
# Puts the EDID in the boot image and the kernel parameters drm.edid_firmware=OUTPUT:... and
# video=OUTPUT:e in the boot setup it finds: Armbian/U-Boot (/boot/armbianEnv.txt), kernelstub
# (Pop!_OS, systemd-boot) or GRUB (Debian, Ubuntu, Fedora...). On NVIDIA it needs the open kernel
# modules (the only ones for RTX 50) with nvidia-drm.modeset=1.
#
# Usage (from the project folder):
#   sudo bash scripts/install-edid.sh [EDID] [OUTPUT]
#     EDID defaults to edid/virtual-monitor.bin (3440x1440, 2560x1080, 3008x1260 and 2360x1640, on
#     clocks every GPU generates); OUTPUT defaults to $CONNECTOR, then HDMI-A-1. The outputs are
#     the names after "cardN-" in /sys/class/drm.
#
# ROOT=/folder writes the files under /folder instead of / (used by the tests).
#
# To undo:
#   GRUB:       sudo cp /etc/default/grub.before-edid /etc/default/grub && sudo update-grub && sudo reboot
#   Armbian:    sudo cp /boot/armbianEnv.txt.before-edid /boot/armbianEnv.txt && sudo reboot
#   kernelstub: sudo kernelstub -d "drm.edid_firmware=OUTPUT:edid/virtual-monitor.bin video=OUTPUT:e" && sudo reboot

set -euo pipefail

[[ "$(id -u)" -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }

DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="${ROOT:-}"
EDID_SRC="${1:-$DIR/../edid/virtual-monitor.bin}"
EDID_REL="edid/virtual-monitor.bin"
EDID_DST="$ROOT/usr/lib/firmware/$EDID_REL"
CONNECTOR="${2:-${CONNECTOR:-HDMI-A-1}}"
[[ "$CONNECTOR" =~ ^[A-Za-z]+(-[A-Za-z]+)?-[0-9]+$ ]] || { echo "Invalid CONNECTOR: $CONNECTOR (like HDMI-A-1 or DP-1)" >&2; exit 1; }
PARAMS="drm.edid_firmware=${CONNECTOR}:${EDID_REL} video=${CONNECTOR}:e"
ARMBIAN_ENV="$ROOT/boot/armbianEnv.txt"
GRUB="$ROOT/etc/default/grub"
KERNELSTUB_CONFIG="$ROOT/etc/kernelstub/configuration"

# sed without -i, which differs between GNU and BSD; rewrites in place to keep owner and permissions
edit() {
    local file="$1" new
    shift
    new="$(sed -E "$@" "$file")"
    printf '%s\n' "$new" > "$file"
}

# Only the running kernel: old kernels whose modules were removed break the generation
build_boot_image() {
    if command -v update-initramfs >/dev/null 2>&1; then
        update-initramfs -u -k "$KVER"
        return
    fi

    if command -v dracut >/dev/null 2>&1; then
        dracut -f --kver "$KVER"
        return
    fi

    echo "Neither update-initramfs nor dracut available to build the boot image." >&2
    exit 1
}

# Whether the listing printed by the command names the EDID. The listing is read whole first: with
# pipefail, "lister | grep -q" fails when grep stops early and the lister dies of SIGPIPE.
image_has_edid() {
    local listing
    listing="$("$@" 2>/dev/null || true)"
    [[ "$listing" == *"$EDID_REL"* ]]
}

check_boot_image() {
    if command -v lsinitrd >/dev/null 2>&1 && image_has_edid lsinitrd --kver "$KVER"; then
        echo "    ok (lsinitrd)"
        return
    fi

    if command -v lsinitramfs >/dev/null 2>&1 && image_has_edid lsinitramfs "$ROOT/boot/initrd.img-$KVER"; then
        echo "    ok (lsinitramfs)"
        return
    fi

    echo "    The EDID was not found in the boot image; stopping before touching the boot setup." >&2
    exit 1
}

add_armbian_params() {
    if ! grep -q '^extraargs=' "$ARMBIAN_ENV"; then
        echo "extraargs=${PARAMS}" >> "$ARMBIAN_ENV"
        return
    fi

    edit "$ARMBIAN_ENV" -e "s#^extraargs=(.*)#extraargs=\1 ${PARAMS}#" -e "s#^extraargs=[[:space:]]+#extraargs=#"
}

set_armbian_params() {
    echo "==> Adjusting the kernel parameters in $ARMBIAN_ENV"
    [[ -f "$ARMBIAN_ENV.before-edid" ]] || cp "$ARMBIAN_ENV" "$ARMBIAN_ENV.before-edid"

    # Remove earlier parameters of this setup and add the new ones
    edit "$ARMBIAN_ENV" -e "/^extraargs=/s#[[:space:]]*video=${CONNECTOR}:[^ ]*##g" \
        -e "/^extraargs=/s#[[:space:]]*drm\.edid_firmware=[^ ]*##g"
    add_armbian_params
    grep '^extraargs=' "$ARMBIAN_ENV"
}

set_grub_params() {
    echo "==> Adjusting the kernel parameters in GRUB"
    [[ -f "$GRUB.before-edid" ]] || cp "$GRUB" "$GRUB.before-edid"

    # Remove earlier parameters of this setup and add the new ones
    edit "$GRUB" -e "s#[[:space:]]*video=${CONNECTOR}:[^\" ]*##g" -e "s#[[:space:]]*drm\.edid_firmware=[^\" ]*##g" \
        -e "s#^(GRUB_CMDLINE_LINUX_DEFAULT=\"[^\"]*)\"#\1 ${PARAMS}\"#" -e "s#^(GRUB_CMDLINE_LINUX_DEFAULT=\")[[:space:]]+#\1#"
    grep GRUB_CMDLINE_LINUX_DEFAULT "$GRUB"
    update-grub
}

# Parameters of an earlier run, as kernelstub keeps them in its JSON configuration
old_kernelstub_params() {
    grep -oE "\"(drm\.edid_firmware=[^\"]*|video=${CONNECTOR}:[^\"]*)\"" "$KERNELSTUB_CONFIG" | tr -d '"' | sort -u | tr '\n' ' ' || true
}

set_kernelstub_params() {
    local old
    echo "==> Adjusting the kernel parameters with kernelstub"
    [[ -f "$KERNELSTUB_CONFIG.before-edid" ]] || cp "$KERNELSTUB_CONFIG" "$KERNELSTUB_CONFIG.before-edid"

    # Remove earlier parameters of this setup and add the new ones
    old="$(old_kernelstub_params)"
    [[ -z "$old" ]] || kernelstub -d "${old% }"
    kernelstub -a "$PARAMS"
}

uses_kernelstub() {
    [[ -f "$KERNELSTUB_CONFIG" ]] && command -v kernelstub >/dev/null 2>&1
}

set_kernel_params() {
    if [[ -f "$ARMBIAN_ENV" ]]; then
        set_armbian_params
        return
    fi

    if uses_kernelstub; then
        set_kernelstub_params
        return
    fi

    if [[ -f "$GRUB" ]]; then
        set_grub_params
        return
    fi

    echo "Neither $ARMBIAN_ENV, kernelstub nor $GRUB found: I do not know where to put the kernel parameters." >&2
    echo "Add to the kernel command line: $PARAMS" >&2
    exit 1
}

[[ -f "$EDID_SRC" ]] || { echo "$EDID_SRC not found" >&2; exit 1; }
[[ "$(wc -c < "$EDID_SRC" | tr -d ' ')" -eq 256 ]] || { echo "$EDID_SRC is not 256 bytes; it does not look like an EDID." >&2; exit 1; }

echo "==> Copying the EDID to $EDID_DST"
mkdir -p "$(dirname "$EDID_DST")"
install -m 644 "$EDID_SRC" "$EDID_DST"

KVER="$(uname -r)"
echo "==> Adding the EDID to the boot image (kernel $KVER)"
# The boot image hooks of earlier versions, which used edid/ultrawide.bin
rm -f "$ROOT/etc/dracut.conf.d/90-edid-ultrawide.conf" "$ROOT/etc/initramfs-tools/hooks/edid-ultrawide"
# The hook goes wherever the tool that builds the image reads it; the folder may not exist yet
if command -v dracut >/dev/null 2>&1; then
    mkdir -p "$ROOT/etc/dracut.conf.d"
    echo "install_items+=\" /usr/lib/firmware/$EDID_REL \"" > "$ROOT/etc/dracut.conf.d/90-edid-virtual-monitor.conf"
fi

if command -v update-initramfs >/dev/null 2>&1; then
    mkdir -p "$ROOT/etc/initramfs-tools/hooks"
    cat > "$ROOT/etc/initramfs-tools/hooks/edid-virtual-monitor" <<'EOF'
#!/bin/sh
PREREQ=""
prereqs() { echo "$PREREQ"; }
case "$1" in prereqs) prereqs; exit 0 ;; esac
mkdir -p "${DESTDIR}/usr/lib/firmware/edid"
cp /usr/lib/firmware/edid/virtual-monitor.bin "${DESTDIR}/usr/lib/firmware/edid/"
EOF
    chmod 755 "$ROOT/etc/initramfs-tools/hooks/edid-virtual-monitor"
fi

build_boot_image

echo "==> Checking that the EDID is in the image"
check_boot_image

set_kernel_params

echo
echo "Done: $CONNECTOR gets the virtual monitor at the next boot. Reboot with: sudo reboot"
echo "Then: virtual-monitor --list"
