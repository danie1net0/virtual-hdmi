import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from virtual_monitor import __version__, choice, cli, displays


def mode(mode_id, current=False, preferred=False):
    width, height = mode_id.split("@")[0].split("x")
    return displays.Mode(mode_id, int(width), int(height), float(mode_id.split("@")[1]), current, preferred)


class Backend(displays.Backend):
    name = "Fake (test)"

    def __init__(self, outputs, error=None):
        self._outputs = outputs
        self.error = error
        self.applied = []

    def outputs(self):
        return self._outputs

    def apply(self, change, persistent):
        if self.error:
            raise self.error

        self.applied.append((change.connector, change.mode_id, persistent))
        self.last_change = change


class CliTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patches = [
            mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(Path(tmp.name))}),
            mock.patch.object(displays, "cmdline_connector", return_value="HDMI-A-1"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.backend = Backend(
            {"HDMI-1": [mode("3440x1440@59.24", preferred=True), mode("2560x1080@59.98", current=True), mode("1920x1080@60.00")]}
        )

    def run_cli(self, argv, backend="default"):
        if backend == "default":
            backend = self.backend

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(displays, "detect", return_value=backend):
            code = cli.main(argv, out, err)
        return code, out.getvalue(), err.getvalue()

    def test_list(self):
        code, out, err = self.run_cli(["--list"])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(
            out.splitlines(),
            [
                "session: Fake (test)",
                "connector: HDMI-1  (EDID at boot: HDMI-A-1)",
                " + 3440x1440@59.24  3440x1440  59.240 Hz",
                "*  2560x1080@59.98  2560x1080  59.980 Hz",
                "   1920x1080@60.00  1920x1080  60.000 Hz",
            ],
        )

    def test_list_without_edid_on_boot(self):
        with mock.patch.object(displays, "cmdline_connector", return_value=None):
            _, out, _ = self.run_cli(["--list"])
        self.assertIn("(EDID at boot: no)", out)

    def test_no_session(self):
        code, out, err = self.run_cli(["--list"], backend=None)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("No supported video environment", err)

    def test_no_connector(self):
        code, _, err = self.run_cli(["--list"], backend=Backend({}))
        self.assertEqual(code, 1)
        self.assertIn("No monitor connected", err)

    def test_apply_remembers(self):
        code, out, _ = self.run_cli(["--apply", "1920x1080@60.00"])

        self.assertEqual(code, 0)
        self.assertEqual(out, "applied 1920x1080@60.00 on HDMI-1\n")
        self.assertEqual(self.backend.applied, [("HDMI-1", "1920x1080@60.00", True)])
        self.assertEqual(choice.load(), ("HDMI-1", "1920x1080@60.00"))

    def test_apply_temp_does_not_remember(self):
        code, _, _ = self.run_cli(["--apply", "1920x1080@60.00", "--temp"])

        self.assertEqual(code, 0)
        self.assertEqual(self.backend.applied, [("HDMI-1", "1920x1080@60.00", False)])
        self.assertIsNone(choice.load())

    def test_apply_failure(self):
        backend = Backend({"HDMI-1": []}, error=RuntimeError("xrandr: cannot find mode"))
        code, out, err = self.run_cli(["--apply", "9x9@1"], backend=backend)

        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err, "Failed: xrandr: cannot find mode\n")
        self.assertIsNone(choice.load())

    def test_restore_with_choice(self):
        choice.save("HDMI-1", "3440x1440@59.24")
        code, out, _ = self.run_cli(["--restore"])

        self.assertEqual((code, out), (0, ""))
        self.assertEqual(self.backend.applied, [("HDMI-1", "3440x1440@59.24", False)])

    def test_restore_without_choice_is_quiet(self):
        self.assertEqual(self.run_cli(["--restore"]), (0, "", ""))
        self.assertEqual(self.backend.applied, [])

    def test_restore_does_not_need_a_connector(self):
        choice.save("HDMI-1", "m")
        backend = Backend({})
        code, _, _ = self.run_cli(["--restore"], backend=backend)

        self.assertEqual(code, 0)
        self.assertEqual(backend.applied, [("HDMI-1", "m", False)])

    def test_restore_failure(self):
        choice.save("HDMI-1", "m")
        code, _, err = self.run_cli(["--restore"], backend=Backend({}, error=RuntimeError("no output")))

        self.assertEqual(code, 1)
        self.assertIn("Failed: no output", err)

    def test_next_applies_the_mode_after_the_current_one(self):
        code, out, _ = self.run_cli(["--next"])

        self.assertEqual(code, 0)
        self.assertEqual(out, "applied 1920x1080@60.00 on HDMI-1\n")
        self.assertEqual(self.backend.applied, [("HDMI-1", "1920x1080@60.00", True)])
        self.assertEqual(choice.load(), ("HDMI-1", "1920x1080@60.00"))

    def test_next_wraps_after_the_last_mode(self):
        backend = Backend({"HDMI-1": [mode("3440x1440@59.24"), mode("1920x1080@60.00", current=True)]})
        self.run_cli(["--next", "--temp"], backend=backend)

        self.assertEqual(backend.applied, [("HDMI-1", "3440x1440@59.24", False)])
        self.assertIsNone(choice.load())

    def test_next_without_current_mode_takes_the_first(self):
        backend = Backend({"HDMI-1": [mode("3440x1440@59.24"), mode("1920x1080@60.00")]})
        self.run_cli(["--next"], backend=backend)
        self.assertEqual(backend.applied[0][1], "3440x1440@59.24")

    def test_next_without_modes_fails(self):
        code, _, err = self.run_cli(["--next"], backend=Backend({"HDMI-1": []}))

        self.assertEqual(code, 1)
        self.assertEqual(err, "Failed: the output has no modes\n")

    def test_apply_with_scale_and_rotation_saves_them_for_the_size(self):
        code, _, _ = self.run_cli(["--apply", "1920x1080@60.00", "--scale", "1.25", "--rotation", "left"])

        self.assertEqual(code, 0)
        self.assertEqual(choice.size_settings(1920, 1080), {"scale": 1.25, "rotation": "left"})
        self.assertEqual(self.backend.last_change, displays.ModeChange("HDMI-1", "1920x1080@60.00", 1.25, "left"))

    def test_scale_alone_rescales_the_current_mode(self):
        code, out, _ = self.run_cli(["--scale", "2"])

        self.assertEqual((code, out), (0, "applied 2560x1080@59.98 on HDMI-1\n"))
        self.assertEqual(self.backend.last_change.scale, 2.0)
        self.assertEqual(choice.size_settings(2560, 1080), {"scale": 2.0})

    def test_rotation_alone_rotates_the_current_mode(self):
        self.run_cli(["--rotation", "right", "--temp"])

        self.assertEqual(self.backend.last_change.rotation, "right")
        self.assertIsNone(choice.load())

    def test_auto_scale_removes_the_saved_one(self):
        choice.save_setting(2560, 1080, "scale", 2.0)
        self.run_cli(["--scale", "auto"])

        self.assertEqual(choice.size_settings(2560, 1080), {})
        self.assertEqual(self.backend.last_change.scale, 1.0)

    def test_scale_without_current_mode_fails(self):
        code, _, err = self.run_cli(["--scale", "2"], backend=Backend({"HDMI-1": [mode("1920x1080@60.00")]}))

        self.assertEqual(code, 1)
        self.assertEqual(err, "Failed: the output has no current mode\n")

    def test_settings_of_unknown_mode_are_not_saved(self):
        backend = Backend({"HDMI-1": []})
        self.run_cli(["--apply", "9x9@1", "--scale", "2"], backend=backend)

        self.assertEqual(choice.load_settings(), {})
        self.assertEqual(backend.last_change, displays.ModeChange("HDMI-1", "9x9@1"))

    def test_scale_argument(self):
        self.assertEqual(cli.scale_argument("1.5"), 1.5)
        self.assertEqual(cli.scale_argument("4"), 4.0)
        self.assertEqual(cli.scale_argument("auto"), cli.AUTO_SCALE)
        for text, message in (("big", "not a number"), ("0", "from 0 to 4"), ("4.5", "from 0 to 4"), ("-1", "from 0 to 4")):
            with self.subTest(text=text), self.assertRaisesRegex(cli.argparse.ArgumentTypeError, message):
                cli.scale_argument(text)

    def test_unknown_rotation_is_refused(self):
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(io.StringIO()):
            cli.parse_args(["--rotation", "inverted"])
        self.assertEqual(raised.exception.code, 2)

    def test_version(self):
        out = io.StringIO()
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(out):
            cli.parse_args(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(out.getvalue(), f"virtual-monitor {__version__}\n")

    def test_options_are_exclusive(self):
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(io.StringIO()):
            cli.parse_args(["--list", "--restore"])
        self.assertEqual(raised.exception.code, 2)

        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.parse_args(["--next", "--apply", "m"])

    def test_temp_alone_lists(self):
        code, out, _ = self.run_cli(["--temp"])

        self.assertEqual(code, 0)
        self.assertIn("session:", out)
        self.assertEqual(self.backend.applied, [])

    def test_help(self):
        out = io.StringIO()
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(out):
            cli.parse_args(["--help"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--apply ID", out.getvalue())


if __name__ == "__main__":
    unittest.main()
