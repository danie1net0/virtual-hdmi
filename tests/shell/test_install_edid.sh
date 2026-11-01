#!/usr/bin/env bash
# Tests scripts/install-edid.sh with the system root in a temporary folder.
source "$(dirname "$0")/lib.sh"

SCRIPT="$PROJECT/scripts/install-edid.sh"
EDID="$PROJECT/edid/ultrawide-rockchip.bin"
PARAMS="drm.edid_firmware=HDMI-A-1:edid/ultrawide.bin video=HDMI-A-1:e"
KVER="6.1.0-test"

# Armbian kernel and tools (initramfs-tools); the EDID shows up in the image
armbian() {
    new_case
    mkdir -p "$ROOT/boot" "$ROOT/etc/initramfs-tools/hooks"
    printf 'verbosity=1\n%s\nrootdev=UUID=abc\n' "$1" > "$ROOT/boot/armbianEnv.txt"
    stub uname "echo $KVER"
    stub update-initramfs
    stub lsinitramfs 'echo usr/lib/firmware/edid/ultrawide.bin'
}

# Fedora/Lenovo kernel and tools (dracut + GRUB)
grub() {
    new_case
    mkdir -p "$ROOT/etc/default" "$ROOT/etc/dracut.conf.d"
    printf 'GRUB_TIMEOUT=5\nGRUB_CMDLINE_LINUX_DEFAULT="%s"\n' "$1" > "$ROOT/etc/default/grub"
    stub uname "echo $KVER"
    stub dracut
    stub lsinitrd 'echo usr/lib/firmware/edid/ultrawide.bin'
    stub update-grub
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
check "does not copy an invalid file" test ! -e "$ROOT/usr/lib/firmware/edid/ultrawide.bin"

echo "# Armbian (Orange Pi)"
armbian "extraargs=cma=256M"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs on Armbian"
check "copies the EDID" cmp "$EDID" "$ROOT/usr/lib/firmware/edid/ultrawide.bin"
check "initramfs hook is executable" test -x "$ROOT/etc/initramfs-tools/hooks/edid-ultrawide"
contains "$ROOT/etc/initramfs-tools/hooks/edid-ultrawide" 'cp /usr/lib/firmware/edid/ultrawide.bin "${DESTDIR}/usr/lib/firmware/edid/"' "hook copies the EDID into the image"
check "without dracut.conf.d, creates no dracut config" test ! -e "$ROOT/etc/dracut.conf.d"
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

echo "# GRUB (Lenovo)"
grub "quiet splash"
run_script "$SCRIPT" "$EDID"
status_is 0 "installs with GRUB and dracut"
contains "$ROOT/etc/dracut.conf.d/90-edid-ultrawide.conf" 'install_items+=" /usr/lib/firmware/edid/ultrawide.bin "' "adds the EDID to dracut"
check "without initramfs-tools, creates no hook" test ! -e "$ROOT/etc/initramfs-tools"
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

armbian "extraargs=cma=256M"
rm "$STUBS/lsinitramfs"
run_script "$SCRIPT" "$EDID"
status_is 1 "fails without lsinitrd and lsinitramfs"

echo "# boot loader"
new_case
stub uname "echo $KVER"
stub update-initramfs
stub lsinitramfs 'echo usr/lib/firmware/edid/ultrawide.bin'
run_script "$SCRIPT" "$EDID"
status_is 1 "fails without armbianEnv and GRUB"
contains "$ERRS" "Add to the kernel command line: $PARAMS" "shows the parameters to set by hand"

echo "# EDID path"
armbian "extraargs=cma=256M"
run_script "$SCRIPT"
status_is 0 "no argument uses the default EDID"
check "default EDID is the project ultrawide.bin" cmp "$PROJECT/edid/ultrawide.bin" "$ROOT/usr/lib/firmware/edid/ultrawide.bin"

armbian "extraargs=cma=256M"
cd "$PROJECT" || exit 1
run_script "$SCRIPT" edid/ultrawide-rockchip.bin
cd - > /dev/null || exit 1
status_is 0 "relative path counts from the current folder"
check "copies the EDID from the relative path" cmp "$EDID" "$ROOT/usr/lib/firmware/edid/ultrawide.bin"

summary
