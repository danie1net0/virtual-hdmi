"""
Lists and switches the video modes of the current graphical session, in any environment:

  GNOME (Mutter)                       DBus org.gnome.Mutter.DisplayConfig
  KDE Plasma                           kscreen-doctor
  COSMIC (Pop!_OS)                     cosmic-randr
  wlroots (sway, labwc, Hyprland...)   wlr-randr
  X11 (XFCE, MATE, i3...)              xrandr

detect() tries each backend in that order and takes the first that lists an output, so it does not
depend on the desktop name: wlr-randr also drives the other compositors with wlr-output-management
(Hyprland, niri, Wayfire...), kscreen-doctor works on KDE under X11 or Wayland, and xrandr skips the
XWayland outputs it cannot change. diagnose() says why each backend was left out.

Needs no GTK: GNOME uses only Gio, loaded when the backend is tested.

Applying a mode also sets the desktop scale (ModeChange) and keeps the output's rotation. The default scale is
1.5 on dense tablet-like modes (the iPad Air 11" 2360x1640) and 1 on the others. XFCE scales
through Xft/DPI; other X11 desktops keep their own.
"""

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

KERNEL_COMMAND_LINE = Path("/proc/cmdline")
MUTTER = ("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig", "org.gnome.Mutter.DisplayConfig")
TABLET_SCALE = 1.5
TABLET_MINIMUM_HEIGHT = 1500
TABLET_MAXIMUM_ASPECT = 1.6
XFT_DPI_AT_1X = 96


@dataclass(frozen=True)
class Mode:
    id: str
    width: int
    height: int
    refresh: float
    current: bool
    preferred: bool


@dataclass(frozen=True)
class ModeChange:
    """What apply() sets on an output: the mode and the desktop scale."""

    connector: str
    mode_id: str
    scale: float = 1.0

    def __post_init__(self):
        if self.scale <= 0:
            raise ValueError(f"The scale must be positive: {self.scale:g}")


def auto_scale(width, height):
    """Desktop scale for a mode: TABLET_SCALE when it is tall and at most 16:10, as on a tablet; 1 otherwise."""
    if height < TABLET_MINIMUM_HEIGHT or width > height * TABLET_MAXIMUM_ASPECT:
        return 1.0

    return TABLET_SCALE


class DisplayError(RuntimeError):
    """A display tool is missing or refused the command; the message says what it printed."""


def command_message(error):
    """First line the failed command printed, or its exit status when it printed nothing."""
    lines = (error.stderr or error.stdout or "").strip().splitlines()
    if not lines:
        return f"exit status {error.returncode}"

    return lines[0]


