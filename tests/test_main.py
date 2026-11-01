import runpy
import sys
import unittest
from pathlib import Path
from unittest import mock

from tests import fake_gi

import virtual_monitor.__main__ as entry

ROOT = Path(__file__).resolve().parent.parent


class MainTest(unittest.TestCase):
    def setUp(self):
        fake_gi.install()

    def test_arguments_go_to_cli(self):
        with mock.patch("virtual_monitor.cli.main", return_value=3) as cli_main:
            self.assertEqual(entry.main(["--list"]), 3)
        cli_main.assert_called_once_with(["--list"])

    def test_no_arguments_opens_window(self):
        with mock.patch("virtual_monitor.window.run", return_value=0) as run:
            self.assertEqual(entry.main([]), 0)
        run.assert_called_once_with()

    def test_reads_sys_argv_by_default(self):
        with mock.patch.object(sys, "argv", ["virtual-monitor", "--restore"]), mock.patch(
            "virtual_monitor.cli.main", return_value=0
        ) as cli_main:
            entry.main()
        cli_main.assert_called_once_with(["--restore"])

    def run_script(self, path, argv):
        with mock.patch.object(sys, "argv", argv), mock.patch("virtual_monitor.cli.main", return_value=5) as cli_main:
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(path), run_name="__main__")
        return raised.exception.code, cli_main

    def test_python_dash_m(self):
        code, cli_main = self.run_script(Path(entry.__file__), ["virtual_monitor", "--list"])
        self.assertEqual(code, 5)
        cli_main.assert_called_once_with(["--list"])

    def test_launcher_script(self):
        launcher = ROOT / "virtual-monitor.py"
        code, cli_main = self.run_script(launcher, [str(launcher), "--apply", "x", "--temp"])
        self.assertEqual(code, 5)
        cli_main.assert_called_once_with(["--apply", "x", "--temp"])

    def test_launcher_puts_its_folder_first_on_the_path(self):
        launcher = ROOT / "virtual-monitor.py"
        with mock.patch.object(sys, "path", list(sys.path)):
            runpy.run_path(str(launcher), run_name="launcher")
            self.assertEqual(sys.path[0], str(ROOT))


if __name__ == "__main__":
    unittest.main()
