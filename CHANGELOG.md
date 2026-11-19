# Changelog

Each `## vX.Y.Z` section becomes the GitLab release of that tag: CI creates the release from it when
the tag is pushed. Pin a version with `VERSION=vX.Y.Z` (see `get.sh`).

## v0.6.0 (2026-11-19)

- `--install-edid` works on more distributions and boot loaders. It sets the kernel parameters
  with grubby, grub2-mkconfig or grub-mkconfig when there is no update-grub, and edits the
  Raspberry Pi `cmdline.txt`, U-Boot's `/etc/default/u-boot` or `extlinux.conf`, and the
  systemd-boot loader entries. On Arch it builds the boot image with mkinitcpio; with no boot
  image tool it only copies the EDID, which the kernel reads from `/usr/lib/firmware`.
- On Debian and Ubuntu the parameters go in `/etc/default/grub.d/99-virtual-monitor.cfg`. Ubuntu's
  cloud image sets the kernel command line again in its own `grub.d` file, so the parameters
  written in `/etc/default/grub` never reached the kernel. The ones an earlier version wrote
  there are removed.
- A machine that boots from a UKI it builds gets the parameters in `/etc/kernel/cmdline`, and the
  UKI is built again with `mkinitcpio -P` or `kernel-install add`. A prebuilt UKI, such as
  Fedora's `kernel-uki-virt`, holds its own command line: the install stops before changing
  anything.
- `install.sh` warns when the icon or launcher cache update fails, instead of hiding it.
- Tested by booting Fedora 45, Debian 13, Ubuntu 26.04, openSUSE Tumbleweed and Arch (with and
  without a UKI) in QEMU with `tests/boot/run.sh`.

## v0.5.2 (2026-11-17)

- The orientation setting is gone from the window, and `--rotation` from the terminal. Remote
  desktop servers that capture the screen through KMS (Jump Desktop Connect, for one) ignore a
  rotation set by the desktop, so a portrait output broke their image and input. Changing a mode
  now keeps the output's rotation as it is, and a rotation saved by v0.5.1 is ignored.
- `--auto-login on` says how to open the session again after logging out: logging out ends it
  until the next boot. With greetd the command also removes its runfile, without which a restart
  skips the automatic session.

## v0.5.1 (2026-11-16)

- With greetd (COSMIC), `--auto-login` also marks the automatic session as graphical in greetd's
  PAM service. Without it logind recorded a tty session, and remote desktop servers such as Jump
  Desktop Connect found no graphical session to show.
- Changing the scale or orientation in the window applies it to the mode on screen now, not the
  one shown at the last refresh: the remote desktop client may have switched the mode since, and
  the window then switched it back.
- The launcher is now installed as `br.app.VirtualMonitor.desktop`, the app id of the window, so
  Wayland docks (COSMIC, GNOME) show the app's icon instead of a generic one.

## v0.5.0 (2026-11-15)

