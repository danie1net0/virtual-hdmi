# Virtual monitor

Virtual HDMI monitor for a headless machine (Orange Pi 3B on Armbian, GRUB laptops): an EDID
installed in the kernel makes the video output offer the resolutions it defines, and a GTK4/libadwaita
app switches the resolution and generates/installs EDIDs.

## Layout

- `virtual-monitor.py`: entry point. No arguments opens the window; `--list`, `--apply ID [--temp]`
  and `--restore` run in the terminal.
- `virtual_monitor/`: `edid.py`, `displays.py` (Mutter, KScreen, wlr-randr, xrandr backends),
  `choice.py` (remembered resolution and autostart), `cli.py`, `window.py` (GTK).
- `scripts/`: root-only system scripts. All accept `ROOT=` for tests.
- `edid/`: ready EDIDs. `ultrawide-rockchip.bin` only uses clocks the RK3566 PLL can generate.
- `install.sh`: per-user install of app, icon and launcher (`--dev`, `--dest-dir`, `--uninstall`).

## Rules

- Standard library only (plus `gi` in the window). Everything in English: code, names, messages.
- Shell scripts must run on macOS bash 3.2 and Linux bash 5: no `sed -i`, `install -D` or
  associative arrays.
- New or changed code ships with tests and 100% coverage.
- `README.md` (English, default) and `README.pt-BR.md` (Portuguese) say the same thing; change both together.
  Keep them short: details live in `--help`, the script headers and this file.

## Tests

`bash tests/run.sh` runs everything. `bash tests/coverage.sh` measures coverage; the shell part
needs bash 4.1+ and a non-root user (on macOS use the container in the script header).
`.gitlab-ci.yml` runs the tests on Python 3.10 and 3.13, and coverage on 3.13, for every push and MR.
The `macos` job runs them with the system bash 3.2 on the aurisbook Mac runner (tag `aurisbook-mac`).
