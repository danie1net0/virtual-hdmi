#!/usr/bin/env bash
# Real boot test: starts a distribution's cloud image in QEMU, runs scripts/install-edid.sh in it,
# reboots, and checks that the kernel read the EDID. The VM has a virtio-gpu card, whose output
# Virtual-1 gets its EDID the same way as HDMI or DisplayPort outputs.
#
# Usage (macOS with QEMU, `brew install qemu`; not run in CI):
#   bash tests/boot/run.sh IMAGE [aarch64|x86_64]
#
# IMAGE is a cloud image with cloud-init; it is not changed (the VM writes to an overlay). Tested
# images: Fedora Cloud Base Generic, Debian generic (not genericcloud, whose kernel has no DRM),
# Ubuntu server cloudimg, openSUSE Tumbleweed Minimal-VM Cloud (aarch64) and Arch cloudimg
# (x86_64, emulated: several minutes).
#
# Prints what the VM reported and exits with 0 only when the EDID after the reboot is the
# project's. WORK_FOLDER (default ~/Library/Caches/virtual-monitor-boot-tests/<image name>) keeps
# the disk, serial.log (the console) and report.log; TIME_LIMIT (default 1800) is in seconds.

set -euo pipefail

PROJECT_FOLDER="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE="${1:?Usage: bash tests/boot/run.sh IMAGE [aarch64|x86_64]}"
ARCHITECTURE="${2:-aarch64}"
WORK_FOLDER="${WORK_FOLDER:-$HOME/Library/Caches/virtual-monitor-boot-tests/$(basename "$IMAGE")}"
TIME_LIMIT="${TIME_LIMIT:-1800}"
FIRMWARE_FOLDER="$(brew --prefix qemu)/share/qemu"

[[ -f "$IMAGE" ]] || { echo "$IMAGE not found." >&2; exit 1; }

# The VM reports through a virtio serial port: a getty on the console would hang up its output
write_user_data() {
    cat <<'USERDATA'
#cloud-config
write_files:
  - path: /usr/local/bin/virtual-monitor-setup
    permissions: "0755"
    content: |
      #!/bin/bash
      exec >> /dev/virtio-ports/report 2>&1
      mkdir -p /root/project /mnt/seed
      mount -o ro "$(blkid -L cidata || blkid -L CIDATA)" /mnt/seed
      tar -C /root/project -xzf "$(find /mnt/seed -maxdepth 1 -iname 'project*' | head -n 1)"
      echo "VM-BEFORE modes: $(cat /sys/class/drm/card*-Virtual-1/modes | tr '\n' ' ')"
      systemctl enable virtual-monitor-check.service
      if ! bash /root/project/scripts/install-edid.sh /root/project/edid/virtual-monitor.bin Virtual-1; then
          echo "VM-RESULT install-failed"
          systemctl poweroff
          exit 1
      fi
      touch /root/virtual-monitor-installed
      systemctl reboot
  - path: /usr/local/bin/virtual-monitor-check
    permissions: "0755"
    content: |
      #!/bin/bash
      exec >> /dev/virtio-ports/report 2>&1
      echo "VM-CHECK cmdline: $(cat /proc/cmdline)"
      expected="$(sha256sum < /root/project/edid/virtual-monitor.bin)"
      result=fail
      for connector in /sys/class/drm/card*-Virtual-1; do
          echo "VM-CHECK $connector status: $(cat "$connector/status")"
          echo "VM-CHECK $connector modes: $(tr '\n' ' ' < "$connector/modes")"
          [[ "$(sha256sum < "$connector/edid")" == "$expected" ]] && result=ok
      done
      echo "VM-RESULT $result"
      systemctl poweroff
  - path: /etc/systemd/system/virtual-monitor-check.service
    content: |
      [Unit]
      Description=Check the virtual monitor EDID
      ConditionPathExists=/root/virtual-monitor-installed
      After=multi-user.target
      [Service]
      Type=oneshot
      ExecStart=/usr/local/bin/virtual-monitor-check
      [Install]
      WantedBy=multi-user.target
runcmd:
  - [bash, /usr/local/bin/virtual-monitor-setup]
USERDATA
}

prepare() {
    rm -rf "$WORK_FOLDER"
    mkdir -p "$WORK_FOLDER/seed"
    qemu-img create -q -f qcow2 -b "$(cd "$(dirname "$IMAGE")" && pwd)/$(basename "$IMAGE")" -F qcow2 "$WORK_FOLDER/disk.qcow2" 20G
    COPYFILE_DISABLE=1 tar --no-xattrs -C "$PROJECT_FOLDER" -czf "$WORK_FOLDER/seed/project.tar.gz" scripts edid
    echo "instance-id: virtual-monitor-boot-test" > "$WORK_FOLDER/seed/meta-data"
    write_user_data > "$WORK_FOLDER/seed/user-data"
    hdiutil makehybrid -quiet -iso -joliet -default-volume-name cidata -o "$WORK_FOLDER/seed.iso" "$WORK_FOLDER/seed"
}

boot() {
    local emulator=qemu-system-aarch64
    local machine=(-M virt -accel hvf -cpu host -bios "$FIRMWARE_FOLDER/edk2-aarch64-code.fd")

    if [[ "$ARCHITECTURE" == "x86_64" ]]; then
        emulator=qemu-system-x86_64
        machine=(-M q35 -accel tcg -cpu max -drive "if=pflash,format=raw,readonly=on,file=$FIRMWARE_FOLDER/edk2-x86_64-code.fd")
    fi

    "$emulator" "${machine[@]}" -smp 2 -m 2048 \
        -drive "file=$WORK_FOLDER/disk.qcow2,if=virtio,format=qcow2" \
        -drive "file=$WORK_FOLDER/seed.iso,if=virtio,format=raw,readonly=on" \
        -device virtio-gpu-pci -display none \
        -nic user,model=virtio-net-pci \
        -device virtio-serial-pci -chardev "file,id=report,path=$WORK_FOLDER/report.log" \
        -device virtserialport,chardev=report,name=report \
        -serial "file:$WORK_FOLDER/serial.log" -monitor none &
    local emulator_process=$!

    # Its own output goes nowhere, so that a sleep left behind does not keep a pipe open
    ( sleep "$TIME_LIMIT"; kill "$emulator_process" ) > /dev/null 2>&1 &
    local watchdog_process=$!
    wait "$emulator_process" || true
    kill "$watchdog_process" 2>/dev/null || true
}

prepare
boot
cat "$WORK_FOLDER/report.log"
grep -qx 'VM-RESULT ok' "$WORK_FOLDER/report.log"