- `virtual-monitor --auto-login [on|off]` turns automatic login on (or off) in GDM, SDDM, LightDM
  or greetd (COSMIC's cosmic-greeter included), so a machine with no monitor opens the desktop
  session at boot and the remote desktop and `virtual-monitor` over SSH find it. It keeps a
  `*.before-auto-login` copy of every file it edits.
- When `--list` finds no desktop session over SSH, the message points to `--auto-login`.

## v0.4.1 (2026-11-15)

- The EDID install no longer stops with "The EDID was not found in the boot image" when it is
  there: the check read the image listing through `grep -q`, which, with `pipefail`, failed as
  soon as the long listing was cut short.
- The boot image hook is written for the tool that builds the image (`update-initramfs` or
  `dracut`), creating its folder when it does not exist yet.

## v0.4.0 (2026-11-15)

- `virtual-monitor --install-edid` sets up the virtual monitor on any machine in one command: it
  picks the output (the one the boot already uses, else a free external one, HDMI first), generates
  the EDID and runs the installer with sudo. `--output NAME` and `--modes '...'` change the choice.
  The window's Install button uses the same output and shows it.
- The installer takes the output as an argument and works with GRUB, kernelstub (Pop!_OS) and
  Armbian; on NVIDIA it needs the open kernel modules.
- One default EDID, `edid/virtual-monitor.bin`, on standard clocks every GPU generates; the
  installed file is now `edid/virtual-monitor.bin`, and the boot hooks of earlier versions are
  removed. Reinstall the EDID after updating.
- The README covers any machine with no monitor, not one board.

## v0.3.3 (2026-11-15)

- COSMIC (Pop!_OS) support through `cosmic-randr`, tried after GNOME and KDE: it lists the enabled
  outputs and sets mode, refresh rate, scale and rotation.
- Over SSH, the X display picked is the one the user owns, not the login screen's `:0`.

## v0.3.2 (2026-11-15)

- The app finds the user's desktop session by itself when the shell does not point to it, as over
  SSH or on a text console: the session bus, the Wayland socket, the X display and its cookie, from
  `/run/user/<uid>` and `/tmp/.X11-unix`. Variables already set are kept.
- Without a desktop session, the window explains it instead of a GTK traceback, and the terminal
  says to log in to the desktop first.

## v0.3.1 (2026-11-15)

- The display backend is found by trying each one (GNOME, KDE, `wlr-randr`, `xrandr`) and taking the
  first that lists an output, instead of going by the desktop name. `kscreen-doctor` works without
  `XDG_CURRENT_DESKTOP=KDE`, and `xrandr` skips the XWayland outputs it cannot change.
- The installer adds the `virtual-monitor` command to `~/.local/bin`, so the terminal mode needs no
  path or alias (`virtual-monitor --list`); `--uninstall` removes it.
- A failed display command shows what it printed (`xrandr --query: Can't open display :0`) instead of
  its exit status, and when no backend works the terminal lists why each one failed.

## v0.3.0 (2026-11-13)

- After a switch, the window asks to keep the new mode and goes back to the previous one after 15
  seconds without an answer, in case the mode shows no picture.
- Desktop scale and orientation (landscape or portrait) for the current mode, saved for each
  resolution. Without a saved scale, tablet-like modes such as 2360×1640 get 150% and the others 100%.
- Portrait turns the output a quarter turn, so the iPad can be used upright.
- Terminal: `--next` switches to the mode after the current one (for a keyboard shortcut), and
  `--scale N|auto` and `--rotation normal|left|right` set the scale and rotation; `--version`.
- The EDID page shows the clock and refresh rate each mode will get as you type.
- The Orange Pi EDID has the iPad Air 11" mode (2360×1640); a mode without a clock gets the RK3566
  clock closest to the rate.
- The EDID lives on its own page, and its button shows Installed when it matches the installed EDID.
- CI runs only on the Docker runner, without spending GitLab CI minutes: bash 3.2 (the macOS bash)
  runs in the `bash:3.2` image, and `tests/test_shell_portability.py` catches GNU-only options and
  bash 4 features.

## v0.2.0 (2026-11-04)

- `get.sh` installs with one line (`curl … get.sh | bash`); options after `--` go to `install.sh`,
  and `VERSION=v0.2.0` pins a tag.
- Python 3.9 is the minimum version, tested in CI next to 3.13.
- Flat control flow everywhere (guard clauses, no `else`, `elif` or nested `if`), checked by
  `tests/test_flow_rules.py`.
- English README is the default, with a Portuguese translation; both are shorter.
- App icon, banners, social preview and project avatar live in `assets/`.

## v0.1.0 (2026-11-03)

First release.

- EDID generator (`virtual_monitor/edid.py`) and ready EDIDs in `edid/`, including
  `ultrawide-rockchip.bin`, which only uses clocks the RK3566 PLL can generate.
- GTK4/libadwaita window to switch the resolution and to generate and install EDIDs.
- Terminal mode: `--list`, `--apply ID [--temp]` and `--restore`.
- Display backends for Mutter, KScreen, wlr-randr and xrandr, with the chosen resolution
  remembered and applied at login.
- System scripts for the EDID install, the XFCE session and the session keeper.
- Per-user installer (`install.sh`) with launcher and icon.
- Tests with 100% coverage, run by GitLab CI on Python 3.10 and 3.13 and on macOS with bash 3.2.
