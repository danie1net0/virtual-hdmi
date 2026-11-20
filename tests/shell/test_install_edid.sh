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

# dracut and GRUB applied with update-grub
grub() {
    new_case
    mkdir -p "$ROOT/etc/default" "$ROOT/etc/dracut.conf.d"
    printf 'GRUB_TIMEOUT=5\nGRUB_CMDLINE_LINUX_DEFAULT="%s"\n' "$1" > "$ROOT/etc/default/grub"
    stub uname "echo $KERNEL_VERSION"
    stub dracut
    stub lsinitrd 'echo usr/lib/firmware/edid/virtual-monitor.bin'
    stub update-grub
}

# Debian and Ubuntu: GRUB with a grub.d file that sets the command line again
grub_drop_in() {
    grub "$1"
    mkdir -p "$ROOT/etc/default/grub.d"
    printf 'GRUB_CMDLINE_LINUX_DEFAULT="console=tty1"\n' > "$ROOT/etc/default/grub.d/50-cloudimg-settings.cfg"
    DROP_IN="$ROOT/etc/default/grub.d/99-virtual-monitor.cfg"
}

# What update-grub reads: /etc/default/grub, then each grub.d file in order
grub_command_line() {
    (
        source "$ROOT/etc/default/grub"
        for file in "$ROOT"/etc/default/grub.d/*.cfg; do
            source "$file"
        done

        echo "$GRUB_CMDLINE_LINUX_DEFAULT"
    )
}

# Booted from a UKI: systemd-stub left StubInfo; the boot loader added BOOT_IMAGE= and initrd=
uki() {
    new_case
    mkdir -p "$ROOT/sys/firmware/efi/efivars" "$ROOT/proc"
    : > "$ROOT/sys/firmware/efi/efivars/StubInfo-4a67b082-0a4c-41cf-b6c7-440b29bb8c4f"
    echo "root=UUID=abc BOOT_IMAGE=/vmlinuz rw initrd=\\initramfs.img quiet my.initrd=keep" > "$ROOT/proc/cmdline"
    stub uname "echo $KERNEL_VERSION"
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
# What set-edid.sh left, and a file of someone else in the same folder
mkdir -p "$ROOT/var/lib/virtual-monitor" "$ROOT/etc/systemd/system" "$ROOT/usr/local/lib/virtual-monitor"
cp "$EDID" "$ROOT/var/lib/virtual-monitor/edid.bin"
echo HDMI-A-1 > "$ROOT/var/lib/virtual-monitor/output"
: > "$ROOT/var/lib/virtual-monitor/other"
: > "$ROOT/etc/systemd/system/virtual-monitor-edid.service"
: > "$ROOT/usr/local/lib/virtual-monitor/set-edid.sh"
stub systemctl
run_script "$SCRIPT" "$EDID"
status_is 0 "installs on Armbian"
for file in var/lib/virtual-monitor/edid.bin var/lib/virtual-monitor/output etc/systemd/system/virtual-monitor-edid.service usr/local/lib/virtual-monitor/set-edid.sh; do
    check "undoes set-edid.sh: removes $file" test ! -e "$ROOT/$file"
done

called "systemctl disable --quiet virtual-monitor-edid.service"
check "leaves the other files of the folder" test -e "$ROOT/var/lib/virtual-monitor/other"
contains "$OUTPUT" "The kept EDID is gone; the installed one comes back at the next boot." "says the EDID set without reboot is gone"
check "copies the EDID" cmp "$EDID" "$ROOT/usr/lib/firmware/edid/virtual-monitor.bin"
check "initramfs hook is executable" test -x "$ROOT/etc/initramfs-tools/hooks/edid-virtual-monitor"
contains "$ROOT/etc/initramfs-tools/hooks/edid-virtual-monitor" 'cp /usr/lib/firmware/edid/virtual-monitor.bin "${DESTDIR}/usr/lib/firmware/edid/"' "hook copies the EDID into the image"
check "the hook is exactly the expected script" test "$(cat "$ROOT/etc/initramfs-tools/hooks/edid-virtual-monitor")" = "$(printf '%s\n' '#!/bin/sh' 'PREREQ=""' 'prereqs() { echo "$PREREQ"; }' 'case "$1" in prereqs) prereqs; exit 0 ;; esac' 'mkdir -p "${DESTDIR}/usr/lib/firmware/edid"' 'cp /usr/lib/firmware/edid/virtual-monitor.bin "${DESTDIR}/usr/lib/firmware/edid/"')"
check "without dracut, creates no dracut configuration" test ! -e "$ROOT/etc/dracut.conf.d"
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

armbian "extraargs=video=HDMI-A-1:D drm.edid_firmware=HDMI-A-1:edid/old.bin"
run_script "$SCRIPT" "$EDID"
check "replaces old parameters leaving no leading space" test "$(line '^extraargs=' "$ROOT/boot/armbianEnv.txt")" = "extraargs=$PARAMETERS"

armbian "# no extraargs"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs without an extraargs line"
check "creates the extraargs line" test "$(line '^extraargs=' "$ROOT/boot/armbianEnv.txt")" = "extraargs=$PARAMETERS"
check "creates the line only once" test "$(grep -c '^extraargs=' "$ROOT/boot/armbianEnv.txt")" = 1

armbian $'#extraargs= video=HDMI-A-1:D drm.edid_firmware=HDMI-A-1:edid/old.bin\nextraargs=cma=256M'
run_script "$SCRIPT" "$EDID"
check "changes the extraargs line, not a commented one" test "$(cat "$ROOT/boot/armbianEnv.txt")" = "$(printf '%s\n' 'verbosity=1' '#extraargs= video=HDMI-A-1:D drm.edid_firmware=HDMI-A-1:edid/old.bin' "extraargs=cma=256M $PARAMETERS" 'rootdev=UUID=abc')"

armbian "#extraargs=cma=256M"
run_script "$SCRIPT" "$EDID"
check "a commented extraargs line is not the setting" test "$(cat "$ROOT/boot/armbianEnv.txt")" = "$(printf '%s\n' 'verbosity=1' '#extraargs=cma=256M' 'rootdev=UUID=abc' "extraargs=$PARAMETERS")"

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

grub "quiet video=HDMI-A-1:D drm.edid_firmware=HDMI-A-1:edid/old.bin splash"
run_script "$SCRIPT" "$EDID"
check "replaces old parameters in GRUB" test "$(line '^GRUB_CMDLINE_LINUX_DEFAULT=' "$ROOT/etc/default/grub")" = "GRUB_CMDLINE_LINUX_DEFAULT=\"quiet splash $PARAMETERS\""

grub "quiet my.drm.edid_firmware=keep"
run_script "$SCRIPT" "$EDID"
check "keeps a parameter that only ends with the EDID option" test "$(line '^GRUB_CMDLINE_LINUX_DEFAULT=' "$ROOT/etc/default/grub")" = "GRUB_CMDLINE_LINUX_DEFAULT=\"quiet my.drm.edid_firmware=keep $PARAMETERS\""

grub "quiet"
: > "$ROOT/etc/default/grub.d"
run_script "$SCRIPT" "$EDID"
status_is 0 "a file named grub.d is no drop-in folder"
check "with a file named grub.d, sets /etc/default/grub" test "$(line '^GRUB_CMDLINE_LINUX_DEFAULT=' "$ROOT/etc/default/grub")" = "GRUB_CMDLINE_LINUX_DEFAULT=\"quiet $PARAMETERS\""

echo "# GRUB drop-in (Debian, Ubuntu)"
grub_drop_in "quiet drm.edid_firmware=HDMI-A-1:edid/old.bin"
printf '#GRUB_CMDLINE_LINUX_DEFAULT="quiet drm.edid_firmware=HDMI-A-1:edid/example.bin"\n' >> "$ROOT/etc/default/grub"
run_script "$SCRIPT" "$EDID"
check "removes the old parameters from GRUB, not from a comment" test "$(cat "$ROOT/etc/default/grub")" = "$(printf '%s\n' 'GRUB_TIMEOUT=5' 'GRUB_CMDLINE_LINUX_DEFAULT="quiet"' '#GRUB_CMDLINE_LINUX_DEFAULT="quiet drm.edid_firmware=HDMI-A-1:edid/example.bin"')"

grub_drop_in "quiet splash"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs with a grub.d folder"
called "update-grub"
contains "$OUTPUT" "Adjusting the kernel parameters in $DROP_IN" "says it writes the drop-in"
check "writes the parameters in a drop-in" test "$(line '^GRUB_CMDLINE_LINUX_DEFAULT=' "$DROP_IN")" = "GRUB_CMDLINE_LINUX_DEFAULT=\"\$GRUB_CMDLINE_LINUX_DEFAULT $PARAMETERS\""
check "adds to what the other grub.d files set" test "$(grub_command_line)" = "console=tty1 $PARAMETERS"
check "leaves /etc/default/grub as it was" grep -qx 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"' "$ROOT/etc/default/grub"
check "keeps no backup of an unchanged GRUB" test ! -e "$ROOT/etc/default/grub.before-edid"

run_script "$SCRIPT" "$EDID"
check "does not duplicate the drop-in line" test "$(grep -c '^GRUB_CMDLINE_LINUX_DEFAULT=' "$DROP_IN")" = 1
check "does not duplicate the parameters" test "$(grub_command_line)" = "console=tty1 $PARAMETERS"

grub_drop_in "quiet $PARAMETERS splash"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs over an earlier version"
check "removes the parameters an earlier version wrote in GRUB" grep -qx 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"' "$ROOT/etc/default/grub"
check "keeps the GRUB of the earlier version" grep -qx "GRUB_CMDLINE_LINUX_DEFAULT=\"quiet $PARAMETERS splash\"" "$ROOT/etc/default/grub.before-edid"

grub_drop_in "$PARAMETERS"
run_script "$SCRIPT" "$EDID"
check "leaves an empty GRUB line empty" grep -qx 'GRUB_CMDLINE_LINUX_DEFAULT=""' "$ROOT/etc/default/grub"

grub_drop_in "quiet"
rm "$STUBS/update-grub"
stub grub2-mkconfig
run_script "$SCRIPT" "$EDID"
status_is 0 "without update-grub, ignores grub.d"
check "writes no drop-in" test ! -e "$DROP_IN"
check "changes /etc/default/grub" test "$(line '^GRUB_CMDLINE_LINUX_DEFAULT=' "$ROOT/etc/default/grub")" = "GRUB_CMDLINE_LINUX_DEFAULT=\"quiet $PARAMETERS\""

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

pop ', "drm.edid_firmware=HDMI-A-1:edid/old.bin", "video=HDMI-A-1:D", "video=DP-2:e"'
echo '{"user": {"kernel_options": ["quiet"]}}' > "$ROOT/etc/kernelstub/configuration.before-edid"
run_script "$SCRIPT" "$EDID"
status_is 0 "reinstalls with kernelstub"
called "kernelstub -d drm.edid_firmware=HDMI-A-1:edid/old.bin video=HDMI-A-1:D"
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
contains "$ROOT/etc/dracut.conf.d/90-edid-virtual-monitor.conf" "edid/virtual-monitor.bin" "creates the dracut folder and configuration"

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

pop ', "drm.edid_firmware=HDMI-A-1:edid/old.bin", "drm.edid_firmware=HDMI-A-1:edid/old.bin"'
run_script "$SCRIPT" "$EDID"
check "removes a parameter listed twice once" grep -qx "kernelstub -d drm.edid_firmware=HDMI-A-1:edid/old.bin" "$CALLS"

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
stub lsinitrd 'echo nothing'
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

fedora "rhgb quiet drm.edid_firmware=HDMI-A-1:edid/old.bin video=HDMI-A-1:D video=DP-2:e"
run_script "$SCRIPT" "$EDID"
status_is 0 "reinstalls on Fedora"
called "grubby --update-kernel=ALL --remove-args=drm.edid_firmware=HDMI-A-1:edid/old.bin video=HDMI-A-1:D"
called "grubby --update-kernel=ALL --args=$PARAMETERS"

fedora "rhgb quiet"
printf '#GRUB_CMDLINE_LINUX_DEFAULT="quiet video=HDMI-A-1:D"\n' >> "$ROOT/etc/default/grub"
run_script "$SCRIPT" "$EDID"
check "a commented GRUB_CMDLINE_LINUX_DEFAULT is not the setting" test "$(cat "$ROOT/etc/default/grub")" = "$(printf '%s\n' 'GRUB_TIMEOUT=5' 'GRUB_CMDLINE_LINUX="rhgb quiet"' '#GRUB_CMDLINE_LINUX_DEFAULT="quiet video=HDMI-A-1:D"' "GRUB_CMDLINE_LINUX_DEFAULT=\"$PARAMETERS\"")"

fedora "nodrm.edid_firmware=keep drm.edid_firmware=HDMI-A-1:edid/old.bin quiet drm.edid_firmware=HDMI-A-1:edid/old.bin"
run_script "$SCRIPT" "$EDID"
check "removes each old parameter once, and only those" grep -qx "grubby --update-kernel=ALL --remove-args=drm.edid_firmware=HDMI-A-1:edid/old.bin" "$CALLS"

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
printf 'title Fallback\nlinux /vmlinuz-linux\n#options quiet\n' > "$ROOT/efi/loader/entries/fallback.conf"
echo "root=UUID=abc rw" > "$ROOT/etc/kernel/cmdline"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs with systemd-boot"
check "replaces the parameters in the entry" grep -qx "options root=UUID=abc rw $PARAMETERS" "$ROOT/boot/loader/entries/arch.conf"
check "keeps the other lines of the entry" grep -qx 'linux /vmlinuz-linux' "$ROOT/boot/loader/entries/arch.conf"
check "adds an options line to an entry without one" grep -qx "options $PARAMETERS" "$ROOT/efi/loader/entries/fallback.conf"
check "leaves a commented options line alone" grep -qx "#options quiet" "$ROOT/efi/loader/entries/fallback.conf"
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
raspberry boot/firmware/cmdline.txt "console=serial0,115200 root=PARTUUID=abc rootwait drm.edid_firmware=HDMI-A-1:edid/old.bin"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs on Raspberry Pi OS"
check "replaces the parameters in cmdline.txt" test "$(cat "$ROOT/boot/firmware/cmdline.txt")" = "console=serial0,115200 root=PARTUUID=abc rootwait $PARAMETERS"
check "keeps the original cmdline.txt" grep -q 'edid/old.bin' "$ROOT/boot/firmware/cmdline.txt.before-edid"

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
check "keeps the original u-boot defaults" grep -qx 'U_BOOT_PARAMETERS="ro quiet video=HDMI-A-1:D"' "$ROOT/etc/default/u-boot.before-edid"
called "u-boot-update"

no_boot_image
mkdir -p "$ROOT/etc/default" "$ROOT/boot/extlinux"
printf '%s\n' 'U_BOOT_MENU_LABEL="Debian"' '#U_BOOT_PARAMETERS="quiet"' > "$ROOT/etc/default/u-boot"
echo "  append root=/dev/sda1" > "$ROOT/boot/extlinux/extlinux.conf"
stub u-boot-update
run_script "$SCRIPT" "$EDID"
status_is 0 "installs with u-boot-menu and no U_BOOT_PARAMETERS"
check "starts from the u-boot-update default, leaving the comment alone" test "$(cat "$ROOT/etc/default/u-boot")" = "$(printf '%s\n' 'U_BOOT_MENU_LABEL="Debian"' '#U_BOOT_PARAMETERS="quiet"' "U_BOOT_PARAMETERS=\"ro quiet $PARAMETERS\"")"
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
printf 'label linux\n  kernel /Image\n  APPEND root=/dev/mmcblk0p2 video=HDMI-A-1:D\n  #append root=/dev/sda1\nlabel rescue\n  append root=/dev/mmcblk0p2 single\n' > "$ROOT/boot/extlinux/extlinux.conf"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs with extlinux.conf"
check "changes every append line" test "$(grep -ci "append.*$PARAMETERS" "$ROOT/boot/extlinux/extlinux.conf")" = 2
check "leaves a commented append line alone" grep -qx "  #append root=/dev/sda1" "$ROOT/boot/extlinux/extlinux.conf"
check "keeps the case and indentation" grep -qx "  APPEND root=/dev/mmcblk0p2 $PARAMETERS" "$ROOT/boot/extlinux/extlinux.conf"
check "keeps the original extlinux.conf" grep -q 'video=HDMI-A-1:D' "$ROOT/boot/extlinux/extlinux.conf.before-edid"

no_boot_image
mkdir -p "$ROOT/boot/extlinux"
printf 'label linux\n  kernel /Image\n' > "$ROOT/boot/extlinux/extlinux.conf"
run_script "$SCRIPT" "$EDID"
status_is 1 "fails with an extlinux.conf without append"
contains "$ERRORS" "has no append line" "says there is no append line"
check "keeps no backup of extlinux.conf" test ! -e "$ROOT/boot/extlinux/extlinux.conf.before-edid"

echo "# UKI"
uki
stub dracut
stub kernel-install
mkdir -p "$ROOT/usr/lib/kernel"
printf '#layout=uki\n' > "$ROOT/usr/lib/kernel/install.conf"
run_script "$SCRIPT" "$EDID"
status_is 1 "stops on a UKI the machine did not build"
contains "$ERRORS" "boots a UKI that it did not build" "says why it stops"
contains "$ERRORS" "Nothing was changed." "says nothing was changed"
check "copies no EDID" test ! -e "$ROOT/usr/lib/firmware"
check "writes no dracut hook" test ! -e "$ROOT/etc/dracut.conf.d"
not_called dracut
not_called kernel-install

uki
stub mkinitcpio
mkdir -p "$ROOT/etc/mkinitcpio.d"
printf 'PRESETS=(default)\n#default_uki="/efi/EFI/Linux/arch-linux.efi"\n' > "$ROOT/etc/mkinitcpio.d/linux.preset"
run_script "$SCRIPT" "$EDID"
status_is 1 "stops when the presets build no UKI"
not_called "mkinitcpio -P"

uki
stub mkinitcpio
mkdir -p "$ROOT/etc/mkinitcpio.d"
printf 'PRESETS=(default)\ndefault_uki="/efi/EFI/Linux/arch-linux.efi"\n' > "$ROOT/etc/mkinitcpio.d/linux.preset"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs in a UKI that mkinitcpio builds"
check "writes the command line from the running one" test "$(cat "$ROOT/etc/kernel/cmdline")" = "root=UUID=abc rw quiet my.initrd=keep $PARAMETERS"
check "keeps the command line from before" test "$(cat "$ROOT/etc/kernel/cmdline.before-edid")" = "root=UUID=abc rw quiet my.initrd=keep"
contains "$ROOT/etc/mkinitcpio.conf.d/virtual-monitor.conf" "FILES+=(/usr/lib/firmware/edid/virtual-monitor.bin)" "adds the EDID to the UKI initrd"
contains "$OUTPUT" "Building the UKI" "says it builds the UKI"
called "mkinitcpio -P"
not_contains "$OUTPUT" "Checking that the EDID is in the image" "does not look for an initramfs image"

uki
stub dracut
stub kernel-install
mkdir -p "$ROOT/etc/kernel"
printf 'layout=uki\n' > "$ROOT/etc/kernel/install.conf"
printf 'root=UUID=abc rw video=HDMI-A-1:D\n' > "$ROOT/etc/kernel/cmdline"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs in a UKI that kernel-install builds"
check "replaces the parameters in /etc/kernel/cmdline" test "$(cat "$ROOT/etc/kernel/cmdline")" = "root=UUID=abc rw $PARAMETERS"
contains "$ROOT/etc/dracut.conf.d/90-edid-virtual-monitor.conf" "virtual-monitor.bin" "adds the EDID to dracut"
called "kernel-install add $KERNEL_VERSION $ROOT/usr/lib/modules/$KERNEL_VERSION/vmlinuz"
not_called "dracut -f"

uki
stub kernel-install
mkdir -p "$ROOT/usr/lib/kernel"
printf 'layout=uki\n' > "$ROOT/usr/lib/kernel/install.conf"
run_script "$SCRIPT" "$EDID"
status_is 0 "reads layout=uki from /usr/lib/kernel/install.conf"
called "kernel-install add $KERNEL_VERSION $ROOT/usr/lib/modules/$KERNEL_VERSION/vmlinuz"

echo "# UKI without the tool that builds it"
uki
mkdir -p "$ROOT/etc/mkinitcpio.d"
printf 'default_uki="/efi/EFI/Linux/arch-linux.efi"\n' > "$ROOT/etc/mkinitcpio.d/linux.preset"
run_script "$SCRIPT" "$EDID"
status_is 1 "a preset with a UKI but no mkinitcpio counts as a ready UKI"

uki
mkdir -p "$ROOT/etc/kernel"
printf 'layout=uki\n' > "$ROOT/etc/kernel/install.conf"
run_script "$SCRIPT" "$EDID"
status_is 1 "layout=uki without kernel-install counts as a ready UKI"

echo "# Raspberry Pi with both cmdline.txt files"
raspberry boot/firmware/cmdline.txt "root=/dev/first"
printf 'root=/dev/second\n' > "$ROOT/boot/cmdline.txt"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs with both files"
check "changes the firmware one" test "$(cat "$ROOT/boot/firmware/cmdline.txt")" = "root=/dev/first $PARAMETERS"
check "leaves /boot/cmdline.txt alone" test "$(cat "$ROOT/boot/cmdline.txt")" = "root=/dev/second"

echo "# failures and the real machine"
new_case
run_script "$SCRIPT" "$EDID" "bad;HDMI-A-1"
status_is 1 "a connector with extra text before it is rejected"

grub "quiet"
stub dracut 'exit 1'
run_script "$SCRIPT" "$EDID"
status_is 1 "stops when the boot image fails to build"
check "leaves GRUB alone after the failure" grep -qx 'GRUB_CMDLINE_LINUX_DEFAULT="quiet"' "$ROOT/etc/default/grub"
not_called update-grub

new_case
UNSET_ROOT=1 run_script "$SCRIPT" "$EDID" "bad connector"
status_is 1 "without ROOT, runs up to the connector check"
contains "$ERRORS" "Invalid CONNECTOR: bad connector" "without ROOT, works on /"

echo "# boot loader"
new_case
stub uname "echo $KERNEL_VERSION"
stub update-initramfs
stub lsinitramfs 'echo usr/lib/firmware/edid/virtual-monitor.bin'
run_script "$SCRIPT" "$EDID"
status_is 1 "fails without a known boot setup"
contains "$ERRORS" "No boot setup found" "says no boot setup was found"
contains "$ERRORS" "Add to the kernel command line: $PARAMETERS" "shows the parameters to set by hand"

echo "# folders with the name of a file"
# systemd-boot, the last boot setup tried, with a folder where an earlier one keeps its file
loader_with_folder() {
    no_boot_image
    stub kernelstub
    stub u-boot-update
    mkdir -p "$ROOT/boot/loader/entries" "$ROOT/$1"
    printf 'options quiet\n' > "$ROOT/boot/loader/entries/linux.conf"
}

for folder in boot/armbianEnv.txt boot/firmware/cmdline.txt etc/kernelstub/configuration etc/default/grub \
    etc/default/u-boot boot/extlinux/extlinux.conf etc/kernel/cmdline sys/firmware/efi/efivars/StubInfo-4a67b082-0a4c-41cf-b6c7-440b29bb8c4f; do
    loader_with_folder "$folder"
    run_script "$SCRIPT" "$EDID"
    status_is 0 "a folder at $folder is not that file"
    check "with a folder at $folder, sets the systemd-boot entry" grep -qx "options quiet $PARAMETERS" "$ROOT/boot/loader/entries/linux.conf"
done

loader_with_folder boot/loader/entries/folder.conf
run_script "$SCRIPT" "$EDID"
status_is 0 "skips a folder among the boot entries"

no_boot_image
mkdir -p "$ROOT/boot/loader/entries/folder.conf"
run_script "$SCRIPT" "$EDID"
status_is 1 "a folder alone is no boot entry"
contains "$ERRORS" "No boot setup found" "a folder alone is no boot setup"

loader_with_folder boot/loader/entries/linux.conf.before-edid
run_script "$SCRIPT" "$EDID"
check "anything at the name of the saved original stays as it is" test -z "$(ls "$ROOT/boot/loader/entries/linux.conf.before-edid")"

new_case
mkdir -p "$CASE/edid.bin"
run_script "$SCRIPT" "$CASE/edid.bin"
status_is 1 "a folder is no EDID"
contains "$ERRORS" "edid.bin not found" "says the folder is not the EDID"

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
