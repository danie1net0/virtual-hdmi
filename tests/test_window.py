import contextlib
import importlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import fake_gi

fake_gi.install()

from virtual_monitor import choice, displays, edid, edid_setup  # noqa: E402
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
        self.changes = []
        self.error = None

    def outputs(self):
        return self._outputs

    def apply(self, change, persistent):
        if self.error:
            raise self.error

        self.applied.append((change.connector, change.mode_id, persistent))
        self.changes.append(change)


def titles(widgets):
    return [widget.constructor_properties.get("title") for widget in widgets]


class WindowTestCase(unittest.TestCase):
    def setUp(self):
        fake_gi.install()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.temporary = Path(temporary.name)
        self.backend = Backend(
            {
                "HDMI-1": [
                    mode("3440x1440@59.24", 3440, 1440, 59.24, preferred=True),
                    mode("2560x1080@59.98", 2560, 1080, 59.98, current=True),
                ]
            }
        )
        self.command_line = "HDMI-A-1"
        self.output = "HDMI-A-1"
        self.installed = self.temporary / "installed.bin"
        patches = [
            mock.patch.object(edid, "INSTALLED", self.installed),
            mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(self.temporary / "configuration")}),
            mock.patch.object(displays, "detect", side_effect=lambda: self.backend),
            mock.patch.object(displays, "command_line_connector", side_effect=lambda: self.command_line),
            mock.patch.object(edid_setup, "target_output", side_effect=lambda: self.output),
            mock.patch("tempfile.mkdtemp", side_effect=self.make_temporary_folder),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        self.application = fake_gi.Adw.Application("test")

    def make_temporary_folder(self, prefix):
        path = self.temporary / f"{prefix}folder"
        path.mkdir()
        return str(path)

    def window(self):
        return window_module.Window(self.application)


class WindowGroupsTest(WindowTestCase):
    def test_each_group_holds_its_rows(self):
        window = self.window()

        status = window.build_status()
        current = window.build_current()

        self.assertEqual(status.children, [window.display_row, window.edid_row])
        self.assertEqual(current.children, [window.scale_row])

    def test_refresh_forgets_a_current_mode_that_is_gone(self):
        window = self.window()
        self.assertEqual(window.current.id, "2560x1080@59.98")

        self.backend._outputs = {"HDMI-1": [mode("3440x1440@59.24", 3440, 1440, 59.24)]}
        window.refresh()

        self.assertIsNone(window.current)

    def test_starts_with_no_switch_waiting_and_not_syncing(self):
        # Without a current mode, sync_current never sets syncing itself
        self.backend._outputs = {"HDMI-1": [mode("3440x1440@59.24", 3440, 1440, 59.24)]}
        window = self.window()

        self.assertIsNone(window.pending)
        self.assertIs(window.syncing, False)


class ModuleTest(unittest.TestCase):
    def test_the_launcher_is_named_after_the_application_id(self):
        # Wayland docks match the window to its launcher by this name; a mismatch shows a generic icon
        install = (Path(__file__).parent.parent / "install.sh").read_text()
        self.assertIn(f'APPLICATION_ID="{window_module.APPLICATION_ID}"', install)
        self.assertIn('LAUNCHER="$DATA/applications/$APPLICATION_ID.desktop"', install)

    def test_countdown_text(self):
        self.assertEqual(window_module.countdown_text(15), "Going back to the previous resolution in 15 s.")

    def test_requires_gtk4_and_libadwaita(self):
        fake_gi.install()
        fake_gi.gi.versions.clear()
        importlib.reload(window_module)

        self.assertEqual(fake_gi.gi.versions, {"Gtk": "4.0", "Adw": "1"})

    def test_install_script_ships_with_the_app(self):
        self.assertEqual(edid_setup.INSTALL_SCRIPT, ROOT / "scripts" / "install-edid.sh")
        self.assertTrue(edid_setup.INSTALL_SCRIPT.is_file())