def run(command):
    try:
        return subprocess.run(command, capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        raise DisplayError(f"{command[0]} is not installed") from None
    except subprocess.CalledProcessError as error:
        raise DisplayError(f"{' '.join(command[:2])}: {command_message(error)}") from None


def missing_variable(name):
    """Why a backend cannot run without the environment variable name; "" when it is set."""
    if os.environ.get(name):
        return ""

    return f"{name} is not set"


def missing_tool(tool):
    if shutil.which(tool) is not None:
        return ""

    return f"{tool} is not installed"


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


def parse_cosmic(text):
    """Enabled outputs of `cosmic-randr list --kdl`; mode lines are "mode WIDTH HEIGHT MILLIHERTZ [flags]"."""
    outputs = {}
    modes = None
    for line in text.splitlines():
        header = re.match(r'^output "([^"]+)" enabled=#(true|false)', line)
        if header:
            modes = start_cosmic_output(outputs, header)
            continue

        row = re.match(r"^\s+mode (\d+) (\d+) (\d+)(.*)$", line)
        if not row or modes is None:
            continue

        width, height, refresh = int(row.group(1)), int(row.group(2)), int(row.group(3)) / 1000
        flags = row.group(4)
        modes.append(
            Mode(f"{width}x{height}@{refresh:.3f}", width, height, refresh, "current=#true" in flags, "preferred=#true" in flags)
        )
    return outputs


def start_cosmic_output(outputs, header):
    """Mode list of an enabled output, registered in outputs; None for a disabled one."""
    if header.group(2) != "true":
        return None

    modes = []
    outputs[header.group(1)] = modes
    return modes


def parse_mutter(monitors):
    """Monitors from GetCurrentState: ((connector, ...), [(id, width, height, refresh, scale, scales, properties)], ...)."""
    outputs = {}
    for monitor in monitors:
        modes = []
        for mode_id, width, height, refresh, _scale, _scales, properties in monitor[1]:
            modes.append(
                Mode(mode_id, width, height, refresh, bool(properties.get("is-current")), bool(properties.get("is-preferred")))
            )
        outputs[monitor[0][0]] = modes
    return outputs


def mutter_scale(monitors, change):
    """The scale Mutter supports for the mode that is closest to change.scale; Mutter refuses any other."""
    modes = [
        mode
        for monitor in monitors
        if monitor[0][0] == change.connector
        for mode in monitor[1]
        if mode[0] == change.mode_id
    ]
    if not modes:
        return 1.0

    supported = modes[0][5]
    return min(supported, key=lambda scale: abs(scale - change.scale))


def holds(members, connector):
    return any(member[0] == connector for member in members)


def mutter_layout(monitors, logical, change):
    """Builds the logical monitors for ApplyMonitorsConfig, changing only the mode and scale of the connector."""
    mode_of = {}
    for monitor in monitors:
        mode_of[monitor[0][0]] = next((mode[0] for mode in monitor[1] if mode[6].get("is-current")), None)

    mode_of[change.connector] = change.mode_id
    scale = mutter_scale(monitors, change)

    layout = []
    for left, top, own_scale, own_transform, primary, monitors_in, _properties in logical:
        members = [(monitor[0], mode_of[monitor[0]], {}) for monitor in monitors_in if mode_of.get(monitor[0])]
        if not members:
            continue

        if holds(members, change.connector):
            layout.append((left, top, scale, own_transform, primary, members))
            continue

        layout.append((left, top, own_scale, own_transform, primary, members))

    if not any(holds(item[5], change.connector) for item in layout):
        layout.append((0, 0, scale, 0, not layout, [(change.connector, change.mode_id, {})]))
    return layout


def set_xfce_dpi(scale):
    """XFCE scales fonts and widgets through Xft/DPI (96 is 1x); without xfconf-query, nothing changes."""
    if shutil.which("xfconf-query") is None:
        return

    dpi = str(round(XFT_DPI_AT_1X * scale))
    run(["xfconf-query", "-c", "xsettings", "-p", "/Xft/DPI", "-n", "-t", "int", "-s", dpi])


class Backend:
    """Base of the backends: each one has name, requirement(), outputs() and apply(change, persistent)."""

    name = ""
    native_persist = False

    @classmethod
    def available(cls):
        return not cls.requirement()

    def connectors(self):
        return list(self.outputs())

    def modes(self, connector):
        return self.outputs().get(connector, [])

    def find_mode(self, connector, mode_id):
        """The mode mode_id of the output, or None when the output does not list it."""
        return next((mode for mode in self.modes(connector) if mode.id == mode_id), None)


class XrandrBackend(Backend):
    name = "X11 (xrandr)"

    @classmethod
    def requirement(cls):
        """Why the backend cannot run here; "" when it can."""
        return missing_variable("DISPLAY") or missing_tool("xrandr")

    def outputs(self):
        """Connected outputs, without the XWAYLAND ones: a Wayland session ignores modes set on them."""
        outputs = parse_xrandr(run(["xrandr", "--query"]))
        real = {name: modes for name, modes in outputs.items() if not name.startswith("XWAYLAND")}
        if outputs and not real:
            raise DisplayError("only XWayland outputs, which xrandr cannot change")

        return real

    def apply(self, change, persistent):
        size, rate = change.mode_id.split("@")
        run(["xrandr", "--output", change.connector, "--mode", size, "--rate", rate])
        set_xfce_dpi(change.scale)


class WlrBackend(Backend):
    name = "Wayland (wlr-randr)"

    @classmethod
    def requirement(cls):
        return missing_variable("WAYLAND_DISPLAY") or missing_tool("wlr-randr")

    def outputs(self):
        return parse_wlr(run(["wlr-randr", "--json"]))

    def apply(self, change, persistent):
        run(
            [
                "wlr-randr",
                "--output",
                change.connector,
                "--mode",
                f"{change.mode_id}Hz",
                "--scale",
                f"{change.scale:g}",
            ]
        )


class KScreenBackend(Backend):
    name = "KDE Plasma (kscreen-doctor)"

    @classmethod
    def requirement(cls):
        return missing_tool("kscreen-doctor")

    def outputs(self):
        return parse_kscreen(run(["kscreen-doctor", "-j"]))

    def apply(self, change, persistent):
        output = f"output.{change.connector}"
        run(
            [
                "kscreen-doctor",
                f"{output}.mode.{change.mode_id}",
                f"{output}.scale.{change.scale:g}",
            ]
        )


class CosmicBackend(Backend):
    name = "COSMIC (cosmic-randr)"

    @classmethod
    def requirement(cls):
        return missing_variable("WAYLAND_DISPLAY") or missing_tool("cosmic-randr")

    def outputs(self):
        return parse_cosmic(run(["cosmic-randr", "list", "--kdl"]))

    def apply(self, change, persistent):
        size, rate = change.mode_id.split("@")
        width, height = size.split("x")
        run(
            [
                "cosmic-randr",
                "mode",
                change.connector,
                width,
                height,
                "--refresh",
                rate,
                "--scale",
                f"{change.scale:g}",
            ]
        )


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
    def requirement(cls):
        try:
            owner = mutter_proxy(auto_start=False).get_name_owner()
        except Exception as error:  # no gi, no session bus
            return f"no session bus ({error})"

        if owner is None:
            return "GNOME Shell is not running"

        return ""

    def state(self):
        from gi.repository import Gio

        serial, monitors, logical, _properties = self.proxy.call_sync(
            "GetCurrentState", None, Gio.DBusCallFlags.NONE, -1, None
        ).unpack()
        return serial, monitors, logical

    def outputs(self):
        return parse_mutter(self.state()[1])

    def apply(self, change, persistent):
        from gi.repository import Gio, GLib

        serial, monitors, logical = self.state()

        layout = mutter_layout(monitors, logical, change)
        method = 1  # temporary
        if persistent:
            method = 2  # persistent (monitors.xml)

        arguments = GLib.Variant("(uua(iiduba(ssa{sv}))a{sv})", (serial, method, layout, {}))
        self.proxy.call_sync("ApplyMonitorsConfig", arguments, Gio.DBusCallFlags.NONE, -1, None)


BACKENDS = (MutterBackend, KScreenBackend, CosmicBackend, WlrBackend, XrandrBackend)


def probe(backend_class):
    """(backend, "") when backend_class lists an output in this session; (None, why not) otherwise."""
    reason = backend_class.requirement()
    if reason:
        return None, reason

    try:
        backend = backend_class()
        outputs = backend.outputs()
    except Exception as error:  # the tool, DBus or gi refused
        return None, str(error)

    if not outputs:
        return None, "no connected output"

    return backend, ""


def detect():
    """The first backend that works in the current session, or None."""
    for backend_class in BACKENDS:
        backend, _reason = probe(backend_class)
        if backend is not None:
            return backend
    return None


def diagnose():
    """(backend name, why it does not work) for every backend, to explain a None from detect()."""
    return [(backend_class.name, probe(backend_class)[1]) for backend_class in BACKENDS]


def command_line_connector():
    """Connector of drm.edid_firmware at the current boot, or None."""
    try:
        command_line = KERNEL_COMMAND_LINE.read_text()
    except OSError:
        return None

    found = re.search(r"drm\.edid_firmware=([^:\s]+):", command_line)
    if not found:
        return None

    return found.group(1)


def pick_connector(backend):
    """The virtual EDID output, if the backend sees it; otherwise the first connected one."""
    connectors = backend.connectors()
    wanted = normalize(command_line_connector())
    for connector in connectors:
        if wanted and normalize(connector) == wanted:
            return connector

    if not connectors:
        return None

    return connectors[0]
