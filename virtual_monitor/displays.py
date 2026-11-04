"""
Lists and switches the video modes of the current graphical session, in any environment:

  GNOME (Mutter)                       DBus org.gnome.Mutter.DisplayConfig
  KDE Plasma                           kscreen-doctor
  wlroots (sway, labwc, Hyprland...)   wlr-randr
  X11 (XFCE, MATE, i3...)              xrandr

Needs no GTK: GNOME uses only Gio, loaded when the backend is tested.
"""

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

CMDLINE = Path("/proc/cmdline")
MUTTER = ("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig", "org.gnome.Mutter.DisplayConfig")


@dataclass(frozen=True)
class Mode:
    id: str
    width: int
    height: int
    refresh: float
    current: bool
    preferred: bool


def run(argv):
    return subprocess.run(argv, capture_output=True, text=True, check=True).stdout


def normalize(connector):
    """HDMI-A-1 (kernel) and HDMI-1 (Mutter, X11) are the same output."""
    return re.sub(r"-A-", "-", connector or "")


def start_xrandr_output(outputs, header):
    """Mode list of a connected output, registered in outputs; None for a disconnected one."""
    if header.group(2) != "connected":
        return None

    modes = []
    outputs[header.group(1)] = modes
    return modes


def parse_xrandr_rates(tokens):
    """[rate, flags] pairs; xrandr may print the flags apart from the rate ("60.00 +")."""
    rates = []
    for token in tokens:
        rate = re.match(r"^(\d+(?:\.\d+)?)([*+]*)$", token)
        if rate:
            rates.append([rate.group(1), rate.group(2)])
            continue

        if rates and re.match(r"^[*+]+$", token):
            rates[-1][1] += token
    return rates


def parse_xrandr(text):
    outputs = {}
    modes = None
    for line in text.splitlines():
        header = re.match(r"^(\S+) (connected|disconnected)", line)
        if header:
            modes = start_xrandr_output(outputs, header)
            continue

        row = re.match(r"^\s+(\d+)x(\d+)(i?)\s+(.*)$", line)
        if not row or modes is None or row.group(3):
            continue

        width, height = int(row.group(1)), int(row.group(2))
        for rate, flags in parse_xrandr_rates(row.group(4).split()):
            modes.append(Mode(f"{width}x{height}@{rate}", width, height, float(rate), "*" in flags, "+" in flags))
    return outputs


def parse_wlr(text):
    outputs = {}
    for output in json.loads(text):
        modes = []
        for mode in output.get("modes", []):
            refresh = float(mode["refresh"])
            modes.append(
                Mode(
                    f"{mode['width']}x{mode['height']}@{refresh:.3f}",
                    mode["width"],
                    mode["height"],
                    refresh,
                    bool(mode.get("current")),
                    bool(mode.get("preferred")),
                )
            )
        outputs[output["name"]] = modes
    return outputs


def parse_kscreen(text):
    outputs = {}
    for output in json.loads(text).get("outputs", []):
        if not output.get("connected"):
            continue

        current = str(output.get("currentModeId"))
        preferred = str((output.get("preferredModes") or [None])[0])
        modes = []
        for mode in output.get("modes", []):
            size = mode["size"]
            mode_id = str(mode["id"])
            modes.append(
                Mode(
                    mode_id,
                    size["width"],
                    size["height"],
                    float(mode["refreshRate"]),
                    mode_id == current,
                    mode_id == preferred,
                )
            )
        outputs[output["name"]] = modes
    return outputs


def parse_mutter(monitors):
    """Monitors from GetCurrentState: ((connector, ...), [(id, w, h, hz, scale, scales, props)], ...)."""
    outputs = {}
    for monitor in monitors:
        modes = []
        for mode_id, width, height, refresh, _scale, _scales, props in monitor[1]:
            modes.append(
                Mode(mode_id, width, height, refresh, bool(props.get("is-current")), bool(props.get("is-preferred")))
            )
        outputs[monitor[0][0]] = modes
    return outputs