class LayoutTest(WindowTestCase):
    def test_window_properties(self):
        window = self.window()
        properties = window.constructor_properties

        self.assertIs(properties["application"], self.application)
        self.assertEqual((properties["title"], properties["default_width"], properties["default_height"]), ("Virtual monitor", 520, 840))

    def test_main_page_has_status_and_resolution(self):
        window = self.window()
        main, edid_page = window.navigation.children
        view = main.constructor_properties["child"]

        self.assertIs(window.content, window.toasts)
        self.assertIs(window.toasts.child, window.navigation)
        self.assertEqual((main.constructor_properties["title"], main.constructor_properties["tag"]), ("Virtual monitor", "main"))
        self.assertEqual(len(view.top_bars), 1)
        self.assertEqual(titles(view.content.children), ["Status", "Current mode", "Resolution", "Other size"])
        self.assertIs(edid_page, window.edid_page)
        self.assertEqual(window.navigation.pushed, [])

    def test_edid_page_has_its_own_header(self):
        window = self.window()
        view = window.edid_page.constructor_properties["child"]
        (group,) = view.content.children

        self.assertEqual((window.edid_page.constructor_properties["title"], window.edid_page.constructor_properties["tag"]), ("Virtual EDID", "edid"))
        self.assertEqual(len(view.top_bars), 1)
        self.assertEqual(group.constructor_properties, {"description": window_module.EDID_HELP})
        self.assertEqual(group.children[0], window.modes_entry)
        self.assertIs(group.children[1], window.timings_row)
        self.assertEqual(group.children[2].suffixes, [window.install_button])

    def test_edid_row_opens_the_edid_page(self):
        window = self.window()
        window.edid_row.emit("activated")

        self.assertTrue(window.edid_row.activatable)
        self.assertEqual([suffix.constructor_properties.get("icon_name") for suffix in window.edid_row.suffixes], ["go-next-symbolic"])
        self.assertEqual(window.navigation.pushed, [window.edid_page])

    def test_status_rows(self):
        window = self.window()
        display, edid_row = window.display_row.constructor_properties, window.edid_row.constructor_properties

        self.assertEqual((display["title"], edid_row["title"]), ("Display", "Virtual EDID"))
        self.assertEqual(window.display_row.subtitle, "X11 (xrandr) · HDMI-1")
        self.assertEqual(window.edid_row.subtitle, "active at boot (HDMI-A-1)")

    def test_status_without_session_or_edid(self):
        self.backend = None
        self.command_line = None
        window = self.window()

        self.assertIsNone(window.connector)
        self.assertEqual(window.display_row.subtitle, "unsupported video environment")
        self.assertEqual(window.edid_row.subtitle, "not configured at this boot")
        self.assertEqual(window.mode_rows, [])

    def test_session_without_monitor(self):
        self.backend = Backend({})
        window = self.window()

        self.assertEqual(window.display_row.subtitle, "X11 (xrandr) · no monitor found")
        self.assertEqual(window.mode_rows, [])

    def test_mode_rows(self):
        window = self.window()
        preferred, current = window.mode_rows

        self.assertEqual((preferred.constructor_properties["title"], preferred.constructor_properties["subtitle"]), ("3440×1440", "59.24 Hz"))
        self.assertTrue(preferred.activatable)
        self.assertEqual([suffix.constructor_properties.get("label") for suffix in preferred.suffixes], ["default of the EDID"])
        self.assertEqual(preferred.suffixes[0].css_classes, ["dim-label"])
        self.assertEqual([suffix.constructor_properties.get("icon_name") for suffix in current.suffixes], ["object-select-symbolic"])
        self.assertEqual(window.modes_group.children, [window.remember, preferred, current])

    def test_remember_is_on_by_default(self):
        self.assertTrue(self.window().remember.get_active())

    def test_edid_defaults(self):
        window = self.window()
        self.assertEqual(window.modes_entry.get_text(), "3440x1440@312 2560x1080@216 3008x1260@241.5 2360x1640@297")
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

    def test_timings_preview_follows_the_modes(self):
        window = self.window()
        self.assertEqual(window.timings_row.constructor_properties["title"], "Timings")
        self.assertIn("property", window.timings_row.css_classes)
        self.assertEqual(
            window.timings_row.subtitle,
            "\n".join(timing.label() for timing in edid.generate(list(edid.DEFAULT_MODES))[0]),
        )

        window.modes_entry.set_text("2360x1640")
        window.modes_entry.emit("changed")
        self.assertEqual(window.timings_row.subtitle, "2360x1640 @ 297 MHz = 60.01 Hz")

        window.modes_entry.set_text("100x100")
        window.modes_entry.emit("changed")
        self.assertEqual(window.timings_row.subtitle, "Invalid: No safe clock fits 100x100 at 60 Hz")

    def test_refresh_replaces_mode_rows(self):
        window = self.window()
        old = list(window.mode_rows)
        self.backend._outputs = {"HDMI-1": [mode("1920x1080@60.00", 1920, 1080, 60.0, current=True)]}
        window.refresh()

        self.assertEqual(len(window.mode_rows), 1)
        for row in old:
            self.assertNotIn(row, window.modes_group.children)

        self.assertEqual(window.modes_group.children, [window.remember, window.mode_rows[0]])


