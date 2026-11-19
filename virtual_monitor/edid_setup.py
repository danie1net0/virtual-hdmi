"""
Sets up the virtual monitor on any machine: picks the video output that gets the EDID and runs
scripts/install-edid.sh with an EDID generated from the modes (edid.py).

Any other size, such as the screen of the computer that connects, comes without a reboot:
scripts/set-edid.sh gives the virtual monitor an EDID with that size and the default modes, and the
desktop lists the size once the output comes back.

The output is the one the current boot already uses for the EDID, or else a free external output
(nothing plugged in), HDMI first, then DisplayPort and DVI. Built-in panels (eDP, LVDS, DSI) and
virtual connectors never get it. Outputs come from /sys/class/drm, as cardN-NAME folders.
"""

import contextlib
import re
import tempfile
import time
from pathlib import Path

from virtual_monitor import displays, edid

DRM = Path("/sys/class/drm")
INSTALL_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "install-edid.sh"
SET_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "set-edid.sh"
NOT_INSTALLED = (
    "The virtual monitor is not installed at this boot, so no output takes a new EDID. Install it "
    "first and reboot: virtual-monitor --install-edid"
)
# The desktop lists the new size a moment after the output comes back
WAIT_ATTEMPTS = 20
WAIT_MILLISECONDS = 500
BUILT_IN = ("eDP", "LVDS", "DSI", "DPI", "Virtual", "Writeback")
PREFERRED_KINDS = ("HDMI", "DP", "DVI")


def connector_name(folder):
    """HDMI-A-1 for the folder card1-HDMI-A-1; None for a folder that is not an output (card1, version)."""
    found = re.fullmatch(r"card\d+-(.+)", folder.name)
    if not found:
        return None

    return found.group(1)


def kind(connector):
    return connector.split("-")[0]


def read_status(folder):
    """Connection status of the output in folder, or None when it has none."""
    with contextlib.suppress(OSError):
        return (folder / "status").read_text().strip()


def external_outputs(drm=DRM):
    """(name, status) of every output that is not a built-in panel."""
    try:
        folders = sorted(drm.iterdir())
    except OSError:
        return []

    named = [(connector_name(folder), folder) for folder in folders]
    outputs = [(name, read_status(folder)) for name, folder in named if name]
    return [(name, status) for name, status in outputs if status and kind(name) not in BUILT_IN]


def preference(connector):
    """Sort key: HDMI, then DP, then DVI, then the rest; by name within a kind."""
    position = len(PREFERRED_KINDS)
    if kind(connector) in PREFERRED_KINDS:
        position = PREFERRED_KINDS.index(kind(connector))

    return position, connector


def free_output(drm=DRM):
    """The preferred external output with nothing plugged in, or None."""
    free = [name for name, status in external_outputs(drm) if status == "disconnected"]
    if not free:
        return None

    return min(free, key=preference)


def target_output(drm=DRM):
    """The output that gets the virtual monitor: the one this boot already uses, else a free one."""
    return displays.command_line_connector() or free_output(drm)


def write_edid(modes):
    """Generates the EDID of the modes into a temporary file and returns its path; raises EdidError."""
    _timings, data = edid.generate(modes)
    path = Path(tempfile.mkdtemp(prefix="edid-")) / "virtual-monitor.bin"
    path.write_bytes(data)
    return path


def install_command(edid_path, connector, elevate):
    """The command that installs edid_path on connector, run through elevate (sudo, pkexec or nothing)."""
    return [*elevate, "bash", str(INSTALL_SCRIPT), str(edid_path), connector]


def same_size(first, second):
    return (first.width, first.height) == (second.width, second.height)


def custom_modes(text):
    """The modes of an EDID with the size in text first, so the desktop prefers it, then the default
    modes; a default mode of the same size leaves, so the size keeps the clock or rate in text.
    Raises EdidError."""
    timing = edid.parse_mode(text)
    others = [mode for mode in edid.DEFAULT_MODES if not same_size(edid.parse_mode(mode), timing)]
    return [text, *others]


def size_mode(modes, timing):
    """The listed mode with the size of timing and the rate closest to it, or None."""
    sized = [mode for mode in modes if same_size(mode, timing)]
    if not sized:
        return None

    return min(sized, key=lambda mode: abs(mode.refresh - timing.refresh))


def listed_mode(modes, text):
    """The listed mode that gives the size in text, or None when the EDID has to change: no mode has
    that size, or the text asks for a clock or a rate (@, :). Raises EdidError."""
    timing = edid.parse_mode(text)
    if "@" in text or ":" in text:
        return None

    return size_mode(modes, timing)


def listed_modes(backend, connector):
    """The modes of the output; none while the output is away, between going off and coming back."""
    try:
        return backend.modes(connector)
    except displays.DisplayError:
        return []


def wait_for_size(backend, connector, timing):
    """The mode of the size of timing once the desktop lists it, or None after WAIT_ATTEMPTS."""
    for _attempt in range(WAIT_ATTEMPTS):
        mode = size_mode(listed_modes(backend, connector), timing)
        if mode is not None:
            return mode

        time.sleep(WAIT_MILLISECONDS / 1000)


def set_command(edid_path, connector, elevate):
    """The command that gives connector the EDID in edid_path right away, through elevate."""
    return [*elevate, "bash", str(SET_SCRIPT), str(edid_path), connector]
