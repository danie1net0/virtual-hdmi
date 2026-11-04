import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from virtual_monitor import choice, cli, displays


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

    def apply(self, connector, mode_id, persistent):
        if self.error:
            raise self.error
        self.applied.append((connector, mode_id, persistent))


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

    def test_options_are_exclusive(self):
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(io.StringIO()):
            cli.parse_args(["--list", "--restore"])
        self.assertEqual(raised.exception.code, 2)

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
