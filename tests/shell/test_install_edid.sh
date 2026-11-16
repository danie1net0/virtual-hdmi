#!/usr/bin/env bash
# Tests scripts/install-edid.sh with the system root in a temporary folder.
source "$(dirname "$0")/lib.sh"

SCRIPT="$PROJECT/scripts/install-edid.sh"
EDID="$PROJECT/edid/virtual-monitor.bin"
PARAMS="drm.edid_firmware=HDMI-A-1:edid/virtual-monitor.bin video=HDMI-A-1:e"
KVER="6.1.0-test"

# Armbian kernel and tools (initramfs-tools); the EDID shows up in the image
armbian() {
    new_case
    mkdir -p "$ROOT/boot" "$ROOT/etc/initramfs-tools/hooks"
    printf 'verbosity=1\n%s\nrootdev=UUID=abc\n' "$1" > "$ROOT/boot/armbianEnv.txt"
    stub uname "echo $KVER"
    stub update-initramfs
    stub lsinitramfs 'echo usr/lib/firmware/edid/virtual-monitor.bin'
}

# Fedora/Lenovo kernel and tools (dracut + GRUB)
grub() {
    new_case
    mkdir -p "$ROOT/etc/default" "$ROOT/etc/dracut.conf.d"
    printf 'GRUB_TIMEOUT=5\nGRUB_CMDLINE_LINUX_DEFAULT="%s"\n' "$1" > "$ROOT/etc/default/grub"
    stub uname "echo $KVER"
    stub dracut
    stub lsinitrd 'echo usr/lib/firmware/edid/virtual-monitor.bin'
    stub update-grub
}

# Pop!_OS: kernelstub (systemd-boot) and initramfs-tools; the configuration keeps the options in JSON
pop() {
    new_case
    mkdir -p "$ROOT/etc/kernelstub" "$ROOT/etc/initramfs-tools/hooks"
    printf '{"user": {"kernel_options": ["quiet", "splash"%s]}}\n' "$1" > "$ROOT/etc/kernelstub/configuration"
    stub uname "echo $KVER"
    stub update-initramfs
    stub lsinitramfs 'echo usr/lib/firmware/edid/virtual-monitor.bin'
    stub kernelstub
}

line() {
    grep "$1" "$2"
}

echo "# permissions and input"
new_case
FAKE_UID=1000 run_script "$SCRIPT" "$EDID"
status_is 1 "fails without root"
contains "$ERRS" "Run with sudo." "asks for sudo"
check "copies nothing without root" test ! -e "$ROOT/usr"

new_case
run_script "$SCRIPT" "$CASE/missing.bin"
status_is 1 "missing EDID fails"
contains "$ERRS" "missing.bin not found" "says which file is missing"

new_case
printf 'short' > "$CASE/short.bin"
run_script "$SCRIPT" "$CASE/short.bin"
status_is 1 "a file that is not 256 bytes fails"
contains "$ERRS" "is not 256 bytes" "explains the size"
check "does not copy an invalid file" test ! -e "$ROOT/usr/lib/firmware/edid/virtual-monitor.bin"

echo "# Armbian"
armbian "extraargs=cma=256M"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs on Armbian"
check "copies the EDID" cmp "$EDID" "$ROOT/usr/lib/firmware/edid/virtual-monitor.bin"
check "initramfs hook is executable" test -x "$ROOT/etc/initramfs-tools/hooks/edid-virtual-monitor"
contains "$ROOT/etc/initramfs-tools/hooks/edid-virtual-monitor" 'cp /usr/lib/firmware/edid/virtual-monitor.bin "${DESTDIR}/usr/lib/firmware/edid/"' "hook copies the EDID into the image"
check "without dracut, creates no dracut config" test ! -e "$ROOT/etc/dracut.conf.d"
called "update-initramfs -u -k $KVER"
called "lsinitramfs $ROOT/boot/initrd.img-$KVER"
check "appends the parameters to extraargs" test "$(line '^extraargs=' "$ROOT/boot/armbianEnv.txt")" = "extraargs=cma=256M $PARAMS"
check "keeps the other lines" grep -qx 'rootdev=UUID=abc' "$ROOT/boot/armbianEnv.txt"
check "keeps the original" test "$(line '^extraargs=' "$ROOT/boot/armbianEnv.txt.before-edid")" = "extraargs=cma=256M"
contains "$OUT" "ok (lsinitramfs)" "checks the image with lsinitramfs"
contains "$OUT" "Done" "ends with the reboot instruction"
not_called update-grub

