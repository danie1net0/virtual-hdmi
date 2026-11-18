#!/usr/bin/env bash
# Tests scripts/install-edid.sh with the system root in a temporary folder.
source "$(dirname "$0")/lib.sh"

SCRIPT="$PROJECT/scripts/install-edid.sh"
EDID="$PROJECT/edid/virtual-monitor.bin"
PARAMETERS="drm.edid_firmware=HDMI-A-1:edid/virtual-monitor.bin video=HDMI-A-1:e"
KERNEL_VERSION="6.1.0-test"

# Armbian kernel and tools (initramfs-tools); the EDID shows up in the image
armbian() {
    new_case
    mkdir -p "$ROOT/boot" "$ROOT/etc/initramfs-tools/hooks"
    printf 'verbosity=1\n%s\nrootdev=UUID=abc\n' "$1" > "$ROOT/boot/armbianEnv.txt"
    stub uname "echo $KERNEL_VERSION"
    stub update-initramfs
    stub lsinitramfs 'echo usr/lib/firmware/edid/virtual-monitor.bin'
}

# Fedora/Lenovo kernel and tools (dracut + GRUB)
grub() {
    new_case
    mkdir -p "$ROOT/etc/default" "$ROOT/etc/dracut.conf.d"
    printf 'GRUB_TIMEOUT=5\nGRUB_CMDLINE_LINUX_DEFAULT="%s"\n' "$1" > "$ROOT/etc/default/grub"
    stub uname "echo $KERNEL_VERSION"
    stub dracut
    stub lsinitrd 'echo usr/lib/firmware/edid/virtual-monitor.bin'
    stub update-grub
}

# Pop!_OS: kernelstub (systemd-boot) and initramfs-tools; the configuration keeps the options in JSON
pop() {
    new_case
    mkdir -p "$ROOT/etc/kernelstub" "$ROOT/etc/initramfs-tools/hooks"
    printf '{"user": {"kernel_options": ["quiet", "splash"%s]}}\n' "$1" > "$ROOT/etc/kernelstub/configuration"
    stub uname "echo $KERNEL_VERSION"
    stub update-initramfs
    stub lsinitramfs 'echo usr/lib/firmware/edid/virtual-monitor.bin'
    stub kernelstub
}

# Fedora: GRUB_CMDLINE_LINUX only, dracut, and grubby for the boot entries; grubby lists ARGS
fedora() {
    new_case
    mkdir -p "$ROOT/etc/default"
    printf 'GRUB_TIMEOUT=5\nGRUB_CMDLINE_LINUX="rhgb quiet"\n' > "$ROOT/etc/default/grub"
    stub uname "echo $KERNEL_VERSION"
    stub dracut
    stub lsinitrd 'echo usr/lib/firmware/edid/virtual-monitor.bin'
    stub grubby "[[ \"\$1\" == --info=ALL ]] && echo 'args=\"$1\"'; exit 0"
}

# Arch: mkinitcpio, its images named after the preset
arch() {
    new_case
    mkdir -p "$ROOT/boot"
    : > "$ROOT/boot/initramfs-linux.img"
    : > "$ROOT/boot/initramfs-linux-fallback.img"
    stub uname "echo $KERNEL_VERSION"
    stub mkinitcpio
    stub lsinitcpio '[[ "$1" == *-fallback.img ]] && exit 0; echo usr/lib/firmware/edid/virtual-monitor.bin'
}

# Raspberry Pi OS: one line in cmdline.txt (FILE TEXT) and initramfs-tools
raspberry() {
    new_case
    mkdir -p "$(dirname "$ROOT/$1")"
    printf '%s\n' "$2" > "$ROOT/$1"
    stub uname "echo $KERNEL_VERSION"
    stub update-initramfs
    stub lsinitramfs 'echo usr/lib/firmware/edid/virtual-monitor.bin'
}

# A machine with no boot image tool; the boot setup comes after
no_boot_image() {
    new_case
    stub uname "echo $KERNEL_VERSION"
}

line() {
    grep "$1" "$2"
}

