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


def parse_arguments(command_line_arguments):
    return build_parser().parse_args(command_line_arguments)


def build_parser():
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
    parser.add_argument("--temp", action="store_true", help="with --apply, --next or --scale: does not remember the resolution")
    parser.add_argument(
        "--scale",
        type=scale_argument,
        metavar="N",
        help="desktop scale (1.25, 1.5...) or auto, saved for the size of the mode; alone, rescales the current mode",
    )

    return parser


def flag(on, mark):
    if not on:
        return " "

    return mark


def print_modes(backend, connector, standard_output):
    print(f"session: {backend.name}", file=standard_output)
    print(f"connector: {connector}  (EDID at boot: {displays.command_line_connector() or 'no'})", file=standard_output)

    for mode in backend.modes(connector):
        flags = flag(mode.current, "*") + flag(mode.preferred, "+")
        print(f"{flags} {mode.id}  {mode.width}x{mode.height}  {mode.refresh:.3f} Hz", file=standard_output)


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


def target_mode(arguments, modes):
    """The mode the options switch to, or None when they only list."""
    if arguments.apply:
        return arguments.apply

    if arguments.next:
        return next_mode(modes)

    if arguments.scale is None:
        return None

    return current_mode(modes)


def save_settings(arguments, backend, connector, mode_id):
    """Saves --scale for the size of mode_id; an unknown mode keeps nothing."""
    if arguments.scale is None:
        return

    mode = backend.find_mode(connector, mode_id)
    if mode is None:
        return

    choice.save_setting(mode.width, mode.height, "scale", arguments.scale or None)


def run_action(arguments, backend, standard_output, error_output):
    if arguments.restore:
        choice.restore(backend)
        return 0

    connector = displays.pick_connector(backend)
    if connector is None:
        print("No monitor connected.", file=error_output)
        return 1

    mode_id = target_mode(arguments, backend.modes(connector))
    if mode_id is None:
        print_modes(backend, connector, standard_output)
        return 0

    save_settings(arguments, backend, connector, mode_id)
    choice.apply_mode(backend, connector, mode_id, not arguments.temp)
    print(f"applied {mode_id} on {connector}", file=standard_output)
    return 0


SESSION_HINT = (
    "If no desktop session of yours is open (after a reboot, nobody logged in), log in to the "
    "desktop, or turn on automatic login: virtual-monitor --auto-login"
)


def print_session_hint(error_output):
    """Hints at a closed session when the user has no Wayland socket: an X display alone may be the
    login screen's."""
    if os.environ.get("WAYLAND_DISPLAY"):
        return

    print(SESSION_HINT, file=error_output)


def print_edid_hint(reasons, error_output):
    """A backend ran but saw no output: no monitor is plugged in and no virtual EDID makes one up."""
    if not any(reason == "no connected output" for _name, reason in reasons):
        return

    print(EDID_HINT, file=error_output)


def elevate():
    """sudo, unless already root."""
    if os.geteuid() == 0:
        return []

    return ["sudo"]


def install_edid(arguments, standard_output, error_output):
    """Generates the EDID of --modes and installs it on --output or the output edid_setup picks."""
    output = arguments.output or edid_setup.target_output()
    if output is None:
        print(NO_FREE_OUTPUT, file=error_output)
        return 1

    try:
        path = edid_setup.write_edid(arguments.modes.split())
    except edid.EdidError as error:
        print(f"Invalid EDID: {error}", file=error_output)
        return 1

    print(f"Installing the virtual monitor on {output}", file=standard_output)
    return subprocess.call(edid_setup.install_command(path, output, elevate()))


def login_user():
    """The user who runs the command, also under sudo."""
    return os.environ.get("SUDO_USER") or getpass.getuser()


def auto_login(state):
    return subprocess.call([*elevate(), "bash", str(AUTO_LOGIN_SCRIPT), login_user(), state])


def main(command_line_arguments, standard_output=None, error_output=None):
    # Without a stream, print writes to sys.stdout; errors go to sys.stderr
    error_output = error_output or sys.stderr
    arguments = parse_arguments(command_line_arguments)
    if arguments.install_edid:
        return install_edid(arguments, standard_output, error_output)

    if arguments.auto_login:
        return auto_login(arguments.auto_login)

    backend = displays.detect()
    if backend is None:
        print("No supported video environment in this session:", file=error_output)
        reasons = displays.diagnose()
        for name, reason in reasons:
            print(f"  {name}: {reason}", file=error_output)

        print_session_hint(error_output)
        print_edid_hint(reasons, error_output)
        return 1

    try:
        return run_action(arguments, backend, standard_output, error_output)
    except Exception as error:  # a display tool or DBus refused the mode
        print(f"Failed: {error}", file=error_output)
        return 1
