"""
Sets up the virtual monitor on any machine: picks the video output that gets the EDID and runs
scripts/install-edid.sh with an EDID generated from the modes (edid.py).

The output is the one the current boot already uses for the EDID, or else a free external output
(nothing plugged in), HDMI first, then DisplayPort and DVI. Built-in panels (eDP, LVDS, DSI) and
virtual connectors never get it. Outputs come from /sys/class/drm, as cardN-NAME folders.
"""

import re
import tempfile
from pathlib import Path

from virtual_monitor import displays, edid

DRM = Path("/sys/class/drm")
INSTALL_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "install-edid.sh"
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
    try:
        return (folder / "status").read_text().strip()
    except OSError:
        return None


def external_outputs(drm=DRM):
    """(name, status) of every output that is not a built-in panel."""
    try:
        folders = sorted(drm.iterdir())
    except OSError:
        return []

    named = [(connector_name(folder), read_status(folder)) for folder in folders]
    return [(name, status) for name, status in named if name and status and kind(name) not in BUILT_IN]


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
