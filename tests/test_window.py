import importlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import fake_gi

fake_gi.install()

from virtual_monitor import choice, displays, edid  # noqa: E402
from virtual_monitor import window as window_module  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def mode(mode_id, width, height, refresh, current=False, preferred=False):
    return displays.Mode(mode_id, width, height, refresh, current, preferred)


class Backend(displays.Backend):
    name = "X11 (xrandr)"
    native_persist = False

    def __init__(self, outputs):
        self._outputs = outputs
        self.applied = []
        self.error = None

    def outputs(self):
        return self._outputs

    def apply(self, connector, mode_id, persistent):
        if self.error:
            raise self.error
        self.applied.append((connector, mode_id, persistent))


def titles(widgets):
    return [w.init_props.get("title") for w in widgets]


class WindowTestCase(unittest.TestCase):
    def setUp(self):
        fake_gi.install()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.backend = Backend(
            {
                "HDMI-1": [
                    mode("3440x1440@59.24", 3440, 1440, 59.24, preferred=True),
                    mode("2560x1080@59.98", 2560, 1080, 59.98, current=True),
                ]
            }
        )
        self.cmdline = "HDMI-A-1"
        self.installed = self.tmp / "installed.bin"
        patches = [
            mock.patch.object(edid, "INSTALLED", self.installed),
            mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(self.tmp / "config")}),
            mock.patch.object(displays, "detect", side_effect=lambda: self.backend),
            mock.patch.object(displays, "cmdline_connector", side_effect=lambda: self.cmdline),
            mock.patch("tempfile.mkdtemp", side_effect=self.mkdtemp),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = fake_gi.Adw.Application("test")

    def mkdtemp(self, prefix):
        path = self.tmp / f"{prefix}x"
        path.mkdir()
        return str(path)

    def window(self):
        return window_module.Window(self.app)


class ModuleTest(unittest.TestCase):
    def test_requires_gtk4_and_libadwaita(self):
        fake_gi.install()
        fake_gi.gi.versions.clear()
        importlib.reload(window_module)

        self.assertEqual(fake_gi.gi.versions, {"Gtk": "4.0", "Adw": "1"})

    def test_install_script_ships_with_the_app(self):
        self.assertEqual(window_module.INSTALL_SCRIPT, ROOT / "scripts" / "install-edid.sh")
        self.assertTrue(window_module.INSTALL_SCRIPT.is_file())


class LayoutTest(WindowTestCase):
    def test_window_properties(self):
        window = self.window()
        props = window.init_props

        self.assertIs(props["application"], self.app)
        self.assertEqual((props["title"], props["default_width"], props["default_height"]), ("Virtual monitor", 520, 760))

    def test_page_has_three_groups(self):
        window = self.window()
        view = window.toasts.child

        self.assertIs(window.content, window.toasts)
        self.assertEqual(len(view.top_bars), 1)
        self.assertEqual(titles(view.content.children), ["Status", "Resolution", "EDID"])

    def test_status_rows(self):
        window = self.window()

        self.assertEqual(window.session_row.subtitle, "X11 (xrandr)")
        self.assertEqual(window.edid_row.subtitle, "active at boot (HDMI-A-1)")
        self.assertEqual(window.output_row.subtitle, "HDMI-1")

    def test_status_without_session_or_edid(self):
        self.backend = None
        self.cmdline = None
        window = self.window()

        self.assertIsNone(window.connector)
        self.assertEqual(window.session_row.subtitle, "unsupported video environment")
        self.assertEqual(window.edid_row.subtitle, "not configured at this boot")
        self.assertEqual(window.output_row.subtitle, "no monitor found")
        self.assertEqual(window.mode_rows, [])

    def test_session_without_monitor(self):
        self.backend = Backend({})
        window = self.window()

        self.assertEqual(window.output_row.subtitle, "no monitor found")
        self.assertEqual(window.mode_rows, [])

    def test_mode_rows(self):
        window = self.window()
        preferred, current = window.mode_rows

        self.assertEqual((preferred.init_props["title"], preferred.init_props["subtitle"]), ("3440×1440", "59.24 Hz"))
        self.assertTrue(preferred.activatable)
        self.assertEqual([s.init_props.get("label") for s in preferred.suffixes], ["default of the EDID"])
        self.assertEqual(preferred.suffixes[0].css_classes, ["dim-label"])
        self.assertEqual([s.init_props.get("icon_name") for s in current.suffixes], ["object-select-symbolic"])
        self.assertEqual(window.modes_group.children, [window.remember, preferred, current])

    def test_remember_is_on_by_default(self):
        self.assertTrue(self.window().remember.get_active())

    def test_edid_defaults(self):
        window = self.window()
        self.assertEqual(window.modes_entry.get_text(), "3440x1440@312 2560x1080@216 3008x1260@241.5")
        self.assertIn("suggested-action", window.install_button.css_classes)
        self.assertEqual(window.install_button.label, "Install")
        self.assertTrue(window.install_button.sensitive)

    def test_installed_edid_disables_install(self):
        self.installed.write_bytes(edid.generate(list(edid.DEFAULT_MODES))[1])
        window = self.window()

        self.assertEqual(window.install_button.label, "Installed")
        self.assertFalse(window.install_button.sensitive)

    def test_editing_the_modes_enables_install_again(self):
        self.installed.write_bytes(edid.generate(list(edid.DEFAULT_MODES))[1])
        window = self.window()
        window.modes_entry.set_text("1920x1080@148.5")
        window.modes_entry.emit("changed")

        self.assertEqual(window.install_button.label, "Install")
        self.assertTrue(window.install_button.sensitive)

    def test_refresh_replaces_mode_rows(self):
        window = self.window()
        old = list(window.mode_rows)
        self.backend._outputs = {"HDMI-1": [mode("1920x1080@60.00", 1920, 1080, 60.0, current=True)]}
        window.refresh()

        self.assertEqual(len(window.mode_rows), 1)
        for row in old:
            self.assertNotIn(row, window.modes_group.children)
        self.assertEqual(window.modes_group.children, [window.remember, window.mode_rows[0]])


