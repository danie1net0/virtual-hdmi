#!/usr/bin/env bash
#
# install-edid.sh
# Installs a virtual monitor EDID on a video output, so the machine offers its modes with no
# monitor plugged in: the output looks connected to a monitor with these resolutions.
# Usually run by the app (virtual-monitor --install-edid, or the Install button), which generates
# the EDID and picks a free output.
#
# Puts the EDID in the boot image (initramfs-tools, dracut or mkinitcpio) and the kernel
# parameters drm.edid_firmware=OUTPUT:... and video=OUTPUT:e in the boot setup it finds:
#   Armbian             /boot/armbianEnv.txt
#   Raspberry Pi        /boot/firmware/cmdline.txt (Raspberry Pi OS, Ubuntu), or /boot/cmdline.txt
#   kernelstub          Pop!_OS (systemd-boot)
#   GRUB                /etc/default/grub.d/99-virtual-monitor.cfg with update-grub (Debian, Ubuntu),
#                       else /etc/default/grub with grubby (Fedora), grub2-mkconfig (openSUSE) or
#                       grub-mkconfig (Arch)
#   U-Boot              /etc/default/u-boot with u-boot-update, else /boot/extlinux/extlinux.conf
#   systemd-boot        the loader entries in /boot, /efi or /boot/efi, and /etc/kernel/cmdline
# With no boot image tool, it only copies the EDID: the kernel then reads it from /usr/lib/firmware.
# On NVIDIA it needs the open kernel modules (the only ones for RTX 50) with nvidia-drm.modeset=1.
#
# Usage (from the project folder):
#   sudo bash scripts/install-edid.sh [EDID] [OUTPUT]
#     EDID defaults to edid/virtual-monitor.bin (3440x1440, 2560x1080, 3008x1260 and 2360x1640, on
#     clocks every GPU generates); OUTPUT defaults to $CONNECTOR, then HDMI-A-1. The outputs are
#     the names after "cardN-" in /sys/class/drm.
#
# ROOT=/folder writes the files under /folder instead of / (used by the tests).
#
# To undo, copy back each *.before-edid file it kept, then apply it and reboot:
#   GRUB:       Debian, Ubuntu: sudo rm /etc/default/grub.d/99-virtual-monitor.cfg && sudo update-grub
#               Fedora: sudo grubby --update-kernel=ALL --remove-args="drm.edid_firmware video=OUTPUT:e"
#               openSUSE, Arch: sudo cp /etc/default/grub.before-edid /etc/default/grub, then
#               grub2-mkconfig -o /boot/grub2/grub.cfg or grub-mkconfig -o /boot/grub/grub.cfg
#   U-Boot:     sudo cp /etc/default/u-boot.before-edid /etc/default/u-boot && sudo u-boot-update
#   kernelstub: sudo kernelstub -d "drm.edid_firmware=OUTPUT:edid/virtual-monitor.bin video=OUTPUT:e"
#   the others: sudo cp FILE.before-edid FILE (armbianEnv.txt, cmdline.txt, extlinux.conf, the
#               systemd-boot entries and /etc/kernel/cmdline)

set -euo pipefail