class CurrentModeTest(WindowTestCase):
    def test_rows_show_the_current_mode_settings(self):
        window = self.window()

        self.assertEqual(window.current.id, "2560x1080@59.98")
        self.assertEqual(window.scale_row.constructor_properties["title"], "Scale")
        self.assertEqual(window.scale_row.constructor_properties["model"].strings, [label for label, _value in window_module.SCALES])
        self.assertEqual(window.scale_row.selected, 0)
        self.assertFalse(hasattr(window, "rotation_row"))
        self.assertEqual(window.scale_row.subtitle, "100% at 2560×1080")
        self.assertTrue(window.scale_row.sensitive)
        self.assertEqual(self.backend.applied, [])

    def test_rows_show_saved_settings_without_applying(self):
        choice.save_setting(2560, 1080, "scale", 1.25)
        window = self.window()

        self.assertEqual(window.scale_row.selected, 2)
        self.assertEqual(window.scale_row.subtitle, "125% at 2560×1080")
        self.assertEqual(self.backend.applied, [])

    def test_rows_are_off_without_current_mode(self):
        self.backend._outputs = {"HDMI-1": [mode("1920x1080@60.00", 1920, 1080, 60.0)]}
        window = self.window()

        self.assertIsNone(window.current)
        self.assertFalse(window.scale_row.sensitive)
        self.assertEqual(window.scale_row.subtitle, "no current mode")

    def test_changing_the_scale_saves_it_and_applies_again(self):
        window = self.window()
        window.scale_row.set_selected(3)

        self.assertEqual(choice.size_settings(2560, 1080), {"scale": 1.5})
        self.assertEqual(self.backend.changes, [displays.ModeChange("HDMI-1", "2560x1080@59.98", 1.5)])
        self.assertEqual(choice.load(), ("HDMI-1", "2560x1080@59.98"))

    def test_automatic_scale_removes_the_saved_one(self):
        choice.save_setting(2560, 1080, "scale", 2.0)
        window = self.window()
        window.scale_row.set_selected(0)

        self.assertEqual(choice.size_settings(2560, 1080), {})
        self.assertEqual(self.backend.changes[-1].scale, 1.0)

    def test_changing_the_scale_without_remembering_keeps_no_choice(self):
        window = self.window()
        window.remember.set_active(False)
        window.scale_row.set_selected(4)

        self.assertEqual(choice.size_settings(2560, 1080), {"scale": 1.75})
        self.assertEqual(self.backend.changes[-1].scale, 1.75)
        self.assertIsNone(choice.load())

    def test_setting_applies_to_the_mode_switched_by_another_app(self):
        window = self.window()
        self.backend._outputs = {
            "HDMI-1": [
                mode("3440x1440@59.24", 3440, 1440, 59.24, current=True),
                mode("2560x1080@59.98", 2560, 1080, 59.98),
            ]
        }
        window.scale_row.set_selected(2)

        self.assertEqual(choice.size_settings(3440, 1440), {"scale": 1.25})
        self.assertEqual(choice.size_settings(2560, 1080), {})
        self.assertEqual(self.backend.changes[-1], displays.ModeChange("HDMI-1", "3440x1440@59.24", 1.25))

    def test_setting_keeps_the_known_mode_when_none_is_current_now(self):
        window = self.window()
        self.backend._outputs = {"HDMI-1": [mode("2560x1080@59.98", 2560, 1080, 59.98)]}
        window.scale_row.set_selected(2)

        self.assertEqual(choice.size_settings(2560, 1080), {"scale": 1.25})
        self.assertEqual(self.backend.changes[-1].mode_id, "2560x1080@59.98")

    def test_failed_setting_change_keeps_the_choice_unsaved(self):
        window = self.window()
        self.backend.error = RuntimeError("refused")
        window.scale_row.set_selected(2)

        self.assertEqual(window.toasts.toasts[-1].constructor_properties["title"], "Failed: refused")
        self.assertIsNone(choice.load())

    def test_apply_says_whether_the_mode_took(self):
        window = self.window()
        self.assertIs(window.apply("2560x1080@59.98", False), True)

        self.backend.error = RuntimeError("refused")
        self.assertIs(window.apply("2560x1080@59.98", False), False)

    def test_setting_without_current_mode_does_nothing(self):
        self.backend._outputs = {"HDMI-1": [mode("1920x1080@60.00", 1920, 1080, 60.0)]}
        window = self.window()
        window.scale_row.set_selected(2)

        self.assertEqual(choice.load_settings(), {})
        self.assertEqual(self.backend.applied, [])

    def test_refresh_after_a_switch_shows_the_new_mode_settings(self):
        choice.save_setting(3440, 1440, "scale", 1.5)
        window = self.window()
        self.backend._outputs = {"HDMI-1": [mode("3440x1440@59.24", 3440, 1440, 59.24, current=True)]}
        window.refresh()

        self.assertEqual(window.scale_row.selected, 3)
        self.assertEqual(self.backend.applied, [])