class ModeTest(WindowTestCase):
    def test_activating_a_row_applies_and_remembers(self):
        window = self.window()
        window.mode_rows[0].emit("activated")

        self.assertEqual(self.backend.applied, [("HDMI-1", "3440x1440@59.24", True)])
        self.assertEqual(choice.load(), ("HDMI-1", "3440x1440@59.24"))
        self.assertEqual(window.toasts.toasts[-1].init_props["title"], "3440×1440 applied")

    def test_without_remember_applies_temporarily(self):
        window = self.window()
        window.remember.set_active(False)
        window.mode_rows[1].emit("activated")

        self.assertEqual(self.backend.applied, [("HDMI-1", "2560x1080@59.98", False)])
        self.assertIsNone(choice.load())

    def test_refreshes_once_after_applying(self):
        window = self.window()
        window.mode_rows[0].emit("activated")
        (delay, callback), = fake_gi.GLib.timeouts

        self.assertEqual(delay, 600)
        self.backend._outputs = {"HDMI-1": []}
        self.assertIs(callback(), fake_gi.GLib.SOURCE_REMOVE)
        self.assertEqual(window.mode_rows, [])

    def test_failure_shows_toast_and_does_not_refresh(self):
        window = self.window()
        self.backend.error = RuntimeError("xrandr: Configure crtc 0 failed")
        window.mode_rows[0].emit("activated")

        self.assertEqual(window.toasts.toasts[-1].init_props["title"], "Failed: xrandr: Configure crtc 0 failed")
        self.assertEqual(fake_gi.GLib.timeouts, [])
        self.assertIsNone(choice.load())


