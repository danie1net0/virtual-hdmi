import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from virtual_monitor import choice, displays

ROOT = Path(__file__).resolve().parent.parent
IPAD = displays.Mode("ipad", 2360, 1640, 60.0, True, False)
WIDE = displays.Mode("wide", 3440, 1440, 59.24, False, True)


class Backend(displays.Backend):
    def __init__(self, native_persist=False):
        self.native_persist = native_persist
        self.applied = []

    def outputs(self):
        return {"HDMI-1": [IPAD, WIDE]}

    def apply(self, change, persistent):
        self.applied.append((change.connector, change.mode_id, persistent))
        self.last_change = change


class ConfigTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        patcher = mock.patch("pathlib.Path.home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_uses_absolute_xdg_config_home(self):
        with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": "/xdg"}):
            self.assertEqual(choice.config_dir(), Path("/xdg"))

    def test_ignores_relative_or_missing_xdg(self):
        for env in ({"XDG_CONFIG_HOME": "rel"}, {}):
            with self.subTest(env=env), mock.patch.dict("os.environ", env, clear=True):
                self.assertEqual(choice.config_dir(), self.home / ".config")

    def test_files(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(choice.choice_file(), self.home / ".config/virtual-monitor/mode.json")
            self.assertEqual(choice.autostart_file(), self.home / ".config/autostart/virtual-monitor-restore.desktop")
            self.assertEqual(choice.settings_file(), self.home / ".config/virtual-monitor/settings.json")


class SaveLoadTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config = Path(tmp.name) / "config"
        patcher = mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(self.config)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_launcher_is_the_project_entry_point(self):
        self.assertEqual(choice.LAUNCHER, ROOT / "virtual-monitor.py")
        self.assertTrue(choice.LAUNCHER.is_file())

    def test_save_writes_choice_and_autostart(self):
        choice.save("HDMI-1", "2560x1080@59.98")

        self.assertEqual(
            json.loads((self.config / "virtual-monitor/mode.json").read_text()),
            {"connector": "HDMI-1", "mode": "2560x1080@59.98"},
        )
        entry = (self.config / "autostart/virtual-monitor-restore.desktop").read_text()
        self.assertIn(f'Exec=python3 "{choice.LAUNCHER}" --restore\n', entry)
        self.assertTrue(entry.startswith("[Desktop Entry]\nType=Application\n"))
        self.assertIn("NoDisplay=true\n", entry)

    def test_save_overwrites(self):
        choice.save("HDMI-1", "a")
        choice.save("HDMI-1", "b")
        self.assertEqual(choice.load(), ("HDMI-1", "b"))

    def test_load_without_file(self):
        self.assertIsNone(choice.load())

    def test_load_broken_files(self):
        path = self.config / "virtual-monitor/mode.json"
        path.parent.mkdir(parents=True)
        for text in ("{", "[]", '{"connector": "HDMI-1"}', "null"):
            with self.subTest(text=text):
                path.write_text(text)
                self.assertIsNone(choice.load())


class SettingsTest(SaveLoadTest):
    def settings_path(self):
        return self.config / "virtual-monitor/settings.json"

    def test_without_file_there_are_no_settings(self):
        self.assertEqual(choice.load_settings(), {})
        self.assertEqual(choice.size_settings(2360, 1640), {})

    def test_broken_files_count_as_empty(self):
        self.settings_path().parent.mkdir(parents=True)
        for text in ("{", "[]", "null"):
            with self.subTest(text=text):
                self.settings_path().write_text(text)
                self.assertEqual(choice.load_settings(), {})

    def test_size_entry_that_is_not_a_map_counts_as_empty(self):
        self.settings_path().parent.mkdir(parents=True)
        self.settings_path().write_text('{"2360x1640": 1.5}')
        self.assertEqual(choice.size_settings(2360, 1640), {})

    def test_save_setting_keeps_each_size_apart(self):
        choice.save_setting(2360, 1640, "scale", 1.25)
        choice.save_setting(2360, 1640, "rotation", "left")
        choice.save_setting(3440, 1440, "scale", 1.0)

        self.assertEqual(
            json.loads(self.settings_path().read_text()),
            {"2360x1640": {"rotation": "left", "scale": 1.25}, "3440x1440": {"scale": 1.0}},
        )

    def test_none_removes_the_setting_and_then_the_size(self):
        choice.save_setting(2360, 1640, "scale", 1.25)
        choice.save_setting(2360, 1640, "rotation", "left")
        choice.save_setting(2360, 1640, "scale", None)
        self.assertEqual(choice.size_settings(2360, 1640), {"rotation": "left"})

        choice.save_setting(2360, 1640, "rotation", None)
        self.assertEqual(choice.load_settings(), {})

    def test_change_uses_auto_scale_without_settings(self):
        change = choice.change_for(Backend(), "HDMI-1", "ipad")
        self.assertEqual(change, displays.ModeChange("HDMI-1", "ipad", 1.5, "normal"))
        self.assertEqual(choice.change_for(Backend(), "HDMI-1", "wide").scale, 1.0)

    def test_change_uses_saved_scale_and_rotation(self):
        choice.save_setting(2360, 1640, "scale", 2)
        choice.save_setting(2360, 1640, "rotation", "right")

        change = choice.change_for(Backend(), "HDMI-1", "ipad")
        self.assertEqual(change, displays.ModeChange("HDMI-1", "ipad", 2.0, "right"))
        self.assertIsInstance(change.scale, float)

    def test_change_ignores_invalid_saved_values(self):
        for scale, rotation in (("big", "upside"), (0, None), (-1, 3), (True, "")):
            with self.subTest(scale=scale, rotation=rotation):
                choice.save_setting(2360, 1640, "scale", scale)
                choice.save_setting(2360, 1640, "rotation", rotation)
                self.assertEqual(choice.change_for(Backend(), "HDMI-1", "ipad"), displays.ModeChange("HDMI-1", "ipad", 1.5))

    def test_change_of_unknown_mode_has_the_defaults(self):
        self.assertEqual(choice.change_for(Backend(), "HDMI-1", "missing"), displays.ModeChange("HDMI-1", "missing"))


class ApplyRestoreTest(SaveLoadTest):
    def test_apply_persistent_saves_when_backend_does_not(self):
        backend = Backend()
        choice.apply_mode(backend, "HDMI-1", "m", True)

        self.assertEqual(backend.applied, [("HDMI-1", "m", True)])
        self.assertEqual(choice.load(), ("HDMI-1", "m"))

    def test_apply_temporary_does_not_save(self):
        choice.apply_mode(Backend(), "HDMI-1", "m", False)
        self.assertIsNone(choice.load())

    def test_apply_on_native_backend_does_not_save(self):
        backend = Backend(native_persist=True)
        choice.apply_mode(backend, "HDMI-1", "m", True)

        self.assertEqual(backend.applied, [("HDMI-1", "m", True)])
        self.assertIsNone(choice.load())

    def test_apply_failure_saves_nothing(self):
        backend = Backend()
        backend.apply = mock.Mock(side_effect=RuntimeError("refused"))
        with self.assertRaises(RuntimeError):
            choice.apply_mode(backend, "HDMI-1", "m", True)

        self.assertIsNone(choice.load())

    def test_apply_passes_the_saved_settings(self):
        choice.save_setting(2360, 1640, "rotation", "left")
        backend = Backend()
        choice.apply_mode(backend, "HDMI-1", "ipad", False)

        self.assertEqual(backend.last_change, displays.ModeChange("HDMI-1", "ipad", 1.5, "left"))

    def test_commit_saves_the_choice(self):
        backend = Backend()
        choice.commit(backend, "HDMI-1", "ipad")

        self.assertEqual(choice.load(), ("HDMI-1", "ipad"))
        self.assertEqual(backend.applied, [])

    def test_commit_on_native_backend_applies_again_as_persistent(self):
        backend = Backend(native_persist=True)
        choice.commit(backend, "HDMI-1", "ipad")

        self.assertEqual(backend.applied, [("HDMI-1", "ipad", True)])
        self.assertEqual(backend.last_change.scale, 1.5)
        self.assertIsNone(choice.load())

    def test_restore_reapplies_temporarily(self):
        choice.save("HDMI-1", "m")
        backend = Backend()

        self.assertTrue(choice.restore(backend))
        self.assertEqual(backend.applied, [("HDMI-1", "m", False)])

    def test_restore_uses_the_saved_settings(self):
        choice.save("HDMI-1", "ipad")
        choice.save_setting(2360, 1640, "scale", 1.25)
        backend = Backend()
        choice.restore(backend)

        self.assertEqual(backend.last_change, displays.ModeChange("HDMI-1", "ipad", 1.25))

    def test_restore_without_choice(self):
        backend = Backend()
        self.assertFalse(choice.restore(backend))
        self.assertEqual(backend.applied, [])


if __name__ == "__main__":
    unittest.main()
