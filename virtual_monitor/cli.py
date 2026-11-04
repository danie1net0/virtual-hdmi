"""Terminal mode of the Virtual monitor: lists, applies and restores resolutions, without GTK."""

import argparse
import sys

from virtual_monitor import choice, displays


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="virtual-monitor", description="With no options, opens the window.")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--list", action="store_true", help="shows the session, the connector and the modes (default)")
    action.add_argument("--apply", metavar="ID", help="applies mode ID and remembers it at the next login")
    action.add_argument("--restore", action="store_true", help="reapplies the last remembered mode")
    parser.add_argument("--temp", action="store_true", help="with --apply: does not remember the choice")

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


def run_action(args, backend, out, err):
    if args.restore:
        choice.restore(backend)
        return 0

    connector = displays.pick_connector(backend)
    if connector is None:
        print("No monitor connected.", file=err)
        return 1

    if args.apply:
        choice.apply_mode(backend, connector, args.apply, not args.temp)
        print(f"applied {args.apply} on {connector}", file=out)
        return 0

    print_modes(backend, connector, out)
    return 0


def main(argv, out=None, err=None):
    out, err = out or sys.stdout, err or sys.stderr
    args = parse_args(argv)

    backend = displays.detect()
    if backend is None:
        print("No supported video environment in this session.", file=err)
        return 1

    try:
        return run_action(args, backend, out, err)
    except Exception as error:  # xrandr, kscreen-doctor or DBus refused the mode
        print(f"Failed: {error}", file=err)
        return 1