echo "# permissions and input"
new_case
FAKE_UID=1000 run_script "$SCRIPT" "$EDID"
status_is 1 "fails without root"
contains "$ERRORS" "Run with sudo." "asks for sudo"
check "copies nothing without root" test ! -e "$ROOT/usr"

new_case
run_script "$SCRIPT" "$CASE/missing.bin"
status_is 1 "missing EDID fails"
contains "$ERRORS" "missing.bin not found" "says which file is missing"

new_case
printf 'short' > "$CASE/short.bin"
run_script "$SCRIPT" "$CASE/short.bin"
status_is 1 "a file that is not 256 bytes fails"
contains "$ERRORS" "is not 256 bytes" "explains the size"
check "does not copy an invalid file" test ! -e "$ROOT/usr/lib/firmware/edid/virtual-monitor.bin"

echo "# Armbian"
armbian "extraargs=cma=256M"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs on Armbian"
check "copies the EDID" cmp "$EDID" "$ROOT/usr/lib/firmware/edid/virtual-monitor.bin"
check "initramfs hook is executable" test -x "$ROOT/etc/initramfs-tools/hooks/edid-virtual-monitor"
contains "$ROOT/etc/initramfs-tools/hooks/edid-virtual-monitor" 'cp /usr/lib/firmware/edid/virtual-monitor.bin "${DESTDIR}/usr/lib/firmware/edid/"' "hook copies the EDID into the image"
check "without dracut, creates no dracut config" test ! -e "$ROOT/etc/dracut.conf.d"
called "update-initramfs -u -k $KERNEL_VERSION"
called "lsinitramfs $ROOT/boot/initrd.img-$KERNEL_VERSION"
check "appends the parameters to extraargs" test "$(line '^extraargs=' "$ROOT/boot/armbianEnv.txt")" = "extraargs=cma=256M $PARAMETERS"
check "keeps the other lines" grep -qx 'rootdev=UUID=abc' "$ROOT/boot/armbianEnv.txt"
check "keeps the original" test "$(line '^extraargs=' "$ROOT/boot/armbianEnv.txt.before-edid")" = "extraargs=cma=256M"
contains "$OUTPUT" "ok (lsinitramfs)" "checks the image with lsinitramfs"
contains "$OUTPUT" "Done" "ends with the reboot instruction"
not_called update-grub

run_script "$SCRIPT" "$EDID"
status_is 0 "reinstalls on Armbian"
check "does not duplicate the parameters" test "$(line '^extraargs=' "$ROOT/boot/armbianEnv.txt")" = "extraargs=cma=256M $PARAMETERS"
check "does not overwrite the saved original" test "$(line '^extraargs=' "$ROOT/boot/armbianEnv.txt.before-edid")" = "extraargs=cma=256M"

armbian "extraargs=drm.edid_firmware=HDMI-A-1:edid/velho.bin video=HDMI-A-1:D"
run_script "$SCRIPT" "$EDID"
check "replaces old parameters leaving no leading space" test "$(line '^extraargs=' "$ROOT/boot/armbianEnv.txt")" = "extraargs=$PARAMETERS"

armbian "# no extraargs"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs without an extraargs line"
check "creates the extraargs line" test "$(line '^extraargs=' "$ROOT/boot/armbianEnv.txt")" = "extraargs=$PARAMETERS"
check "creates the line only once" test "$(grep -c '^extraargs=' "$ROOT/boot/armbianEnv.txt")" = 1

echo "# GRUB"
grub "quiet splash"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs with GRUB and dracut"
contains "$ROOT/etc/dracut.conf.d/90-edid-virtual-monitor.conf" 'install_items+=" /usr/lib/firmware/edid/virtual-monitor.bin "' "adds the EDID to dracut"
check "without update-initramfs, creates no hook" test ! -e "$ROOT/etc/initramfs-tools"
called "dracut -f --kver $KERNEL_VERSION"
called "lsinitrd --kver $KERNEL_VERSION"
called "update-grub"
contains "$OUTPUT" "ok (lsinitrd)" "checks the image with lsinitrd"
check "appends the parameters to GRUB" test "$(line '^GRUB_CMDLINE_LINUX_DEFAULT=' "$ROOT/etc/default/grub")" = "GRUB_CMDLINE_LINUX_DEFAULT=\"quiet splash $PARAMETERS\""
check "keeps the original GRUB" grep -qx 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"' "$ROOT/etc/default/grub.before-edid"
check "keeps the other GRUB lines" grep -qx 'GRUB_TIMEOUT=5' "$ROOT/etc/default/grub"

