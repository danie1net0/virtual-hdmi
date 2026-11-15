# Virtual monitor

Virtual monitor for any machine with no monitor plugged in (single-board computers, mini PCs,
desktops, laptops with the lid closed): an EDID installed in the kernel makes a free video output
look connected to a monitor with the resolutions it defines, and a GTK4/libadwaita app and CLI
switch the resolution and generate/install the EDID. Nothing in the code or docs may assume one
board, GPU, distribution or desktop: hardware-specific facts (the RK3566 clocks, NVIDIA's open
modules) are notes, not defaults.

## Layout

- `virtual-monitor.py`: entry point. No arguments opens the window; `--list`, `--apply ID [--temp]`,
  `--next`, `--restore` and `--install-edid [--output NAME] [--modes ...]` run in the terminal.
- `virtual_monitor/`: `edid.py`, `displays.py` (Mutter, KScreen, cosmic-randr, wlr-randr, xrandr backends; `detect`
  takes the first that lists an output, `diagnose` says why the others failed; `apply` takes a
  `ModeChange` with the mode, desktop scale and rotation),
  `choice.py` (remembered resolution, autostart, and the scale and rotation saved per mode size in
  `settings.json`, with `auto_scale` as the default), `session.py` (fills the missing session
  variables from `/run/user/<uid>` and `/tmp/.X11-unix`, so the app also runs over SSH; `__main__`
  calls it first), `cli.py`, `window.py` (GTK; a switch goes back after `REVERT_SECONDS` without Keep).
- `scripts/`: root-only system scripts. All accept `ROOT=` for tests.
- `edid/virtual-monitor.bin`: the default EDID, equal to `edid.generate(DEFAULT_MODES)`; its clocks
  (`SAFE_CLOCKS_MHZ`) are standard ones every GPU generates, the RK3566 PLL included.
- `virtual_monitor/edid_setup.py`: picks the output for the EDID (the one at boot, else a free
  external one from `/sys/class/drm`, HDMI first) and builds the `install-edid.sh` command that
  `--install-edid` (sudo) and the window (pkexec) run.
- `assets/`: app icon, README banners and screenshot, GitHub social preview (SVG source and the
  1280×640 PNG uploaded in Settings) and the GitLab project avatar.
- `install.sh`: per-user install of app, icon, launcher and the `~/.local/bin/virtual-monitor`
  command (`--dev`, `--dest-dir`, `--uninstall`).
- `CHANGELOG.md`: one `## vX.Y.Z (date)` section per release, newest first; the top one equals
  `__version__` in `virtual_monitor/__init__.py`. Pushing the tag makes CI create the GitLab release
  from that section (`tests/test_release.py` checks both).
- `get.sh`: `curl | bash` installer. Downloads the GitLab archive of `VERSION` (default `master`)
  and runs `install.sh` with the options after `--`.

## Rules

- Standard library only (plus `gi` in the window). Everything in English: code, names, messages.
- Shell scripts must run on macOS bash 3.2 and Linux bash 5: no `sed -i`, `install -D`,
  associative arrays or other bash 4 features (`tests/test_shell_portability.py` checks it).
- New or changed code ships with tests and 100% coverage.
- Flat control flow: no `else`, `elif`, conditional expressions or `if` inside `if`; use guard
  clauses and small functions. `tests/test_flow_rules.py` checks it.
- `README.md` (English, default) and `README.pt-BR.md` (Portuguese) say the same thing; change both together.
  Keep them short: details live in `--help`, the script headers and this file.

## Tests

`bash tests/run.sh` runs everything. `bash tests/coverage.sh` measures coverage; the shell part
needs bash 4.1+ and a non-root user (on macOS use the container in the script header).
`.gitlab-ci.yml` runs the tests on Python 3.9 and 3.13 and on bash 3.2 (the `bash:3.2` image), and
coverage on 3.13, for every push and MR. Every job runs on the Docker runner (tag `docker`, as a
non-root user), so none spends GitLab CI minutes; no job runs on macOS, so
`tests/test_shell_portability.py` checks for GNU-only options and bash 4 features.
A `vX.Y.Z` tag also runs the `release` job (Docker runner), which creates the GitLab release.
