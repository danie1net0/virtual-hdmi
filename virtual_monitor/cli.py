"""Terminal mode of the Virtual monitor: lists, applies and restores resolutions, and installs the
virtual monitor (the EDID), without GTK."""

import argparse
import getpass
import os
import subprocess
import sys
from pathlib import Path

from virtual_monitor import __version__, choice, displays, edid, edid_setup

AUTO_SCALE = 0.0
AUTO_LOGIN_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "auto-login.sh"
EDID_HINT = (
    "No output is connected. Plug in a monitor, or install the virtual monitor so an output works "
    "without one: virtual-monitor --install-edid"
)
NO_FREE_OUTPUT = (
    "No free video output for the virtual monitor (every external output has something plugged in). "
    "Pick one with --output NAME; the names are the folders after cardN- in /sys/class/drm."
)


def scale_argument(text):
    """A positive scale such as 1.25, or "auto" (AUTO_SCALE) to go back to the default of the size."""
    if text == "auto":
        return AUTO_SCALE

    try:
        scale = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text}") from None

    if not 0 < scale <= 4:
        raise argparse.ArgumentTypeError(f"use a scale from 0 to 4, or auto: {text}")

    return scale


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="virtual-monitor", description="With no options, opens the window.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--list", action="store_true", help="shows the session, the connector and the modes (default)")
    action.add_argument("--apply", metavar="ID", help="applies mode ID and remembers it at the next login")
    action.add_argument("--next", action="store_true", help="applies the mode after the current one, like --apply")
    action.add_argument("--restore", action="store_true", help="reapplies the last remembered mode")
    action.add_argument(
        "--install-edid",
        action="store_true",
        help="installs the virtual monitor, so a free output works with no monitor plugged in (asks for sudo)",
    )
    action.add_argument(
        "--auto-login",
        nargs="?",
        const="on",
        choices=("on", "off"),
        help="opens your desktop session at boot (on, the default) or stops it (off), so the machine works "
        "with no one at it (asks for sudo)",
    )
    parser.add_argument("--output", metavar="NAME", help="with --install-edid: the output, like HDMI-A-1 or DP-1")
    parser.add_argument(
        "--modes",
        default=" ".join(edid.DEFAULT_MODES),
        metavar="'MODE ...'",
        help="with --install-edid: WIDTHxHEIGHT[@MHZ][:HZ] modes, separated by spaces (default: %(default)s)",
    )
    parser.add_argument("--temp", action="store_true", help="with --apply or --next: does not remember the choice")
    parser.add_argument(
        "--scale",
        type=scale_argument,
        metavar="N",
        help="desktop scale (1.25, 1.5...) or auto, saved for the size of the mode; alone, rescales the current mode",
    )
    parser.add_argument(
        "--rotation",
        choices=displays.ROTATIONS,
        help="rotation saved for the size of the mode (left or right: portrait); alone, rotates the current mode",
    )

    return parser.parse_args(argv)


def flag(on, mark):
    if not on:
        return " "

    return mark


def print_modes(backend, connector, out):
    print(f"session: {backend.name}", file=out)
    print(f"connector: {connector}  (EDID at boot: {displays.cmdline_connector() or 'no'})", file=out)

    for mode in backend.modes(connector):
        flags = flag(mode.current, "*") + flag(mode.preferred, "+")
        print(f"{flags} {mode.id}  {mode.width}x{mode.height}  {mode.refresh:.3f} Hz", file=out)


def current_index(modes):
    """Position of the current mode, or -1 when none is current."""
    return next((index for index, mode in enumerate(modes) if mode.current), -1)


def next_mode(modes):
    """The mode after the current one, back to the first after the last."""
    if not modes:
        raise ValueError("the output has no modes")

    return modes[(current_index(modes) + 1) % len(modes)].id


def current_mode(modes):
    index = current_index(modes)
    if index < 0:
        raise ValueError("the output has no current mode")

    return modes[index].id


def target_mode(args, modes):
    """The mode the options switch to, or None when they only list."""
    if args.apply:
        return args.apply

    if args.next:
        return next_mode(modes)

    if args.scale is None and args.rotation is None:
        return None

    return current_mode(modes)


def save_settings(args, backend, connector, mode_id):
    """Saves --scale and --rotation for the size of mode_id; an unknown mode keeps nothing."""
    mode = backend.find_mode(connector, mode_id)
    if mode is None:
        return

    if args.scale is not None:
        choice.save_setting(mode.width, mode.height, "scale", args.scale or None)

    if args.rotation is not None:
        choice.save_setting(mode.width, mode.height, "rotation", args.rotation)


def run_action(args, backend, out, err):
    if args.restore:
        choice.restore(backend)
        return 0

    connector = displays.pick_connector(backend)
    if connector is None:
        print("No monitor connected.", file=err)
        return 1

    mode_id = target_mode(args, backend.modes(connector))
    if mode_id is None:
        print_modes(backend, connector, out)
        return 0

    save_settings(args, backend, connector, mode_id)
    choice.apply_mode(backend, connector, mode_id, not args.temp)
    print(f"applied {mode_id} on {connector}", file=out)
    return 0


SESSION_HINT = (
    "If no desktop session of yours is open (after a reboot, nobody logged in), log in to the "
    "desktop, or turn on automatic login: virtual-monitor --auto-login"
)


def print_session_hint(err):
    """Hints at a closed session when the user has no Wayland socket: an X display alone may be the
    login screen's."""
    if os.environ.get("WAYLAND_DISPLAY"):
        return

    print(SESSION_HINT, file=err)


def print_edid_hint(reasons, err):
    """A backend ran but saw no output: no monitor is plugged in and no virtual EDID makes one up."""
    if not any(reason == "no connected output" for _name, reason in reasons):
        return

    print(EDID_HINT, file=err)


def elevate():
    """sudo, unless already root."""
    if os.geteuid() == 0:
        return []

    return ["sudo"]


def install_edid(args, out, err):
    """Generates the EDID of --modes and installs it on --output or the output edid_setup picks."""
    output = args.output or edid_setup.target_output()
    if output is None:
        print(NO_FREE_OUTPUT, file=err)
        return 1

    try:
        path = edid_setup.write_edid(args.modes.split())
    except edid.EdidError as error:
        print(f"Invalid EDID: {error}", file=err)
        return 1

    print(f"Installing the virtual monitor on {output}", file=out)
    return subprocess.call(edid_setup.install_command(path, output, elevate()))


def login_user():
    """The user who runs the command, also under sudo."""
    return os.environ.get("SUDO_USER") or getpass.getuser()


def auto_login(state):
    return subprocess.call([*elevate(), "bash", str(AUTO_LOGIN_SCRIPT), login_user(), state])


def main(argv, out=None, err=None):
    out, err = out or sys.stdout, err or sys.stderr
    args = parse_args(argv)
    if args.install_edid:
        return install_edid(args, out, err)

    if args.auto_login:
        return auto_login(args.auto_login)

    backend = displays.detect()
    if backend is None:
        print("No supported video environment in this session:", file=err)
        reasons = displays.diagnose()
        for name, reason in reasons:
            print(f"  {name}: {reason}", file=err)
        print_session_hint(err)
        print_edid_hint(reasons, err)
        return 1

    try:
        return run_action(args, backend, out, err)
    except Exception as error:  # xrandr, kscreen-doctor or DBus refused the mode
        print(f"Failed: {error}", file=err)
        return 1