run_script "$SCRIPT" "$EDID"
check "does not duplicate the parameters in GRUB" test "$(line '^GRUB_CMDLINE_LINUX_DEFAULT=' "$ROOT/etc/default/grub")" = "GRUB_CMDLINE_LINUX_DEFAULT=\"quiet splash $PARAMETERS\""
check "does not overwrite the saved GRUB" grep -qx 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"' "$ROOT/etc/default/grub.before-edid"

grub ""
run_script "$SCRIPT" "$EDID"
check "empty GRUB has no leading space" test "$(line '^GRUB_CMDLINE_LINUX_DEFAULT=' "$ROOT/etc/default/grub")" = "GRUB_CMDLINE_LINUX_DEFAULT=\"$PARAMETERS\""

grub "quiet video=HDMI-A-1:D drm.edid_firmware=HDMI-A-1:edid/velho.bin splash"
run_script "$SCRIPT" "$EDID"
check "replaces old parameters in GRUB" test "$(line '^GRUB_CMDLINE_LINUX_DEFAULT=' "$ROOT/etc/default/grub")" = "GRUB_CMDLINE_LINUX_DEFAULT=\"quiet splash $PARAMETERS\""

echo "# kernelstub (Pop!_OS)"
pop ""
run_script "$SCRIPT" "$EDID"
status_is 0 "installs with kernelstub"
called "kernelstub -a $PARAMETERS"
not_called "kernelstub -d"
check "keeps the original kernelstub configuration" cmp "$ROOT/etc/kernelstub/configuration" "$ROOT/etc/kernelstub/configuration.before-edid"
called "update-initramfs -u -k $KERNEL_VERSION"
contains "$OUTPUT" "Adjusting the kernel parameters with kernelstub" "says it uses kernelstub"
not_called update-grub

pop ', "drm.edid_firmware=HDMI-A-1:edid/velho.bin", "video=HDMI-A-1:D", "video=DP-2:e"'
echo '{"user": {"kernel_options": ["quiet"]}}' > "$ROOT/etc/kernelstub/configuration.before-edid"
run_script "$SCRIPT" "$EDID"
status_is 0 "reinstalls with kernelstub"
called "kernelstub -d drm.edid_firmware=HDMI-A-1:edid/velho.bin video=HDMI-A-1:D"
called "kernelstub -a $PARAMETERS"
check "does not overwrite the saved kernelstub configuration" grep -q '\["quiet"\]' "$ROOT/etc/kernelstub/configuration.before-edid"

pop ""
rm -r "$ROOT/etc/initramfs-tools"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs when the initramfs-tools hooks folder does not exist yet"
check "creates the hooks folder and the hook" test -x "$ROOT/etc/initramfs-tools/hooks/edid-virtual-monitor"

grub "quiet"
rm -r "$ROOT/etc/dracut.conf.d"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs when dracut.conf.d does not exist yet"
contains "$ROOT/etc/dracut.conf.d/90-edid-virtual-monitor.conf" "edid/virtual-monitor.bin" "creates the dracut folder and config"

pop ""
mkdir -p "$ROOT/etc/default"
printf 'GRUB_CMDLINE_LINUX_DEFAULT="quiet"\n' > "$ROOT/etc/default/grub"
stub update-grub
run_script "$SCRIPT" "$EDID"
check "prefers kernelstub over GRUB" grep -qx 'GRUB_CMDLINE_LINUX_DEFAULT="quiet"' "$ROOT/etc/default/grub"
not_called update-grub

