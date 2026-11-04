import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from virtual_monitor import choice

ROOT = Path(__file__).resolve().parent.parent


class Backend:
    def __init__(self, native_persist=False):
        self.native_persist = native_persist
        self.applied = []

    def apply(self, connector, mode_id, persistent):
        self.applied.append((connector, mode_id, persistent))


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

    def test_restore_reapplies_temporarily(self):
        choice.save("HDMI-1", "m")
        backend = Backend()

        self.assertTrue(choice.restore(backend))
        self.assertEqual(backend.applied, [("HDMI-1", "m", False)])

    def test_restore_without_choice(self):
        backend = Backend()
        self.assertFalse(choice.restore(backend))
        self.assertEqual(backend.applied, [])


if __name__ == "__main__":
    unittest.main()