class ModeTest(WindowTestCase):
    def switch(self, window, index=0):
        window.mode_rows[index].emit("activated")
        return fake_gi.AlertDialog.created[-1]

    def test_switch_applies_temporarily_and_asks_to_keep(self):
        window = self.window()
        dialog = self.switch(window)

        self.assertEqual(self.backend.applied, [("HDMI-1", "3440x1440@59.24", False)])
        self.assertEqual(window.toasts.toasts[-1].constructor_properties["title"], "3440×1440 applied")
        self.assertEqual(dialog.constructor_properties, {"heading": "Keep this resolution?", "body": window_module.countdown_text(15)})
        self.assertEqual(dialog.responses, [("revert", "Go back"), ("keep", "Keep")])
        self.assertEqual(dialog.appearances, {"keep": "suggested"})
        self.assertEqual(dialog.close_response, "revert")
        self.assertEqual(dialog.presented_on, [window])
        self.assertEqual(fake_gi.GLib.second_timeouts, [(1, window.count_down, (window.pending,))])
        self.assertIsNone(choice.load())

    def test_keep_remembers_the_mode(self):
        window = self.window()
        self.switch(window).emit("response", "keep")

        self.assertEqual(choice.load(), ("HDMI-1", "3440x1440@59.24"))
        self.assertIsNone(window.pending)
        self.assertEqual(len(self.backend.applied), 1)

    def test_keep_without_remember_saves_nothing(self):
        window = self.window()
        window.remember.set_active(False)
        self.switch(window).emit("response", "keep")

        self.assertIsNone(choice.load())

    def test_keep_on_gnome_applies_again_as_persistent(self):
        self.backend.native_persist = True
        window = self.window()
        self.switch(window).emit("response", "keep")

        self.assertEqual(self.backend.applied[-1], ("HDMI-1", "3440x1440@59.24", True))

    def test_keep_failure_shows_toast(self):
        self.backend.native_persist = True
        window = self.window()
        dialog = self.switch(window)
        self.backend.error = RuntimeError("monitors.xml")
        dialog.emit("response", "keep")

        self.assertEqual(window.toasts.toasts[-1].constructor_properties["title"], "Failed: monitors.xml")

    def test_go_back_restores_the_previous_mode(self):
        window = self.window()
        self.switch(window).emit("response", "revert")

        self.assertEqual(self.backend.applied[-1], ("HDMI-1", "2560x1080@59.98", False))
        self.assertEqual(window.toasts.toasts[-1].constructor_properties["title"], "Previous resolution restored")
        self.assertIsNone(choice.load())

    def test_failed_go_back_shows_toast(self):
        window = self.window()
        dialog = self.switch(window)
        self.backend.error = RuntimeError("no output")
        dialog.emit("response", "revert")

        self.assertEqual(window.toasts.toasts[-1].constructor_properties["title"], "Failed: no output")

    def test_countdown_goes_back_when_nobody_answers(self):
        window = self.window()
        dialog = self.switch(window)
        (_seconds, count_down, (pending,)), = fake_gi.GLib.second_timeouts

        for remaining in range(14, 0, -1):
            self.assertIs(count_down(pending), fake_gi.GLib.SOURCE_CONTINUE)
            self.assertEqual(dialog.body, window_module.countdown_text(remaining))

        self.assertEqual(len(self.backend.applied), 1)

        self.assertIs(count_down(pending), fake_gi.GLib.SOURCE_REMOVE)
        self.assertTrue(dialog.force_closed)
        self.assertIsNone(window.pending)
        self.assertEqual(self.backend.applied[-1], ("HDMI-1", "2560x1080@59.98", False))

    def test_answer_after_the_countdown_is_ignored(self):
        window = self.window()
        dialog = self.switch(window)
        window.pending.remaining = 1
        window.count_down(window.pending)
        dialog.emit("response", "keep")

        self.assertEqual(len(self.backend.applied), 2)
        self.assertIsNone(choice.load())

    def test_countdown_stops_after_an_answer(self):
        window = self.window()
        dialog = self.switch(window)
        (_seconds, count_down, (pending,)), = fake_gi.GLib.second_timeouts
        dialog.emit("response", "keep")

        self.assertIs(count_down(pending), fake_gi.GLib.SOURCE_REMOVE)
        self.assertEqual(pending.remaining, 15)

    def test_old_countdown_does_not_touch_a_newer_switch(self):
        window = self.window()
        first = self.switch(window)
        first.emit("response", "keep")
        self.switch(window)
        (_seconds, old_count_down, (old_pending,)) = fake_gi.GLib.second_timeouts[0]

        self.assertIs(old_count_down(old_pending), fake_gi.GLib.SOURCE_REMOVE)
        self.assertEqual(window.pending.remaining, 15)

    def test_current_mode_applies_without_asking(self):
        window = self.window()
        window.mode_rows[1].emit("activated")

        self.assertEqual(fake_gi.AlertDialog.created, [])
        self.assertEqual(self.backend.applied, [("HDMI-1", "2560x1080@59.98", False)])
        self.assertEqual(choice.load(), ("HDMI-1", "2560x1080@59.98"))

    def test_without_current_mode_applies_without_asking(self):
        self.backend._outputs = {"HDMI-1": [mode("1920x1080@60.00", 1920, 1080, 60.0)]}
        window = self.window()
        window.remember.set_active(False)
        window.mode_rows[0].emit("activated")

        self.assertEqual(fake_gi.AlertDialog.created, [])
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

        self.assertEqual(window.toasts.toasts[-1].constructor_properties["title"], "Failed: xrandr: Configure crtc 0 failed")
        self.assertEqual(fake_gi.GLib.timeouts, [])
        self.assertEqual(fake_gi.AlertDialog.created, [])
        self.assertIsNone(choice.load())


