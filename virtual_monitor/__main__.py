"""With no arguments opens the window; with arguments runs in the terminal (--help)."""

import sys


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    if argv:
        from virtual_monitor import cli

        return cli.main(argv)

    from virtual_monitor import window

    return window.run()


if __name__ == "__main__":
    sys.exit(main())
