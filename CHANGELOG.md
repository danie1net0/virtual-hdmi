# Changelog

Each `## vX.Y.Z` section becomes the GitLab release of that tag: CI creates the release from it when
the tag is pushed. Pin a version with `VERSION=vX.Y.Z` (see `get.sh`).

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
