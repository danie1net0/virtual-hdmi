"""
Finds the graphical session of the current user when the environment does not point to it, as in a
shell opened over SSH or on a text console. Only fills what is missing, never changes what is set:

  XDG_RUNTIME_DIR           /run/user/<uid>
  DBUS_SESSION_BUS_ADDRESS  the session bus in it (GNOME is reached through DBus)
  WAYLAND_DISPLAY           the first wayland-N socket in it (KDE, wlroots compositors)
  DISPLAY                   the X server socket in /tmp/.X11-unix (X11, or XWayland): the lowest one the
                            user owns, else the lowest one (the login screen may hold :0)
  XAUTHORITY                the X cookie that the display manager or the compositor wrote

It only finds sessions of the same user: the sockets of other users are not readable anyway.
"""

import os
import re
import stat
from pathlib import Path

RUNTIME_ROOT = Path("/run/user")
X11_SOCKETS = Path("/tmp/.X11-unix")
# Where GDM, GNOME's XWayland, SDDM and startx-style logins leave the X cookie
XAUTHORITY_PATTERNS = ("gdm/Xauthority", ".mutter-Xwaylandauth.*", "xauth_*")


def is_socket(path):
    try:
        return stat.S_ISSOCK(path.stat().st_mode)
    except OSError:
        return False


def runtime_folder(environment, uid, root=RUNTIME_ROOT):
    """XDG_RUNTIME_DIR, or /run/user/<uid> when it exists; None without either."""
    if environment.get("XDG_RUNTIME_DIR"):
        return Path(environment["XDG_RUNTIME_DIR"])

    folder = root / str(uid)
    if not folder.is_dir():
        return None

    return folder


def socket_number(path, prefix):
    """N of a socket named prefix + N, or None for another name (wayland-0.lock, X0-lock)."""
    found = re.fullmatch(re.escape(prefix) + r"(\d+)", path.name)
    if not found:
        return None

    return int(found.group(1))


def owner(path):
    try:
        return path.stat().st_uid
    except OSError:
        return None


def lowest_socket(folder, prefix, uid=None):
    """Name of the prefix + N socket in folder with the lowest N, those owned by uid first; or None."""
    try:
        entries = list(folder.iterdir())
    except OSError:
        return None

    numbered = [(socket_number(entry, prefix), entry) for entry in entries if is_socket(entry)]
    ranked = [(owner(entry) != uid, number, entry.name) for number, entry in numbered if number is not None]
    if not ranked:
        return None

    return min(ranked)[2]


def xauthority(runtime, home):
    """The first X cookie file found, or None."""
    candidates = [home / ".Xauthority"]
    for pattern in XAUTHORITY_PATTERNS:
        candidates.extend(sorted(runtime.glob(pattern)))

    return next((str(candidate) for candidate in candidates if candidate.is_file()), None)


def add_runtime_variables(found, environment, runtime):
    if not environment.get("DBUS_SESSION_BUS_ADDRESS") and is_socket(runtime / "bus"):
        found["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime / 'bus'}"

    wayland = lowest_socket(runtime, "wayland-")
    if not environment.get("WAYLAND_DISPLAY") and wayland:
        found["WAYLAND_DISPLAY"] = wayland


def add_x11_variables(found, environment, runtime, home, x11_sockets, uid):
    if environment.get("DISPLAY"):
        return

    socket = lowest_socket(x11_sockets, "X", uid)
    if socket is None:
        return

    found["DISPLAY"] = f":{socket[1:]}"
    cookie = xauthority(runtime, home)
    if not environment.get("XAUTHORITY") and cookie:
        found["XAUTHORITY"] = cookie


def missing_variables(environment, uid, home, runtime_root=RUNTIME_ROOT, x11_sockets=X11_SOCKETS):
    """The session variables environ lacks and this user's session provides."""
    found = {}
    runtime = runtime_folder(environment, uid, runtime_root)
    if runtime is None:
        return found

    if not environment.get("XDG_RUNTIME_DIR"):
        found["XDG_RUNTIME_DIR"] = str(runtime)

    add_runtime_variables(found, environment, runtime)
    add_x11_variables(found, environment, runtime, home, x11_sockets, uid)
    return found


def has_display(environment):
    return bool(environment.get("WAYLAND_DISPLAY") or environment.get("DISPLAY"))


def attach():
    """Completes os.environ with the user's graphical session; True when there is a display to use."""
    os.environ.update(missing_variables(os.environ, os.getuid(), Path.home()))
    return has_display(os.environ)