class InstallTest(WindowTestCase):
    def click_install(self, window, text=None):
        if text is not None:
            window.modes_entry.set_text(text)
        window.install_button.emit("clicked")

    def test_generates_edid_and_runs_installer_with_pkexec(self):
        window = self.window()
        self.click_install(window)
        (process,) = fake_gi.Subprocess.created
        out = Path(process.argv[-1])

        self.assertEqual(process.argv[:3], ["pkexec", "bash", str(window_module.INSTALL_SCRIPT)])
        self.assertEqual(out.name, "ultrawide-app.bin")
        self.assertTrue(out.parent.name.startswith("edid-"))
        self.assertEqual(out.read_bytes(), edid.generate(list(edid.DEFAULT_MODES))[1])
        self.assertEqual(process.flags, 3)
        self.assertFalse(window.install_button.sensitive)

    def test_uses_modes_typed_by_the_user(self):
        window = self.window()
        self.click_install(window, "  1920x1080@148.5   1280x720@74.25 ")
        out = Path(fake_gi.Subprocess.created[0].argv[-1])

        self.assertEqual(out.read_bytes(), edid.generate(["1920x1080@148.5", "1280x720@74.25"])[1])

    def test_invalid_modes_show_toast_without_running_anything(self):
        for text, message in (("", "at least one mode"), ("3440x1440", "Invalid mode"), ("9000x1@100", "Resolution")):
            with self.subTest(text=text):
                window = self.window()
                self.click_install(window, text)
                self.assertIn(message, window.toasts.toasts[-1].init_props["title"])
                self.assertTrue(window.toasts.toasts[-1].init_props["title"].startswith("Invalid EDID: "))
                self.assertEqual(fake_gi.Subprocess.created, [])
                self.assertTrue(window.install_button.sensitive)

    def test_cancelled_or_failed_install(self):
        window = self.window()
        self.click_install(window)
        fake_gi.Subprocess.created[0].finish(status=126)

        self.assertTrue(window.install_button.sensitive)
        self.assertEqual(window.toasts.toasts[-1].init_props["title"], "Install cancelled or failed")

    def test_subprocess_error_counts_as_failure(self):
        window = self.window()
        self.click_install(window)
        fake_gi.Subprocess.created[0].finish(error="pkexec not found")

        self.assertEqual(window.toasts.toasts[-1].init_props["title"], "Install cancelled or failed")

    def successful_install(self):
        window = self.window()
        self.click_install(window)
        fake_gi.Subprocess.created[0].finish(status=0, stdout="Done\n")
        (dialog,) = fake_gi.AlertDialog.created
        return window, dialog.init_props, dialog

    def test_success_asks_to_reboot(self):
        window, props, dialog = self.successful_install()

        self.assertTrue(window.install_button.sensitive)
        self.assertEqual(props, {"heading": "EDID installed", "body": "Restart for it to take effect. Restart now?"})
        self.assertEqual(dialog.responses, [("later", "Later"), ("reboot", "Restart")])
        self.assertEqual(dialog.appearances, {"reboot": "destructive"})
        self.assertEqual(dialog.presented_on, [window])

    def test_success_marks_the_new_edid_as_installed(self):
        window = self.window()
        self.click_install(window)
        self.installed.write_bytes(Path(fake_gi.Subprocess.created[0].argv[-1]).read_bytes())
        fake_gi.Subprocess.created[0].finish(status=0, stdout="Done\n")

        self.assertEqual(window.install_button.label, "Installed")
        self.assertFalse(window.install_button.sensitive)

    def test_reboot_response_reboots(self):
        _window, _props, dialog = self.successful_install()
        dialog.emit("response", "reboot")

        self.assertEqual(fake_gi.Subprocess.created[-1].argv, ["systemctl", "reboot"])
        self.assertEqual(fake_gi.Subprocess.created[-1].flags, 0)

    def test_later_response_does_nothing(self):
        _window, _props, dialog = self.successful_install()
        dialog.emit("response", "later")
        self.assertEqual(len(fake_gi.Subprocess.created), 1)


class RunAsyncTest(unittest.TestCase):
    def setUp(self):
        fake_gi.install()
        self.results = []

    def start(self):
        window_module.run_async(["true"], lambda ok, text: self.results.append((ok, text)))
        return fake_gi.Subprocess.created[-1]

    def test_success_passes_output(self):
        self.start().finish(status=0, stdout="pronto")
        self.assertEqual(self.results, [(True, "pronto")])

    def test_failure_status(self):
        self.start().finish(status=1, stdout="error")
        self.assertEqual(self.results, [(False, "error")])

    def test_missing_output_becomes_empty_text(self):
        self.start().finish(status=0, stdout=None)
        self.assertEqual(self.results, [(True, "")])

    def test_glib_error(self):
        self.start().finish(error="failed to read")
        self.assertEqual(self.results, [(False, "failed to read")])


class AppTest(WindowTestCase):
    def test_activate_creates_and_presents_window_once(self):
        app = window_module.App()

        self.assertEqual(app.application_id, "br.app.VirtualMonitor")
        app.do_activate()
        window = app.props.active_window
        self.assertIsInstance(window, window_module.Window)
        app.do_activate()
        self.assertIs(app.props.active_window, window)
        self.assertEqual(window.presented_on, [None, None])

    def test_run(self):
        self.assertEqual(window_module.run(), 0)
        app = fake_gi.Application.created[-1]

        self.assertIsInstance(app, window_module.App)
        self.assertEqual(app.run_args, [])
        self.assertEqual(fake_gi.GLib.prgnames, ["virtual-monitor"])
        self.assertEqual(fake_gi.Gtk.Window.default_icons, ["virtual-monitor"])
        self.assertIsInstance(app.props.active_window, window_module.Window)


if __name__ == "__main__":
    unittest.main()
