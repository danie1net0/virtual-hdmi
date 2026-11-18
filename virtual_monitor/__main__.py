"""With no arguments opens the window; with arguments runs in the terminal (--help).

Either way it first finds the user's graphical session (session.py), so it also works over SSH.
"""

import sys

from virtual_monitor import session


def main(command_line_arguments=None):
    if command_line_arguments is None:
        command_line_arguments = sys.argv[1:]

    session.attach()

    if command_line_arguments:
        from virtual_monitor import cli

        return cli.main(command_line_arguments)

    from virtual_monitor import window

    return window.run()


if __name__ == "__main__":
    sys.exit(main())
