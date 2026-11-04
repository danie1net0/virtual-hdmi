"""
Remembered resolution: applies a mode and, when the environment does not keep it
by itself (everything but GNOME), saves the choice and creates an autostart entry that reapplies it at login.
"""

import json
import os
from pathlib import Path

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


def apply_mode(backend, connector, mode_id, persistent):
    backend.apply(connector, mode_id, persistent)

    if persistent and not backend.native_persist:
        save(connector, mode_id)


def restore(backend):
    """Reapplies the remembered choice. Returns False if there was nothing to reapply."""
    choice = load()
    if choice is None:
        return False

    backend.apply(*choice, False)
    return True