class SizeTest(WindowTestCase):
    def type_size(self, window, text):
        window.size_entry.set_text(text)
        window.size_entry.emit("apply")

    def new_size(self, text="2880x1800"):
        """Types a size the output does not list and lets set-edid.sh succeed; returns the window and the wait."""
        window = self.window()
        self.type_size(window, text)
        fake_gi.Subprocess.created[-1].finish(0)
        (milliseconds, wait), = fake_gi.GLib.timeouts
        self.assertEqual(milliseconds, 500)
        fake_gi.GLib.timeouts.clear()
        return window, wait

    def list_new_mode(self):
        self.backend._outputs["HDMI-1"].append(mode("2880x1800@56.30", 2880, 1800, 56.3))

    def test_size_group(self):
        window = self.window()
        view = window.navigation.children[0].constructor_properties["child"]
        group = view.content.children[-1]

        self.assertEqual(group.constructor_properties, {"title": "Other size", "description": window_module.SIZE_HELP})
        self.assertEqual(group.children, [window.size_entry])
        self.assertEqual(window.size_entry.constructor_properties, {"title": "Size, like 2880x1800", "show_apply_button": True})
        self.assertTrue(window.size_entry.sensitive)

    def test_size_needs_a_monitor(self):
        self.backend = Backend({})
        window = self.window()

        self.assertFalse(window.size_entry.sensitive)

    def test_listed_size_switches_and_asks_to_keep(self):
        window = self.window()
        self.type_size(window, " 3440x1440 ")

        self.assertEqual(self.backend.applied, [("HDMI-1", "3440x1440@59.24", False)])
        self.assertEqual(window.pending.previous_id, "2560x1080@59.98")
        self.assertEqual(fake_gi.Subprocess.created, [])

    def test_current_size_applies_without_asking(self):
        window = self.window()
        self.type_size(window, "2560x1080")

        self.assertEqual(self.backend.applied, [("HDMI-1", "2560x1080@59.98", False)])
        self.assertIsNone(window.pending)
        self.assertEqual(choice.load(), ("HDMI-1", "2560x1080@59.98"))

    def test_invalid_size_shows_toast(self):
        window = self.window()
        self.type_size(window, "2880")

        self.assertEqual(window.toasts.toasts[-1].constructor_properties["title"], "Invalid size: Invalid mode: 2880 (use WIDTHxHEIGHT[@MHZ][:HZ])")
        self.assertEqual(fake_gi.Subprocess.created, [])
        self.assertEqual(self.backend.applied, [])

    def test_new_size_needs_the_virtual_monitor(self):
        self.command_line = None
        window = self.window()
        self.type_size(window, "2880x1800")

        self.assertEqual(window.toasts.toasts[-1].constructor_properties["title"], edid_setup.NOT_INSTALLED)
        self.assertEqual(fake_gi.Subprocess.created, [])
        self.assertTrue(window.size_entry.sensitive)

    def test_new_size_runs_set_edid_with_pkexec(self):
        window = self.window()
        self.type_size(window, "  2880x1800 ")
        (process,) = fake_gi.Subprocess.created
        written = Path(process.command[-2])

        self.assertEqual(process.command[:3], ["pkexec", "bash", str(edid_setup.SET_SCRIPT)])
        self.assertEqual(process.command[-1], "HDMI-A-1")
        self.assertEqual(written.read_bytes(), edid.generate(edid_setup.custom_modes("2880x1800"))[1])
        self.assertFalse(window.size_entry.sensitive)
        self.assertEqual(fake_gi.GLib.timeouts, [])

    def test_failed_set_edid_shows_toast(self):
        window = self.window()
        self.type_size(window, "2880x1800")
        fake_gi.Subprocess.created[-1].finish(126)

        self.assertTrue(window.size_entry.sensitive)
        self.assertEqual(window.toasts.toasts[-1].constructor_properties["title"], "Cancelled or failed: the EDID did not change")
        self.assertEqual(fake_gi.GLib.timeouts, [])

    def test_new_size_switches_once_listed_and_asks_to_keep(self):
        window, wait = self.new_size()
        self.assertTrue(window.size_entry.sensitive)

        self.assertIs(wait(), fake_gi.GLib.SOURCE_CONTINUE)
        self.assertEqual(self.backend.applied, [])

        self.list_new_mode()
        self.assertIs(wait(), fake_gi.GLib.SOURCE_REMOVE)
        self.assertEqual(self.backend.applied, [("HDMI-1", "2880x1800@56.30", False)])
        self.assertEqual((window.pending.mode_id, window.pending.previous_id), ("2880x1800@56.30", "2560x1080@59.98"))

    def test_new_size_gives_up_after_the_last_check(self):
        window, wait = self.new_size()
        answers = [wait() for _attempt in range(edid_setup.WAIT_ATTEMPTS)]

        self.assertEqual(answers, [fake_gi.GLib.SOURCE_CONTINUE] * (edid_setup.WAIT_ATTEMPTS - 1) + [fake_gi.GLib.SOURCE_REMOVE])
        self.assertEqual(window.toasts.toasts[-1].constructor_properties["title"], "The desktop does not list 2880×1800")
        self.assertEqual(self.backend.applied, [])

    def test_giving_up_shows_the_modes_again(self):
        window, wait = self.new_size()
        rows = window.mode_rows
        for _attempt in range(edid_setup.WAIT_ATTEMPTS):
            wait()

        self.assertIsNot(window.mode_rows, rows)

    def test_wait_survives_the_output_going_away(self):
        window, wait = self.new_size()
        # While the output is off, the display tool fails
        with mock.patch.object(self.backend, "outputs", side_effect=displays.DisplayError("gone")):
            self.assertIs(wait(), fake_gi.GLib.SOURCE_CONTINUE)

        self.list_new_mode()
        self.assertIs(wait(), fake_gi.GLib.SOURCE_REMOVE)