run_script "$SCRIPT" "$EDID"
status_is 0 "reinstalls on Armbian"
check "does not duplicate the parameters" test "$(line '^extraargs=' "$ROOT/boot/armbianEnv.txt")" = "extraargs=cma=256M $PARAMS"
check "does not overwrite the saved original" test "$(line '^extraargs=' "$ROOT/boot/armbianEnv.txt.before-edid")" = "extraargs=cma=256M"

armbian "extraargs=drm.edid_firmware=HDMI-A-1:edid/velho.bin video=HDMI-A-1:D"
run_script "$SCRIPT" "$EDID"
check "replaces old parameters leaving no leading space" test "$(line '^extraargs=' "$ROOT/boot/armbianEnv.txt")" = "extraargs=$PARAMS"

armbian "# no extraargs"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs without an extraargs line"
check "creates the extraargs line" test "$(line '^extraargs=' "$ROOT/boot/armbianEnv.txt")" = "extraargs=$PARAMS"
check "creates the line only once" test "$(grep -c '^extraargs=' "$ROOT/boot/armbianEnv.txt")" = 1

echo "# GRUB"
grub "quiet splash"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs with GRUB and dracut"
contains "$ROOT/etc/dracut.conf.d/90-edid-virtual-monitor.conf" 'install_items+=" /usr/lib/firmware/edid/virtual-monitor.bin "' "adds the EDID to dracut"
check "without update-initramfs, creates no hook" test ! -e "$ROOT/etc/initramfs-tools"
called "dracut -f --kver $KVER"
called "lsinitrd --kver $KVER"
called "update-grub"
contains "$OUT" "ok (lsinitrd)" "checks the image with lsinitrd"
check "appends the parameters to GRUB" test "$(line '^GRUB_CMDLINE_LINUX_DEFAULT=' "$ROOT/etc/default/grub")" = "GRUB_CMDLINE_LINUX_DEFAULT=\"quiet splash $PARAMS\""
check "keeps the original GRUB" grep -qx 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"' "$ROOT/etc/default/grub.before-edid"
check "keeps the other GRUB lines" grep -qx 'GRUB_TIMEOUT=5' "$ROOT/etc/default/grub"

run_script "$SCRIPT" "$EDID"
check "does not duplicate the parameters in GRUB" test "$(line '^GRUB_CMDLINE_LINUX_DEFAULT=' "$ROOT/etc/default/grub")" = "GRUB_CMDLINE_LINUX_DEFAULT=\"quiet splash $PARAMS\""
check "does not overwrite the saved GRUB" grep -qx 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"' "$ROOT/etc/default/grub.before-edid"

grub ""
run_script "$SCRIPT" "$EDID"
check "empty GRUB has no leading space" test "$(line '^GRUB_CMDLINE_LINUX_DEFAULT=' "$ROOT/etc/default/grub")" = "GRUB_CMDLINE_LINUX_DEFAULT=\"$PARAMS\""

grub "quiet video=HDMI-A-1:D drm.edid_firmware=HDMI-A-1:edid/velho.bin splash"
run_script "$SCRIPT" "$EDID"
check "replaces old parameters in GRUB" test "$(line '^GRUB_CMDLINE_LINUX_DEFAULT=' "$ROOT/etc/default/grub")" = "GRUB_CMDLINE_LINUX_DEFAULT=\"quiet splash $PARAMS\""

