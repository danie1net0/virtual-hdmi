import contextlib
import io
import os
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
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        patches = [
            mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(Path(temporary.name))}),
            mock.patch.object(displays, "command_line_connector", return_value="HDMI-A-1"),
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

        standard_output, error_output = io.StringIO(), io.StringIO()
        with mock.patch.object(displays, "detect", return_value=backend):
            code = cli.main(argv, standard_output, error_output)
        return code, standard_output.getvalue(), error_output.getvalue()

    def test_list(self):
        code, standard_output, error_output = self.run_cli(["--list"])
        self.assertEqual((code, error_output), (0, ""))
        self.assertEqual(
            standard_output.splitlines(),
            [
                "session: Fake (test)",
                "connector: HDMI-1  (EDID at boot: HDMI-A-1)",
                " + 3440x1440@59.24  3440x1440  59.240 Hz",
                "*  2560x1080@59.98  2560x1080  59.980 Hz",
                "   1920x1080@60.00  1920x1080  60.000 Hz",
            ],
        )

    def test_no_session_without_display_says_to_log_in(self):
        environ = {key: value for key, value in os.environ.items() if key not in ("DISPLAY", "WAYLAND_DISPLAY")}
        with mock.patch.object(displays, "diagnose", return_value=[]), mock.patch.dict("os.environ", environ, clear=True):
            code, _out, error_output = self.run_cli(["--list"], backend=None)

        self.assertEqual(code, 1)
        self.assertEqual(error_output.splitlines()[-1], cli.SESSION_HINT)

    def test_no_connected_output_suggests_the_virtual_edid(self):
        reasons = [("COSMIC (cosmic-randr)", "no connected output"), ("X11 (xrandr)", "DISPLAY is not set")]
        with mock.patch.object(displays, "diagnose", return_value=reasons), mock.patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-1"}):
            code, _out, error_output = self.run_cli(["--list"], backend=None)

        self.assertEqual(code, 1)
        self.assertEqual(error_output.splitlines()[-1], cli.EDID_HINT)

    def run_auto_login(self, argv, environ, euid=1000):
        with mock.patch.object(cli.subprocess, "call", return_value=4) as call, mock.patch(
            "os.geteuid", return_value=euid
        ), mock.patch.dict("os.environ", environ), mock.patch("getpass.getuser", return_value="daniel"), mock.patch.object(
            displays, "detect"
        ) as detect:
            code = cli.main(argv, io.StringIO(), io.StringIO())

        detect.assert_not_called()
        return code, call.call_args.args[0]

    def test_auto_login_turns_it_on_for_the_user_with_sudo(self):
        code, argv = self.run_auto_login(["--auto-login"], {"SUDO_USER": ""})

        self.assertEqual(code, 4)
        self.assertEqual(argv, ["sudo", "bash", str(cli.AUTO_LOGIN_SCRIPT), "daniel", "on"])

    def test_auto_login_off_under_sudo_keeps_the_real_user(self):
        _code, argv = self.run_auto_login(["--auto-login", "off"], {"SUDO_USER": "maria"}, euid=0)
        self.assertEqual(argv, ["bash", str(cli.AUTO_LOGIN_SCRIPT), "maria", "off"])

    def test_auto_login_script_ships_with_the_app(self):
        self.assertTrue(cli.AUTO_LOGIN_SCRIPT.is_file())

    def test_auto_login_refuses_other_states(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.parse_arguments(["--auto-login", "maybe"])

    def run_install(self, argv, target="HDMI-A-1", code=0):
        standard_output, error_output = io.StringIO(), io.StringIO()
        with mock.patch.object(cli.edid_setup, "target_output", return_value=target), mock.patch.object(
            cli.subprocess, "call", return_value=code
        ) as call, mock.patch.object(displays, "detect") as detect:
            result = cli.main(argv, standard_output, error_output)

        detect.assert_not_called()
        return result, standard_output.getvalue(), error_output.getvalue(), call

    def test_install_edid_on_the_picked_output_with_sudo(self):
        with mock.patch("os.geteuid", return_value=1000):
            code, standard_output, error_output, call = self.run_install(["--install-edid"])

        self.assertEqual((code, standard_output, error_output), (0, "Installing the virtual monitor on HDMI-A-1\n", ""))
        argv = call.call_args.args[0]
        self.assertEqual(argv[:3], ["sudo", "bash", str(cli.edid_setup.INSTALL_SCRIPT)])
        self.assertEqual(argv[-1], "HDMI-A-1")
        self.addCleanup(Path(argv[-2]).parent.rmdir)
        self.addCleanup(Path(argv[-2]).unlink)
        self.assertEqual(Path(argv[-2]).read_bytes(), cli.edid.generate(list(cli.edid.DEFAULT_MODES))[1])

    def test_install_edid_as_root_skips_sudo_and_passes_the_exit_status(self):
        with mock.patch("os.geteuid", return_value=0):
            code, _out, _error_output, call = self.run_install(["--install-edid", "--output", "DP-1", "--modes", "1920x1080"], code=3)

        argv = call.call_args.args[0]
        self.addCleanup(Path(argv[-2]).parent.rmdir)
        self.addCleanup(Path(argv[-2]).unlink)
        self.assertEqual(code, 3)
        self.assertEqual(argv[0], "bash")
        self.assertEqual(argv[-1], "DP-1")
        self.assertEqual(Path(argv[-2]).read_bytes(), cli.edid.generate(["1920x1080"])[1])

    def test_install_edid_without_free_output(self):
        code, _out, error_output, call = self.run_install(["--install-edid"], target=None)

        self.assertEqual((code, error_output), (1, cli.NO_FREE_OUTPUT + "\n"))
        call.assert_not_called()

    def test_install_edid_with_invalid_modes(self):
        code, _out, error_output, call = self.run_install(["--install-edid", "--modes", "100x100"])

        self.assertEqual(code, 1)
        self.assertEqual(error_output, "Invalid EDID: No safe clock fits 100x100 at 60 Hz\n")
        call.assert_not_called()

    def test_list_without_edid_on_boot(self):
        with mock.patch.object(displays, "command_line_connector", return_value=None):
            _, standard_output, _ = self.run_cli(["--list"])
        self.assertIn("(EDID at boot: no)", standard_output)

    def test_no_session_says_why_each_backend_failed(self):
        reasons = [("GNOME (Mutter)", "GNOME Shell is not running"), ("X11 (xrandr)", "xrandr --query: Can't open display :0")]
        with mock.patch.object(displays, "diagnose", return_value=reasons), mock.patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-1"}):
            code, standard_output, error_output = self.run_cli(["--list"], backend=None)

        self.assertEqual((code, standard_output), (1, ""))
        self.assertEqual(
            error_output.splitlines(),
            [
                "No supported video environment in this session:",
                "  GNOME (Mutter): GNOME Shell is not running",
                "  X11 (xrandr): xrandr --query: Can't open display :0",
            ],
        )

    def test_no_connector(self):
        code, _, error_output = self.run_cli(["--list"], backend=Backend({}))
        self.assertEqual(code, 1)
        self.assertIn("No monitor connected", error_output)

    def test_apply_remembers(self):
        code, standard_output, _ = self.run_cli(["--apply", "1920x1080@60.00"])

        self.assertEqual(code, 0)
        self.assertEqual(standard_output, "applied 1920x1080@60.00 on HDMI-1\n")
        self.assertEqual(self.backend.applied, [("HDMI-1", "1920x1080@60.00", True)])
        self.assertEqual(choice.load(), ("HDMI-1", "1920x1080@60.00"))

    def test_apply_temp_does_not_remember(self):
        code, _, _ = self.run_cli(["--apply", "1920x1080@60.00", "--temp"])

        self.assertEqual(code, 0)
        self.assertEqual(self.backend.applied, [("HDMI-1", "1920x1080@60.00", False)])
        self.assertIsNone(choice.load())

    def test_apply_failure(self):
        backend = Backend({"HDMI-1": []}, error=RuntimeError("xrandr: cannot find mode"))
        code, standard_output, error_output = self.run_cli(["--apply", "9x9@1"], backend=backend)

        self.assertEqual((code, standard_output), (1, ""))
        self.assertEqual(error_output, "Failed: xrandr: cannot find mode\n")
        self.assertIsNone(choice.load())

    def test_restore_with_choice(self):
        choice.save("HDMI-1", "3440x1440@59.24")
        code, standard_output, _ = self.run_cli(["--restore"])

        self.assertEqual((code, standard_output), (0, ""))
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
        code, _, error_output = self.run_cli(["--restore"], backend=Backend({}, error=RuntimeError("no output")))

        self.assertEqual(code, 1)
        self.assertIn("Failed: no output", error_output)

    def test_next_applies_the_mode_after_the_current_one(self):
        code, standard_output, _ = self.run_cli(["--next"])

        self.assertEqual(code, 0)
        self.assertEqual(standard_output, "applied 1920x1080@60.00 on HDMI-1\n")
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
        code, _, error_output = self.run_cli(["--next"], backend=Backend({"HDMI-1": []}))

        self.assertEqual(code, 1)
        self.assertEqual(error_output, "Failed: the output has no modes\n")

    def test_apply_with_scale_saves_it_for_the_size(self):
        code, _, _ = self.run_cli(["--apply", "1920x1080@60.00", "--scale", "1.25"])

        self.assertEqual(code, 0)
        self.assertEqual(choice.size_settings(1920, 1080), {"scale": 1.25})
        self.assertEqual(self.backend.last_change, displays.ModeChange("HDMI-1", "1920x1080@60.00", 1.25))

    def test_scale_alone_rescales_the_current_mode(self):
        code, standard_output, _ = self.run_cli(["--scale", "2"])

        self.assertEqual((code, standard_output), (0, "applied 2560x1080@59.98 on HDMI-1\n"))
        self.assertEqual(self.backend.last_change.scale, 2.0)
        self.assertEqual(choice.size_settings(2560, 1080), {"scale": 2.0})

    def test_scale_with_temp_does_not_remember_the_mode(self):
        self.run_cli(["--scale", "2", "--temp"])

        self.assertEqual(self.backend.last_change.scale, 2.0)
        self.assertIsNone(choice.load())

    def test_auto_scale_removes_the_saved_one(self):
        choice.save_setting(2560, 1080, "scale", 2.0)
        self.run_cli(["--scale", "auto"])

        self.assertEqual(choice.size_settings(2560, 1080), {})
        self.assertEqual(self.backend.last_change.scale, 1.0)

    def test_scale_without_current_mode_fails(self):
        code, _, error_output = self.run_cli(["--scale", "2"], backend=Backend({"HDMI-1": [mode("1920x1080@60.00")]}))

        self.assertEqual(code, 1)
        self.assertEqual(error_output, "Failed: the output has no current mode\n")

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

    def test_rotation_is_no_longer_an_option(self):
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(io.StringIO()):
            cli.parse_arguments(["--rotation", "left"])
        self.assertEqual(raised.exception.code, 2)

    def test_version(self):
        standard_output = io.StringIO()
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(standard_output):
            cli.parse_arguments(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(standard_output.getvalue(), f"virtual-monitor {__version__}\n")

    def test_options_are_exclusive(self):
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(io.StringIO()):
            cli.parse_arguments(["--list", "--restore"])
        self.assertEqual(raised.exception.code, 2)

        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.parse_arguments(["--next", "--apply", "m"])

    def test_temp_alone_lists(self):
        code, standard_output, _ = self.run_cli(["--temp"])

        self.assertEqual(code, 0)
        self.assertIn("session:", standard_output)
        self.assertEqual(self.backend.applied, [])

    def test_help(self):
        standard_output = io.StringIO()
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(standard_output):
            cli.parse_arguments(["--help"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--apply ID", standard_output.getvalue())


if __name__ == "__main__":
    unittest.main()