pop ""
rm "$STUBS/kernelstub"
run_script "$SCRIPT" "$EDID"
status_is 1 "kernelstub configuration without kernelstub is not used"

echo "# connector"
pop ""
CONNECTOR=DP-1 run_script "$SCRIPT" "$EDID"
status_is 0 "installs on the CONNECTOR output"
called "kernelstub -a drm.edid_firmware=DP-1:edid/virtual-monitor.bin video=DP-1:e"

pop ""
CONNECTOR=DP-1 run_script "$SCRIPT" "$EDID" HDMI-A-2
status_is 0 "installs on the output given as argument"
called "kernelstub -a drm.edid_firmware=HDMI-A-2:edid/virtual-monitor.bin video=HDMI-A-2:e"
contains "$OUTPUT" "Done: HDMI-A-2 gets the virtual monitor" "says which output gets it"

echo "# hooks of earlier versions"
armbian "extraargs=cma=256M"
mkdir -p "$ROOT/etc/dracut.conf.d"
echo old > "$ROOT/etc/initramfs-tools/hooks/edid-ultrawide"
echo old > "$ROOT/etc/dracut.conf.d/90-edid-ultrawide.conf"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs over an earlier version"
check "removes the old initramfs hook" test ! -e "$ROOT/etc/initramfs-tools/hooks/edid-ultrawide"
check "removes the old dracut configuration" test ! -e "$ROOT/etc/dracut.conf.d/90-edid-ultrawide.conf"

new_case
CONNECTOR='HDMI-A-1 rm -rf /' run_script "$SCRIPT" "$EDID"
status_is 1 "refuses an invalid connector"
contains "$ERRORS" "Invalid CONNECTOR" "says the connector is invalid"
check "copies nothing with an invalid connector" test ! -e "$ROOT/usr"

echo "# boot image"
grub "quiet"
rm "$STUBS/dracut" "$STUBS/lsinitrd"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs without a boot image tool"
contains "$OUTPUT" "the kernel reads the EDID from /usr/lib/firmware" "says there is no boot image to build"
not_contains "$OUTPUT" "Checking that the EDID is in the image" "checks no image"
called "update-grub"

armbian "extraargs=cma=256M"
stub lsinitramfs 'echo usr/lib/modules'
run_script "$SCRIPT" "$EDID"
status_is 1 "EDID outside the image fails"
contains "$ERRORS" "stopping before touching the boot setup" "stops before the boot setup"
check "leaves armbianEnv alone" test "$(line '^extraargs=' "$ROOT/boot/armbianEnv.txt")" = "extraargs=cma=256M"
check "keeps no backup without changes" test ! -e "$ROOT/boot/armbianEnv.txt.before-edid"

armbian "extraargs=cma=256M"
stub lsinitrd 'echo nada'
run_script "$SCRIPT" "$EDID"
status_is 0 "lsinitrd without the EDID falls back to lsinitramfs"
contains "$OUTPUT" "ok (lsinitramfs)" "uses lsinitramfs after lsinitrd"

# A real image lists thousands of files after the EDID; grep -q would stop reading and the lister
# would die of SIGPIPE, which pipefail turns into a failed check
armbian "extraargs=cma=256M"
stub lsinitramfs 'echo usr/lib/firmware/edid/virtual-monitor.bin; index=0; while [ $index -lt 50000 ]; do echo usr/lib/modules/file-$index; index=$((index + 1)); done'
run_script "$SCRIPT" "$EDID"
status_is 0 "finds the EDID at the top of a long listing"
contains "$OUTPUT" "ok (lsinitramfs)" "accepts the long listing"

armbian "extraargs=cma=256M"
stub lsinitramfs 'echo usr/lib/firmware/edid/virtual-monitor.bin; exit 1'
run_script "$SCRIPT" "$EDID"
status_is 0 "a lister that fails after printing the EDID still counts"

armbian "extraargs=cma=256M"
rm "$STUBS/lsinitramfs"
run_script "$SCRIPT" "$EDID"
status_is 1 "fails without lsinitrd and lsinitramfs"