echo "# kernelstub (Pop!_OS)"
pop ""
run_script "$SCRIPT" "$EDID"
status_is 0 "installs with kernelstub"
called "kernelstub -a $PARAMS"
not_called "kernelstub -d"
check "keeps the original kernelstub configuration" cmp "$ROOT/etc/kernelstub/configuration" "$ROOT/etc/kernelstub/configuration.before-edid"
called "update-initramfs -u -k $KVER"
contains "$OUT" "Adjusting the kernel parameters with kernelstub" "says it uses kernelstub"
not_called update-grub

pop ', "drm.edid_firmware=HDMI-A-1:edid/velho.bin", "video=HDMI-A-1:D", "video=DP-2:e"'
echo '{"user": {"kernel_options": ["quiet"]}}' > "$ROOT/etc/kernelstub/configuration.before-edid"
run_script "$SCRIPT" "$EDID"
status_is 0 "reinstalls with kernelstub"
called "kernelstub -d drm.edid_firmware=HDMI-A-1:edid/velho.bin video=HDMI-A-1:D"
called "kernelstub -a $PARAMS"
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
contains "$OUT" "Done: HDMI-A-2 gets the virtual monitor" "says which output gets it"

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
contains "$ERRS" "Invalid CONNECTOR" "says the connector is invalid"
check "copies nothing with an invalid connector" test ! -e "$ROOT/usr"

echo "# boot image"
grub "quiet"
rm "$STUBS/dracut"
run_script "$SCRIPT" "$EDID"
status_is 1 "fails without update-initramfs and dracut"
contains "$ERRS" "Neither update-initramfs nor dracut" "explains the missing tool"
not_called update-grub

armbian "extraargs=cma=256M"
stub lsinitramfs 'echo usr/lib/modules'
run_script "$SCRIPT" "$EDID"
status_is 1 "EDID outside the image fails"
contains "$ERRS" "stopping before touching the boot setup" "stops before the boot setup"
check "leaves armbianEnv alone" test "$(line '^extraargs=' "$ROOT/boot/armbianEnv.txt")" = "extraargs=cma=256M"
check "keeps no backup without changes" test ! -e "$ROOT/boot/armbianEnv.txt.before-edid"

armbian "extraargs=cma=256M"
stub lsinitrd 'echo nada'
run_script "$SCRIPT" "$EDID"
status_is 0 "lsinitrd without the EDID falls back to lsinitramfs"
contains "$OUT" "ok (lsinitramfs)" "uses lsinitramfs after lsinitrd"

# A real image lists thousands of files after the EDID; grep -q would stop reading and the lister
# would die of SIGPIPE, which pipefail turns into a failed check
armbian "extraargs=cma=256M"
stub lsinitramfs 'echo usr/lib/firmware/edid/virtual-monitor.bin; index=0; while [ $index -lt 50000 ]; do echo usr/lib/modules/file-$index; index=$((index + 1)); done'
run_script "$SCRIPT" "$EDID"
status_is 0 "finds the EDID at the top of a long listing"
contains "$OUT" "ok (lsinitramfs)" "accepts the long listing"

armbian "extraargs=cma=256M"
stub lsinitramfs 'echo usr/lib/firmware/edid/virtual-monitor.bin; exit 1'
run_script "$SCRIPT" "$EDID"
status_is 0 "a lister that fails after printing the EDID still counts"

armbian "extraargs=cma=256M"
rm "$STUBS/lsinitramfs"
run_script "$SCRIPT" "$EDID"
status_is 1 "fails without lsinitrd and lsinitramfs"

echo "# boot loader"
new_case
stub uname "echo $KVER"
stub update-initramfs
stub lsinitramfs 'echo usr/lib/firmware/edid/virtual-monitor.bin'
run_script "$SCRIPT" "$EDID"
status_is 1 "fails without armbianEnv, kernelstub and GRUB"
contains "$ERRS" "Add to the kernel command line: $PARAMS" "shows the parameters to set by hand"

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