class HelpersTest(unittest.TestCase):
    def test_choice_index(self):
        self.assertEqual(window_module.choice_index(window_module.SCALES, 1.5), 3)
        self.assertEqual(window_module.choice_index(window_module.SCALES, 1.1), 0)


class InstallTest(WindowTestCase):
    def click_install(self, window, text=None):
        if text is not None:
            window.modes_entry.set_text(text)

        window.install_button.emit("clicked")

    def test_generates_edid_and_runs_installer_with_pkexec(self):
        window = self.window()
        self.click_install(window)
        (process,) = fake_gi.Subprocess.created
        written = Path(process.command[-2])

        self.assertEqual(process.command[:3], ["pkexec", "bash", str(edid_setup.INSTALL_SCRIPT)])
        self.assertEqual(process.command[-1], "HDMI-A-1")
        self.assertEqual(written.name, "virtual-monitor.bin")
        self.assertTrue(written.parent.name.startswith("edid-"))
        self.assertEqual(written.read_bytes(), edid.generate(list(edid.DEFAULT_MODES))[1])
        self.assertEqual(process.flags, 3)
        self.assertFalse(window.install_button.sensitive)

    def test_uses_modes_typed_by_the_user(self):
        window = self.window()
        self.click_install(window, "  1920x1080@148.5   1280x720@74.25 ")
        written = Path(fake_gi.Subprocess.created[0].command[-2])

        self.assertEqual(written.read_bytes(), edid.generate(["1920x1080@148.5", "1280x720@74.25"])[1])

    def test_modes_without_clock_install_on_safe_clocks(self):
        window = self.window()
        self.click_install(window, "2360x1640 1920x1200")
        written = Path(fake_gi.Subprocess.created[0].command[-2])

        self.assertEqual(written.read_bytes(), edid.generate(["2360x1640@297", "1920x1200@200"])[1])

    def test_invalid_modes_show_toast_without_running_anything(self):
        for text, message in (("", "at least one mode"), ("3440x1440@x", "Invalid mode"), ("100x100", "No safe clock"), ("9000x1@100", "Resolution")):
            with self.subTest(text=text):
                window = self.window()
                self.click_install(window, text)
                self.assertIn(message, window.toasts.toasts[-1].constructor_properties["title"])
                self.assertTrue(window.toasts.toasts[-1].constructor_properties["title"].startswith("Invalid EDID: "))
                self.assertEqual(fake_gi.Subprocess.created, [])
                self.assertTrue(window.install_button.sensitive)

    def test_without_free_output_shows_toast_without_running_anything(self):
        self.output = None
        window = self.window()
        self.click_install(window)

        self.assertEqual(window.toasts.toasts[-1].constructor_properties["title"], window_module.NO_FREE_OUTPUT)
        self.assertEqual(fake_gi.Subprocess.created, [])

    def test_install_row_names_the_output(self):
        self.assertEqual(window_module.install_subtitle("DP-1"), "On DP-1. Asks for the administrator password.")
        self.assertEqual(window_module.install_subtitle(None), "No free video output found.")
        window = self.window()
        view = window.edid_page.constructor_properties["child"]
        (group,) = view.content.children
        self.assertEqual(group.children[2].constructor_properties["subtitle"], "On HDMI-A-1. Asks for the administrator password.")

    def test_cancelled_or_failed_install(self):
        window = self.window()
        self.click_install(window)
        fake_gi.Subprocess.created[0].finish(status=126)

        self.assertTrue(window.install_button.sensitive)
        self.assertEqual(window.toasts.toasts[-1].constructor_properties["title"], "Install cancelled or failed")
        self.assertEqual(fake_gi.AlertDialog.created, [])

    def test_subprocess_error_counts_as_failure(self):
        window = self.window()
        self.click_install(window)
        fake_gi.Subprocess.created[0].finish(error="pkexec not found")

        self.assertEqual(window.toasts.toasts[-1].constructor_properties["title"], "Install cancelled or failed")

    def successful_install(self):
        window = self.window()
        self.click_install(window)
        fake_gi.Subprocess.created[0].finish(status=0, output="Done\n")
        (dialog,) = fake_gi.AlertDialog.created
        return window, dialog.constructor_properties, dialog

    def test_success_asks_to_reboot(self):
        window, properties, dialog = self.successful_install()

        self.assertTrue(window.install_button.sensitive)
        self.assertEqual(properties, {"heading": "EDID installed", "body": "Restart for it to take effect. Restart now?"})
        self.assertEqual(dialog.responses, [("later", "Later"), ("reboot", "Restart")])
        self.assertEqual(dialog.appearances, {"reboot": "destructive"})
        self.assertEqual(dialog.presented_on, [window])

    def test_success_marks_the_new_edid_as_installed(self):
        window = self.window()
        self.click_install(window)
        self.installed.write_bytes(Path(fake_gi.Subprocess.created[0].command[-2]).read_bytes())
        fake_gi.Subprocess.created[0].finish(status=0, output="Done\n")

        self.assertEqual(window.install_button.label, "Installed")
        self.assertFalse(window.install_button.sensitive)

    def test_reboot_response_reboots(self):
        _window, _properties, dialog = self.successful_install()
        dialog.emit("response", "reboot")

        self.assertEqual(fake_gi.Subprocess.created[-1].command, ["systemctl", "reboot"])
        self.assertEqual(fake_gi.Subprocess.created[-1].flags, 0)

    def test_later_response_does_nothing(self):
        _window, _properties, dialog = self.successful_install()
        dialog.emit("response", "later")
        self.assertEqual(len(fake_gi.Subprocess.created), 1)