echo "# GRUB on Fedora, openSUSE and Arch"
fedora "rhgb quiet"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs on Fedora"
check "adds GRUB_CMDLINE_LINUX_DEFAULT when only GRUB_CMDLINE_LINUX exists" test "$(line '^GRUB_CMDLINE_LINUX_DEFAULT=' "$ROOT/etc/default/grub")" = "GRUB_CMDLINE_LINUX_DEFAULT=\"$PARAMETERS\""
check "keeps GRUB_CMDLINE_LINUX" grep -qx 'GRUB_CMDLINE_LINUX="rhgb quiet"' "$ROOT/etc/default/grub"
called "grubby --update-kernel=ALL --args=$PARAMETERS"
not_called "grubby --update-kernel=ALL --remove-args"

fedora "rhgb quiet drm.edid_firmware=HDMI-A-1:edid/velho.bin video=HDMI-A-1:D video=DP-2:e"
run_script "$SCRIPT" "$EDID"
status_is 0 "reinstalls on Fedora"
called "grubby --update-kernel=ALL --remove-args=drm.edid_firmware=HDMI-A-1:edid/velho.bin video=HDMI-A-1:D"
called "grubby --update-kernel=ALL --args=$PARAMETERS"

grub "quiet"
rm "$STUBS/update-grub"
stub grub2-mkconfig
run_script "$SCRIPT" "$EDID"
status_is 0 "installs with grub2-mkconfig (openSUSE)"
called "grub2-mkconfig -o $ROOT/boot/grub2/grub.cfg"

grub "quiet"
rm "$STUBS/update-grub"
stub grub-mkconfig
run_script "$SCRIPT" "$EDID"
status_is 0 "installs with grub-mkconfig (Arch)"
called "grub-mkconfig -o $ROOT/boot/grub/grub.cfg"

grub "quiet"
rm "$STUBS/update-grub"
run_script "$SCRIPT" "$EDID"
status_is 1 "fails with no tool to apply GRUB"
contains "$ERRORS" "Neither update-grub, grubby, grub2-mkconfig nor grub-mkconfig" "names the missing tools"

echo "# mkinitcpio (Arch)"
arch
mkdir -p "$ROOT/boot/loader/entries"
printf 'title Arch Linux\nlinux /vmlinuz-linux\noptions root=UUID=abc rw\n' > "$ROOT/boot/loader/entries/arch.conf"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs on Arch"
contains "$ROOT/etc/mkinitcpio.conf.d/virtual-monitor.conf" "FILES+=(/usr/lib/firmware/edid/virtual-monitor.bin)" "adds the EDID to mkinitcpio"
called "mkinitcpio -P"
called "lsinitcpio $ROOT/boot/initramfs-linux.img"
not_called "lsinitcpio $ROOT/boot/initramfs-linux-fallback.img"
contains "$OUTPUT" "ok (lsinitcpio)" "checks the image with lsinitcpio"

arch
stub lsinitcpio 'echo usr/lib/modules'
mkdir -p "$ROOT/boot/loader/entries"
printf 'options root=UUID=abc\n' > "$ROOT/boot/loader/entries/arch.conf"
run_script "$SCRIPT" "$EDID"
status_is 1 "mkinitcpio image without the EDID fails"
check "leaves the entry alone" grep -qx 'options root=UUID=abc' "$ROOT/boot/loader/entries/arch.conf"

echo "# systemd-boot"
arch
mkdir -p "$ROOT/boot/loader/entries" "$ROOT/efi/loader/entries" "$ROOT/etc/kernel"
printf 'title Arch Linux\nlinux /vmlinuz-linux\noptions root=UUID=abc rw video=HDMI-A-1:D\n' > "$ROOT/boot/loader/entries/arch.conf"
printf 'title Fallback\nlinux /vmlinuz-linux\n' > "$ROOT/efi/loader/entries/fallback.conf"
echo "root=UUID=abc rw" > "$ROOT/etc/kernel/cmdline"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs with systemd-boot"
check "replaces the parameters in the entry" grep -qx "options root=UUID=abc rw $PARAMETERS" "$ROOT/boot/loader/entries/arch.conf"
check "keeps the other lines of the entry" grep -qx 'linux /vmlinuz-linux' "$ROOT/boot/loader/entries/arch.conf"
check "adds an options line to an entry without one" grep -qx "options $PARAMETERS" "$ROOT/efi/loader/entries/fallback.conf"
check "keeps the original entry" grep -qx 'options root=UUID=abc rw video=HDMI-A-1:D' "$ROOT/boot/loader/entries/arch.conf.before-edid"
check "adds the parameters to /etc/kernel/cmdline" grep -qx "root=UUID=abc rw $PARAMETERS" "$ROOT/etc/kernel/cmdline"

