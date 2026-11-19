"""What the user reads (options, help, hints, window labels) against tests/snapshots/*.txt.

After changing a text on purpose, run with UPDATE_SNAPSHOTS=1 and check the diff.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import fake_gi

fake_gi.install()

from virtual_monitor import __version__, cli, displays, edid  # noqa: E402
from virtual_monitor import window as window_module  # noqa: E402

SNAPSHOTS = Path(__file__).resolve().parent / "snapshots"


def parser_lines(parser):
    lines = [f"prog: {parser.prog}", f"description: {parser.description}"]
    for action in parser._actions:
        name = ", ".join(action.option_strings) or action.dest
        version = getattr(action, "version", None)
        lines.append(f"{name}: help={action.help!r} metavar={action.metavar!r} choices={action.choices!r} default={action.default!r}")
        lines.append(f"{name}: version={version!r}".replace(__version__, "VERSION"))

    return lines


def widget_lines(widget, depth=0):
    """Title, subtitle, description and label of the widget and everything under it."""
    lines = []
    values = {**widget.constructor_properties, "subtitle": widget.subtitle, "label": widget.label}
    texts = [f"{key}={values[key]!r}" for key in ("title", "subtitle", "description", "label") if values.get(key)]
    if texts:
        lines.append("  " * depth + f"{type(widget).__name__}: " + " ".join(texts))

    children = [*widget.children, *widget.suffixes, *widget.top_bars]
    children.extend(child for child in (widget.child, widget.content, widget.constructor_properties.get("child")) if child is not None)
    for child in children:
        lines.extend(widget_lines(child, depth + 1))

    return lines


class SnapshotTestCase(unittest.TestCase):
    def assert_snapshot(self, name, lines):
        path = SNAPSHOTS / f"{name}.txt"
        text = "\n".join(lines) + "\n"
        if os.environ.get("UPDATE_SNAPSHOTS") == "1":
            path.write_text(text)

        self.assertEqual(text, path.read_text())


class InterfaceTextsTest(SnapshotTestCase):
    def test_terminal_options(self):
        self.assert_snapshot("terminal-options", parser_lines(cli.build_parser()))

    def test_edid_options(self):
        self.assert_snapshot("edid-options", parser_lines(edid.build_parser()))

    def test_messages_and_constants(self):
        values = {
            "cli.EDID_HINT": cli.EDID_HINT,
            "cli.NO_FREE_OUTPUT": cli.NO_FREE_OUTPUT,
            "cli.SESSION_HINT": cli.SESSION_HINT,
            "displays.MUTTER": displays.MUTTER,
            "displays.KERNEL_COMMAND_LINE": str(displays.KERNEL_COMMAND_LINE),
            "window.EDID_HELP": window_module.EDID_HELP,
            "window.NO_FREE_OUTPUT": window_module.NO_FREE_OUTPUT,
            "window.NO_DISPLAY": window_module.NO_DISPLAY,
            "window.REVERT_SECONDS": window_module.REVERT_SECONDS,
            "window.SCALES": window_module.SCALES,
        }
        self.assert_snapshot("messages", [f"{name} = {value!r}" for name, value in values.items()])


class WindowTextsTest(SnapshotTestCase):
    def test_window_labels(self):
        fake_gi.install()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        patches = [
            mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": temporary.name}),
            mock.patch.object(displays, "detect", return_value=None),
            mock.patch.object(displays, "command_line_connector", return_value=None),
            mock.patch.object(window_module.edid_setup, "target_output", return_value="HDMI-A-1"),
            mock.patch.object(edid, "INSTALLED", Path(temporary.name) / "none.bin"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        window = window_module.Window(fake_gi.Adw.Application("test"))

        self.assert_snapshot("window", widget_lines(window))


if __name__ == "__main__":
    unittest.main()