def mutter_layout(monitors, logical, connector, mode_id):
    """Builds the logical monitors for ApplyMonitorsConfig, changing only the mode of connector."""
    mode_of = {}
    for monitor in monitors:
        mode_of[monitor[0][0]] = next((m[0] for m in monitor[1] if m[6].get("is-current")), None)
    mode_of[connector] = mode_id

    layout = []
    for x, y, scale, transform, primary, mons, _props in logical:
        members = [(mon[0], mode_of[mon[0]], {}) for mon in mons if mode_of.get(mon[0])]
        if members:
            layout.append((x, y, scale, transform, primary, members))

    if not any(connector == member[0] for item in layout for member in item[5]):
        layout.append((0, 0, 1.0, 0, not layout, [(connector, mode_id, {})]))
    return layout


class Backend:
    """Base of the backends: each one has name, available(), outputs() and apply()."""

    name = ""
    native_persist = False

    def connectors(self):
        return list(self.outputs())

    def modes(self, connector):
        return self.outputs().get(connector, [])


class XrandrBackend(Backend):
    name = "X11 (xrandr)"

    @classmethod
    def available(cls):
        return bool(os.environ.get("DISPLAY")) and shutil.which("xrandr") is not None

    def outputs(self):
        return parse_xrandr(run(["xrandr", "--query"]))

    def apply(self, connector, mode_id, persistent):
        size, rate = mode_id.split("@")
        run(["xrandr", "--output", connector, "--mode", size, "--rate", rate])


class WlrBackend(Backend):
    name = "Wayland (wlr-randr)"

    @classmethod
    def available(cls):
        return bool(os.environ.get("WAYLAND_DISPLAY")) and shutil.which("wlr-randr") is not None

    def outputs(self):
        return parse_wlr(run(["wlr-randr", "--json"]))

    def apply(self, connector, mode_id, persistent):
        run(["wlr-randr", "--output", connector, "--mode", f"{mode_id}Hz"])


class KScreenBackend(Backend):
    name = "KDE Plasma (kscreen-doctor)"

    @classmethod
    def available(cls):
        return "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "") and shutil.which("kscreen-doctor") is not None

    def outputs(self):
        return parse_kscreen(run(["kscreen-doctor", "-j"]))

    def apply(self, connector, mode_id, persistent):
        run(["kscreen-doctor", f"output.{connector}.mode.{mode_id}"])


def mutter_proxy(auto_start):
    from gi.repository import Gio

    flags = Gio.DBusProxyFlags.DO_NOT_AUTO_START
    if auto_start:
        flags = Gio.DBusProxyFlags.NONE

    return Gio.DBusProxy.new_for_bus_sync(Gio.BusType.SESSION, flags, None, *MUTTER, None)


class MutterBackend(Backend):
    name = "GNOME (Mutter)"
    native_persist = True

    def __init__(self):
        self.proxy = mutter_proxy(auto_start=True)

    @classmethod
    def available(cls):
        try:
            return mutter_proxy(auto_start=False).get_name_owner() is not None
        except Exception:
            return False

    def state(self):
        from gi.repository import Gio

        serial, monitors, logical, _props = self.proxy.call_sync(
            "GetCurrentState", None, Gio.DBusCallFlags.NONE, -1, None
        ).unpack()
        return serial, monitors, logical

    def outputs(self):
        return parse_mutter(self.state()[1])

    def apply(self, connector, mode_id, persistent):
        from gi.repository import Gio, GLib

        serial, monitors, logical = self.state()

        layout = mutter_layout(monitors, logical, connector, mode_id)
        method = 1  # temporary
        if persistent:
            method = 2  # persistent (monitors.xml)

        args = GLib.Variant("(uua(iiduba(ssa{sv}))a{sv})", (serial, method, layout, {}))
        self.proxy.call_sync("ApplyMonitorsConfig", args, Gio.DBusCallFlags.NONE, -1, None)


BACKENDS = (MutterBackend, KScreenBackend, WlrBackend, XrandrBackend)


def detect():
    """Backend of the current session, or None."""
    for cls in BACKENDS:
        if cls.available():
            return cls()
    return None


def cmdline_connector():
    """Connector of drm.edid_firmware at the current boot, or None."""
    try:
        cmdline = CMDLINE.read_text()
    except OSError:
        return None

    found = re.search(r"drm\.edid_firmware=([^:\s]+):", cmdline)
    if not found:
        return None

    return found.group(1)


def pick_connector(backend):
    """The virtual EDID output, if the backend sees it; otherwise the first connected one."""
    connectors = backend.connectors()
    wanted = normalize(cmdline_connector())
    for connector in connectors:
        if wanted and normalize(connector) == wanted:
            return connector

    if not connectors:
        return None

    return connectors[0]