run_script "$SCRIPT" "$EDID"
check "does not duplicate the parameters in the entry" grep -qx "options root=UUID=abc rw $PARAMETERS" "$ROOT/boot/loader/entries/arch.conf"
check "does not overwrite the saved entry" grep -qx 'options root=UUID=abc rw video=HDMI-A-1:D' "$ROOT/boot/loader/entries/arch.conf.before-edid"

arch
mkdir -p "$ROOT/boot/efi/loader/entries"
printf 'options quiet\n' > "$ROOT/boot/efi/loader/entries/opensuse.conf"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs with entries in /boot/efi and no /etc/kernel/cmdline"
check "changes the entry in /boot/efi" grep -qx "options quiet $PARAMETERS" "$ROOT/boot/efi/loader/entries/opensuse.conf"
check "creates no /etc/kernel/cmdline" test ! -e "$ROOT/etc/kernel/cmdline"

echo "# Raspberry Pi"
raspberry boot/firmware/cmdline.txt "console=serial0,115200 root=PARTUUID=abc rootwait drm.edid_firmware=HDMI-A-1:edid/velho.bin"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs on Raspberry Pi OS"
check "replaces the parameters in cmdline.txt" test "$(cat "$ROOT/boot/firmware/cmdline.txt")" = "console=serial0,115200 root=PARTUUID=abc rootwait $PARAMETERS"
check "keeps the original cmdline.txt" grep -q 'edid/velho.bin' "$ROOT/boot/firmware/cmdline.txt.before-edid"

run_script "$SCRIPT" "$EDID"
check "keeps cmdline.txt on one line" test "$(wc -l < "$ROOT/boot/firmware/cmdline.txt" | tr -d ' ')" = 1
check "does not duplicate the parameters in cmdline.txt" test "$(cat "$ROOT/boot/firmware/cmdline.txt")" = "console=serial0,115200 root=PARTUUID=abc rootwait $PARAMETERS"

raspberry boot/cmdline.txt "root=/dev/mmcblk0p2 rootwait"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs with the older /boot/cmdline.txt"
check "changes /boot/cmdline.txt" test "$(cat "$ROOT/boot/cmdline.txt")" = "root=/dev/mmcblk0p2 rootwait $PARAMETERS"

raspberry boot/firmware/cmdline.txt "root=/dev/mmcblk0p2"
rm "$STUBS/update-initramfs" "$STUBS/lsinitramfs"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs on a Raspberry Pi with no initramfs"
check "still sets cmdline.txt" test "$(cat "$ROOT/boot/firmware/cmdline.txt")" = "root=/dev/mmcblk0p2 $PARAMETERS"

echo "# U-Boot"
no_boot_image
mkdir -p "$ROOT/etc/default"
printf '# U_BOOT_PARAMETERS="ro quiet"\nU_BOOT_PARAMETERS="ro quiet video=HDMI-A-1:D"\n' > "$ROOT/etc/default/u-boot"
stub u-boot-update
run_script "$SCRIPT" "$EDID"
status_is 0 "installs with u-boot-menu"
check "sets U_BOOT_PARAMETERS" grep -qx "U_BOOT_PARAMETERS=\"ro quiet $PARAMETERS\"" "$ROOT/etc/default/u-boot"
check "leaves the comment alone" grep -qx '# U_BOOT_PARAMETERS="ro quiet"' "$ROOT/etc/default/u-boot"
called "u-boot-update"

