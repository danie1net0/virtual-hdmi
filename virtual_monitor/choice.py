"""
Remembered resolution: applies a mode and, when the environment does not keep it
by itself (everything but GNOME), saves the choice and creates an autostart entry that reapplies it at login.

Each mode size also keeps its own desktop scale and rotation (settings.json), used every time
that size is applied. Without a saved scale, the size gets displays.auto_scale.
"""

import json
import os
from pathlib import Path

from virtual_monitor import displays

LAUNCHER = Path(__file__).resolve().parent.parent / "virtual-monitor.py"


def config_dir():
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    if not xdg.startswith("/"):
        return Path.home() / ".config"

    return Path(xdg)


def choice_file():
    return config_dir() / "virtual-monitor" / "mode.json"


def autostart_file():
    return config_dir() / "autostart" / "virtual-monitor-restore.desktop"


def settings_file():
    return config_dir() / "virtual-monitor" / "settings.json"


def autostart_entry():
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Virtual monitor (restore resolution)\n"
        f'Exec=python3 "{LAUNCHER}" --restore\n'
        "NoDisplay=true\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def save(connector, mode_id):
    choice = choice_file()
    choice.parent.mkdir(parents=True, exist_ok=True)
    choice.write_text(json.dumps({"connector": connector, "mode": mode_id}))

    autostart = autostart_file()
    autostart.parent.mkdir(parents=True, exist_ok=True)
    autostart.write_text(autostart_entry())


def load():
    """The remembered (connector, mode), or None if there is no valid choice."""
    try:
        choice = json.loads(choice_file().read_text())
        return choice["connector"], choice["mode"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def size_key(width, height):
    return f"{width}x{height}"


def load_settings():
    """Saved settings of every mode size, {"2360x1640": {"scale": 1.25, "rotation": "left"}}; {} if broken."""
    try:
        settings = json.loads(settings_file().read_text())
    except (OSError, ValueError):
        return {}

    if not isinstance(settings, dict):
        return {}

    return settings


def size_settings(width, height):
    """Saved settings of one mode size; {} when there are none."""
    settings = load_settings().get(size_key(width, height))
    if not isinstance(settings, dict):
        return {}

    return settings


def save_setting(width, height, name, value):
    """Saves a setting ("scale" or "rotation") of a mode size; None goes back to the default."""
    settings = load_settings()
    key = size_key(width, height)
    entry = dict(size_settings(width, height))
    entry.pop(name, None)
    if value is not None:
        entry[name] = value

    settings[key] = entry
    if not entry:
        del settings[key]

    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, sort_keys=True))


def saved_scale(settings, width, height):
    """The saved scale, or auto_scale when none is saved or it is not a positive number."""
    scale = settings.get("scale")
    if not isinstance(scale, (int, float)) or isinstance(scale, bool) or scale <= 0:
        return displays.auto_scale(width, height)

    return float(scale)


def saved_rotation(settings):
    rotation = settings.get("rotation")
    if rotation not in displays.ROTATIONS:
        return "normal"

    return rotation


def change_for(backend, connector, mode_id):
    """The ModeChange that applies mode_id with the scale and rotation saved for its size."""
    mode = backend.find_mode(connector, mode_id)
    if mode is None:
        return displays.ModeChange(connector, mode_id)

    settings = size_settings(mode.width, mode.height)
    scale = saved_scale(settings, mode.width, mode.height)
    return displays.ModeChange(connector, mode_id, scale, saved_rotation(settings))


def apply_mode(backend, connector, mode_id, persistent):
    backend.apply(change_for(backend, connector, mode_id), persistent)

    if persistent and not backend.native_persist:
        save(connector, mode_id)


def commit(backend, connector, mode_id):
    """Makes a mode applied temporarily last: GNOME writes it again as persistent, the others save the choice."""
    if backend.native_persist:
        backend.apply(change_for(backend, connector, mode_id), True)
        return

    save(connector, mode_id)


def restore(backend):
    """Reapplies the remembered choice. Returns False if there was nothing to reapply."""
    choice = load()
    if choice is None:
        return False

    backend.apply(change_for(backend, *choice), False)
    return True