[[ "$(id -u)" -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }

SCRIPT_FOLDER="$(cd "$(dirname "$0")" && pwd)"
ROOT="${ROOT:-}"
EDID_SOURCE="${1:-$SCRIPT_FOLDER/../edid/virtual-monitor.bin}"
EDID_RELATIVE="edid/virtual-monitor.bin"
EDID_TARGET="$ROOT/usr/lib/firmware/$EDID_RELATIVE"
CONNECTOR="${2:-${CONNECTOR:-HDMI-A-1}}"
[[ "$CONNECTOR" =~ ^[A-Za-z]+(-[A-Za-z]+)?-[0-9]+$ ]] || { echo "Invalid CONNECTOR: $CONNECTOR (like HDMI-A-1 or DP-1)" >&2; exit 1; }
PARAMETERS="drm.edid_firmware=${CONNECTOR}:${EDID_RELATIVE} video=${CONNECTOR}:e"
ARMBIAN_ENVIRONMENT="$ROOT/boot/armbianEnv.txt"
GRUB="$ROOT/etc/default/grub"
GRUB_DROP_IN_FOLDER="$ROOT/etc/default/grub.d"
GRUB_DROP_IN="$GRUB_DROP_IN_FOLDER/99-virtual-monitor.cfg"
KERNELSTUB_CONFIG="$ROOT/etc/kernelstub/configuration"
UBOOT_DEFAULTS="$ROOT/etc/default/u-boot"
EXTLINUX="$ROOT/boot/extlinux/extlinux.conf"
KERNEL_COMMAND_LINE="$ROOT/etc/kernel/cmdline"
LOADER_FOLDERS=("$ROOT/boot/loader/entries" "$ROOT/efi/loader/entries" "$ROOT/boot/efi/loader/entries")
# Set when no tool builds a boot image here, so there is no image to check
NO_BOOT_IMAGE=""

# sed without -i, which differs between GNU and BSD; rewrites in place to keep owner and permissions
edit() {
    local file="$1" new
    shift
    new="$(sed -E "$@" "$file")"
    printf '%s\n' "$new" > "$file"
}

keep_original() {
    [[ -f "$1.before-edid" ]] || cp "$1" "$1.before-edid"
}

# Rewrites the kernel arguments on the lines of FILE that match PREFIX, an awk regular expression
# for what comes before them (FILE PREFIX [FIRST] [ADDED]): drops the parameters of an earlier
# run and adds ADDED, by default $PARAMETERS. A closing quote stays at the end. FIRST=1 changes
# only the first match.
set_arguments() {
    local file="$1" program content
    program='
        function rewrite(arguments,    count, words, position, kept, quote, separator) {
            quote = ""
            if (arguments ~ /"$/) { quote = "\""; arguments = substr(arguments, 1, length(arguments) - 1) }
            count = split(arguments, words, /[[:space:]]+/)
            kept = ""
            separator = ""
            for (position = 1; position <= count; position++) {
                if (words[position] == "" || words[position] ~ /^drm\.edid_firmware=/ || index(words[position], video) == 1) { continue }
                kept = kept separator words[position]
                separator = " "
            }

            if (parameters != "") { kept = kept separator parameters }

            return kept quote
        }
        !done && match($0, prefix) { print substr($0, 1, RLENGTH) rewrite(substr($0, RLENGTH + 1)); done = first; next }
        { print }
    '

    content="$(awk -v prefix="$2" -v first="${3:-0}" -v parameters="${4-$PARAMETERS}" -v video="video=${CONNECTOR}:" "$program" "$file")"
    printf '%s\n' "$content" > "$file"
}

# Only the running kernel: old kernels whose modules were removed break the generation
build_boot_image() {
    if command -v update-initramfs >/dev/null 2>&1; then
        update-initramfs -u -k "$KERNEL_VERSION"
        return
    fi

    if command -v dracut >/dev/null 2>&1; then
        dracut -f --kver "$KERNEL_VERSION"
        return
    fi

    # Arch names its images after the preset, not the kernel version: build them all
    if command -v mkinitcpio >/dev/null 2>&1; then
        mkinitcpio -P
        return
    fi

    echo "    No update-initramfs, dracut or mkinitcpio: no boot image to build; the kernel reads the EDID from /usr/lib/firmware."
    NO_BOOT_IMAGE=1
}

# Whether the listing printed by the command names the EDID. The listing is read whole first: with
# pipefail, "lister | grep -q" fails when grep stops early and the lister dies of SIGPIPE.
image_has_edid() {
    local listing
    listing="$("$@" 2>/dev/null || true)"
    [[ "$listing" == *"$EDID_RELATIVE"* ]]
}

# Whether one of the mkinitcpio images (the fallback ones aside) has the EDID
initcpio_has_edid() {
    local image
    for image in "$ROOT"/boot/initramfs-*.img; do
        [[ "$image" != *-fallback.img ]] || continue
        image_has_edid lsinitcpio "$image" && return 0
    done
    return 1
}

check_boot_image() {
    [[ -z "$NO_BOOT_IMAGE" ]] || return 0
    echo "==> Checking that the EDID is in the image"
    if command -v lsinitrd >/dev/null 2>&1 && image_has_edid lsinitrd --kver "$KERNEL_VERSION"; then
        echo "    ok (lsinitrd)"
        return
    fi

    if command -v lsinitramfs >/dev/null 2>&1 && image_has_edid lsinitramfs "$ROOT/boot/initrd.img-$KERNEL_VERSION"; then
        echo "    ok (lsinitramfs)"
        return
    fi

    if command -v lsinitcpio >/dev/null 2>&1 && initcpio_has_edid; then
        echo "    ok (lsinitcpio)"
        return
    fi

    echo "    The EDID was not found in the boot image; stopping before touching the boot setup." >&2
    exit 1
}

add_armbian_parameters() {
    if ! grep -q '^extraargs=' "$ARMBIAN_ENVIRONMENT"; then
        echo "extraargs=${PARAMETERS}" >> "$ARMBIAN_ENVIRONMENT"
        return
    fi

    edit "$ARMBIAN_ENVIRONMENT" -e "s#^extraargs=(.*)#extraargs=\1 ${PARAMETERS}#" -e "s#^extraargs=[[:space:]]+#extraargs=#"
}

set_armbian_parameters() {
    echo "==> Adjusting the kernel parameters in $ARMBIAN_ENVIRONMENT"
    keep_original "$ARMBIAN_ENVIRONMENT"

    # Remove earlier parameters of this setup and add the new ones
    edit "$ARMBIAN_ENVIRONMENT" -e "/^extraargs=/s#[[:space:]]*video=${CONNECTOR}:[^ ]*##g" \
        -e "/^extraargs=/s#[[:space:]]*drm\.edid_firmware=[^ ]*##g"
    add_armbian_parameters
    grep '^extraargs=' "$ARMBIAN_ENVIRONMENT"
}

# Debian and Ubuntu read /etc/default/grub.d/*.cfg after /etc/default/grub, and a file there
# (the cloud images' 50-cloudimg-settings.cfg) can set GRUB_CMDLINE_LINUX_DEFAULT again
uses_grub_drop_in() {
    [[ -d "$GRUB_DROP_IN_FOLDER" ]] && command -v update-grub >/dev/null 2>&1
}

# The parameters go in a file of their own that runs last and adds to what the others set
set_grub_drop_in_parameters() {
    echo "==> Adjusting the kernel parameters in $GRUB_DROP_IN"
    printf '%s\n' "# Virtual monitor EDID, written by install-edid.sh. To undo: delete this file and run update-grub." \
        "GRUB_CMDLINE_LINUX_DEFAULT=\"\$GRUB_CMDLINE_LINUX_DEFAULT $PARAMETERS\"" > "$GRUB_DROP_IN"
    cat "$GRUB_DROP_IN"
    remove_grub_parameters
    update-grub
}

# An earlier version wrote the parameters in /etc/default/grub itself
remove_grub_parameters() {
    grep -q 'drm\.edid_firmware=' "$GRUB" || return 0
    keep_original "$GRUB"
    set_arguments "$GRUB" '^GRUB_CMDLINE_LINUX_DEFAULT="' 0 ""
}

set_grub_parameters() {
    uses_grub_drop_in && { set_grub_drop_in_parameters; return; }

    echo "==> Adjusting the kernel parameters in GRUB"
    keep_original "$GRUB"
    # Fedora and openSUSE set only GRUB_CMDLINE_LINUX; every grub.cfg generator also reads this one
    grep -q '^GRUB_CMDLINE_LINUX_DEFAULT=' "$GRUB" || echo 'GRUB_CMDLINE_LINUX_DEFAULT=""' >> "$GRUB"
    set_arguments "$GRUB" '^GRUB_CMDLINE_LINUX_DEFAULT="'
    grep GRUB_CMDLINE_LINUX_DEFAULT "$GRUB"
    apply_grub
}

# The command that applies /etc/default/grub here. Fedora keeps a boot entry per kernel in
# /boot/loader/entries, which grub2-mkconfig does not rewrite: grubby changes them.
apply_grub() {
    if command -v update-grub >/dev/null 2>&1; then
        update-grub
        return
    fi

    if command -v grubby >/dev/null 2>&1; then
        set_grubby_parameters
        return
    fi

    if command -v grub2-mkconfig >/dev/null 2>&1; then
        grub2-mkconfig -o "$ROOT/boot/grub2/grub.cfg"
        return
    fi

    if command -v grub-mkconfig >/dev/null 2>&1; then
        grub-mkconfig -o "$ROOT/boot/grub/grub.cfg"
        return
    fi

    echo "Neither update-grub, grubby, grub2-mkconfig nor grub-mkconfig found to apply $GRUB." >&2
    exit 1
}

# Parameters of an earlier run in the boot entries, as grubby lists them (args="...")
old_grubby_parameters() {
    grubby --info=ALL 2>/dev/null | tr ' "' '\n\n' | grep -E "^(drm\.edid_firmware=|video=${CONNECTOR}:)" | sort -u | tr '\n' ' ' || true
}

set_grubby_parameters() {
    local old_parameters
    old_parameters="$(old_grubby_parameters)"
    [[ -z "$old_parameters" ]] || grubby --update-kernel=ALL --remove-args="${old_parameters% }"
    grubby --update-kernel=ALL --args="$PARAMETERS"
}

# The kernel command line of the Raspberry Pi: one line in cmdline.txt
raspberry_command_line() {
    local file
    for file in "$ROOT/boot/firmware/cmdline.txt" "$ROOT/boot/cmdline.txt"; do
        [[ -f "$file" ]] || continue
        echo "$file"
        return
    done
}

# A file that holds only the command line (cmdline.txt, /etc/kernel/cmdline)
set_command_line_parameters() {
    echo "==> Adjusting the kernel parameters in $1"
    keep_original "$1"
    set_arguments "$1" '^' 1
    head -n 1 "$1"
}

# Debian's u-boot-menu writes extlinux.conf from /etc/default/u-boot at every kernel update
uses_uboot_menu() {
    [[ -f "$UBOOT_DEFAULTS" ]] && command -v u-boot-update >/dev/null 2>&1
}

set_uboot_parameters() {
    echo "==> Adjusting the kernel parameters in $UBOOT_DEFAULTS"
    keep_original "$UBOOT_DEFAULTS"
    # Unset, u-boot-update uses "ro quiet"
    grep -q '^U_BOOT_PARAMETERS=' "$UBOOT_DEFAULTS" || echo 'U_BOOT_PARAMETERS="ro quiet"' >> "$UBOOT_DEFAULTS"
    set_arguments "$UBOOT_DEFAULTS" '^U_BOOT_PARAMETERS="'
    grep '^U_BOOT_PARAMETERS=' "$UBOOT_DEFAULTS"
    u-boot-update
}

EXTLINUX_APPEND='^[[:space:]]*[Aa][Pp][Pp][Ee][Nn][Dd][[:space:]]+'

set_extlinux_parameters() {
    echo "==> Adjusting the kernel parameters in $EXTLINUX"
    grep -qE "$EXTLINUX_APPEND" "$EXTLINUX" || { echo "$EXTLINUX has no append line for the parameters: $PARAMETERS" >&2; exit 1; }
    keep_original "$EXTLINUX"
    set_arguments "$EXTLINUX" "$EXTLINUX_APPEND"
    grep -iE "$EXTLINUX_APPEND" "$EXTLINUX"
}

has_loader_entries() {
    local folder file
    for folder in "${LOADER_FOLDERS[@]}"; do
        for file in "$folder"/*.conf; do
            [[ -f "$file" ]] && return 0
        done
    done
    return 1
}

# An entry with no options line gets one
set_entry_parameters() {
    echo "==> Adjusting the kernel parameters in $1"
    keep_original "$1"
    grep -q '^options[[:space:]]' "$1" || echo "options " >> "$1"
    set_arguments "$1" '^options[[:space:]]+'
    grep '^options' "$1"
}

# Every systemd-boot entry, and /etc/kernel/cmdline, which kernel-install reads for new kernels
set_loader_parameters() {
    local folder file
    for folder in "${LOADER_FOLDERS[@]}"; do
        for file in "$folder"/*.conf; do
            [[ -f "$file" ]] || continue
            set_entry_parameters "$file"
        done
    done

    [[ -f "$KERNEL_COMMAND_LINE" ]] || return 0
    set_command_line_parameters "$KERNEL_COMMAND_LINE"
}

# Parameters of an earlier run, as kernelstub keeps them in its JSON configuration
old_kernelstub_parameters() {
    grep -oE "\"(drm\.edid_firmware=[^\"]*|video=${CONNECTOR}:[^\"]*)\"" "$KERNELSTUB_CONFIG" | tr -d '"' | sort -u | tr '\n' ' ' || true
}

set_kernelstub_parameters() {
    local old_parameters
    echo "==> Adjusting the kernel parameters with kernelstub"
    keep_original "$KERNELSTUB_CONFIG"

    # Remove earlier parameters of this setup and add the new ones
    old_parameters="$(old_kernelstub_parameters)"
    [[ -z "$old_parameters" ]] || kernelstub -d "${old_parameters% }"
    kernelstub -a "$PARAMETERS"
}

uses_kernelstub() {
    [[ -f "$KERNELSTUB_CONFIG" ]] && command -v kernelstub >/dev/null 2>&1
}

set_kernel_parameters() {
    local command_line

    if [[ -f "$ARMBIAN_ENVIRONMENT" ]]; then
        set_armbian_parameters
        return
    fi

    command_line="$(raspberry_command_line)"
    if [[ -n "$command_line" ]]; then
        set_command_line_parameters "$command_line"
        return
    fi

    if uses_kernelstub; then
        set_kernelstub_parameters
        return
    fi

    if [[ -f "$GRUB" ]]; then
        set_grub_parameters
        return
    fi

    if uses_uboot_menu; then
        set_uboot_parameters
        return
    fi

    if [[ -f "$EXTLINUX" ]]; then
        set_extlinux_parameters
        return
    fi

    if has_loader_entries; then
        set_loader_parameters
        return
    fi

    echo "No boot setup found (armbianEnv.txt, cmdline.txt, kernelstub, GRUB, U-Boot or systemd-boot): I do not know where to put the kernel parameters." >&2
    echo "Add to the kernel command line: $PARAMETERS" >&2
    exit 1
}

[[ -f "$EDID_SOURCE" ]] || { echo "$EDID_SOURCE not found" >&2; exit 1; }
[[ "$(wc -c < "$EDID_SOURCE" | tr -d ' ')" -eq 256 ]] || { echo "$EDID_SOURCE is not 256 bytes; it does not look like an EDID." >&2; exit 1; }

echo "==> Copying the EDID to $EDID_TARGET"
mkdir -p "$(dirname "$EDID_TARGET")"
install -m 644 "$EDID_SOURCE" "$EDID_TARGET"

KERNEL_VERSION="$(uname -r)"
echo "==> Adding the EDID to the boot image (kernel $KERNEL_VERSION)"
# The boot image hooks of earlier versions, which used edid/ultrawide.bin
rm -f "$ROOT/etc/dracut.conf.d/90-edid-ultrawide.conf" "$ROOT/etc/initramfs-tools/hooks/edid-ultrawide"
# The hook goes wherever the tool that builds the image reads it; the folder may not exist yet
if command -v dracut >/dev/null 2>&1; then
    mkdir -p "$ROOT/etc/dracut.conf.d"
    echo "install_items+=\" /usr/lib/firmware/$EDID_RELATIVE \"" > "$ROOT/etc/dracut.conf.d/90-edid-virtual-monitor.conf"
fi

if command -v mkinitcpio >/dev/null 2>&1; then
    mkdir -p "$ROOT/etc/mkinitcpio.conf.d"
    echo "FILES+=(/usr/lib/firmware/$EDID_RELATIVE)" > "$ROOT/etc/mkinitcpio.conf.d/virtual-monitor.conf"
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
check_boot_image

set_kernel_parameters

echo
echo "Done: $CONNECTOR gets the virtual monitor at the next boot. Reboot with: sudo reboot"
echo "Then: virtual-monitor --list"