no_boot_image
mkdir -p "$ROOT/etc/default" "$ROOT/boot/extlinux"
echo 'U_BOOT_MENU_LABEL="Debian"' > "$ROOT/etc/default/u-boot"
echo "  append root=/dev/sda1" > "$ROOT/boot/extlinux/extlinux.conf"
stub u-boot-update
run_script "$SCRIPT" "$EDID"
status_is 0 "installs with u-boot-menu and no U_BOOT_PARAMETERS"
check "starts from the u-boot-update default" grep -qx "U_BOOT_PARAMETERS=\"ro quiet $PARAMETERS\"" "$ROOT/etc/default/u-boot"
check "leaves extlinux.conf to u-boot-update" grep -qx "  append root=/dev/sda1" "$ROOT/boot/extlinux/extlinux.conf"

no_boot_image
mkdir -p "$ROOT/etc/default" "$ROOT/boot/extlinux"
echo 'U_BOOT_PARAMETERS="ro"' > "$ROOT/etc/default/u-boot"
echo "append root=/dev/sda1" > "$ROOT/boot/extlinux/extlinux.conf"
run_script "$SCRIPT" "$EDID"
status_is 0 "without u-boot-update, edits extlinux.conf"
check "leaves /etc/default/u-boot alone" grep -qx 'U_BOOT_PARAMETERS="ro"' "$ROOT/etc/default/u-boot"
check "changes extlinux.conf" grep -qx "append root=/dev/sda1 $PARAMETERS" "$ROOT/boot/extlinux/extlinux.conf"

no_boot_image
mkdir -p "$ROOT/boot/extlinux"
printf 'label linux\n  kernel /Image\n  APPEND root=/dev/mmcblk0p2 video=HDMI-A-1:D\nlabel rescue\n  append root=/dev/mmcblk0p2 single\n' > "$ROOT/boot/extlinux/extlinux.conf"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs with extlinux.conf"
check "changes every append line" test "$(grep -ci "append.*$PARAMETERS" "$ROOT/boot/extlinux/extlinux.conf")" = 2
check "keeps the case and indentation" grep -qx "  APPEND root=/dev/mmcblk0p2 $PARAMETERS" "$ROOT/boot/extlinux/extlinux.conf"
check "keeps the original extlinux.conf" grep -q 'video=HDMI-A-1:D' "$ROOT/boot/extlinux/extlinux.conf.before-edid"

no_boot_image
mkdir -p "$ROOT/boot/extlinux"
printf 'label linux\n  kernel /Image\n' > "$ROOT/boot/extlinux/extlinux.conf"
run_script "$SCRIPT" "$EDID"
status_is 1 "fails with an extlinux.conf without append"
contains "$ERRORS" "has no append line" "says there is no append line"
check "keeps no backup of extlinux.conf" test ! -e "$ROOT/boot/extlinux/extlinux.conf.before-edid"

echo "# boot loader"
new_case
stub uname "echo $KERNEL_VERSION"
stub update-initramfs
stub lsinitramfs 'echo usr/lib/firmware/edid/virtual-monitor.bin'
run_script "$SCRIPT" "$EDID"
status_is 1 "fails without a known boot setup"
contains "$ERRORS" "No boot setup found" "says no boot setup was found"
contains "$ERRORS" "Add to the kernel command line: $PARAMETERS" "shows the parameters to set by hand"

echo "# EDID path"
armbian "extraargs=cma=256M"
run_script "$SCRIPT"
status_is 0 "no argument uses the default EDID"
check "default EDID is the project virtual-monitor.bin" cmp "$PROJECT/edid/virtual-monitor.bin" "$ROOT/usr/lib/firmware/edid/virtual-monitor.bin"

armbian "extraargs=cma=256M"
cd "$PROJECT" || exit 1
run_script "$SCRIPT" edid/virtual-monitor.bin
cd - > /dev/null || exit 1
status_is 0 "relative path counts from the current folder"
check "copies the EDID from the relative path" cmp "$EDID" "$ROOT/usr/lib/firmware/edid/virtual-monitor.bin"

summary