class RunAsyncTest(unittest.TestCase):
    def setUp(self):
        fake_gi.install()
        self.results = []

    def start(self):
        window_module.run_async(["true"], lambda succeeded, text: self.results.append((succeeded, text)))
        return fake_gi.Subprocess.created[-1]

    def test_success_passes_output(self):
        self.start().finish(status=0, output="pronto")
        self.assertEqual(self.results, [(True, "pronto")])

    def test_failure_status(self):
        self.start().finish(status=1, output="error")
        self.assertEqual(self.results, [(False, "error")])

    def test_missing_output_becomes_empty_text(self):
        self.start().finish(status=0, output=None)
        self.assertEqual(self.results, [(True, "")])

    def test_glib_error(self):
        self.start().finish(error="failed to read")
        self.assertEqual(self.results, [(False, "failed to read")])


class ApplicationTest(WindowTestCase):
    def test_activate_creates_and_presents_window_once(self):
        application = window_module.VirtualMonitorApplication()

        self.assertEqual(application.application_id, "br.app.VirtualMonitor")
        application.do_activate()
        window = application.props.active_window
        self.assertIsInstance(window, window_module.Window)
        application.do_activate()
        self.assertIs(application.props.active_window, window)
        self.assertEqual(window.presented_on, [None, None])

    def test_run_without_display_explains_and_fails(self):
        fake_gi.Gtk.displays[0] = False
        applications_before = len(fake_gi.Application.created)
        error_output = io.StringIO()
        with contextlib.redirect_stderr(error_output):
            self.assertEqual(window_module.run(), 1)

        self.assertEqual(error_output.getvalue(), window_module.NO_DISPLAY + "\n")
        self.assertEqual(len(fake_gi.Application.created), applications_before)
        self.assertEqual(fake_gi.GLib.program_names, [])

    def test_run(self):
        self.assertEqual(window_module.run(), 0)
        application = fake_gi.Application.created[-1]

        self.assertIsInstance(application, window_module.VirtualMonitorApplication)
        self.assertEqual(application.run_arguments, [])
        self.assertEqual(fake_gi.GLib.program_names, ["virtual-monitor"])
        self.assertEqual(fake_gi.Gtk.Window.default_icons, ["virtual-monitor"])
        self.assertIsInstance(application.props.active_window, window_module.Window)


if __name__ == "__main__":
    unittest.main()
