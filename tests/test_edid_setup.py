import tempfile
import unittest
from pathlib import Path
from unittest import mock

from virtual_monitor import displays, edid, edid_setup

ROOT = Path(__file__).resolve().parent.parent


class DrmTestCase(unittest.TestCase):
    """A fake /sys/class/drm: card folders, outputs with a status file, and other entries."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.drm = Path(folder.name)
        (self.drm / "card1").mkdir()
        (self.drm / "version").write_text("drm 1.1.0\n")

    def output(self, name, status):
        folder = self.drm / name
        folder.mkdir()
        (folder / "status").write_text(f"{status}\n")


class OutputsTest(DrmTestCase):
    def test_connector_name(self):
        self.assertEqual(edid_setup.connector_name(Path("card1-HDMI-A-1")), "HDMI-A-1")
        self.assertEqual(edid_setup.connector_name(Path("card10-DP-3")), "DP-3")
        self.assertIsNone(edid_setup.connector_name(Path("card1")))
        self.assertIsNone(edid_setup.connector_name(Path("renderD128")))

    def test_external_outputs_skip_built_in_panels_and_other_entries(self):
        self.output("card1-HDMI-A-1", "connected")
        self.output("card1-DP-2", "disconnected")
        self.output("card0-eDP-1", "connected")
        self.output("card0-Writeback-1", "unknown")
        (self.drm / "card1-DP-3").mkdir()

        self.assertEqual(edid_setup.external_outputs(self.drm), [("DP-2", "disconnected"), ("HDMI-A-1", "connected")])

    def test_free_output_prefers_hdmi_then_dp_then_dvi(self):
        self.output("card1-DVI-D-1", "disconnected")
        self.output("card1-DP-1", "disconnected")
        self.output("card1-HDMI-A-2", "disconnected")
        self.output("card1-HDMI-A-1", "connected")
        self.output("card1-VGA-1", "disconnected")
        self.assertEqual(edid_setup.free_output(self.drm), "HDMI-A-2")

    def test_free_output_by_name_within_the_same_kind(self):
        self.output("card1-DP-3", "disconnected")
        self.output("card1-DP-1", "disconnected")
        self.assertEqual(edid_setup.free_output(self.drm), "DP-1")

    def test_free_output_of_other_kinds(self):
        self.output("card1-VGA-1", "disconnected")
        self.output("card1-DVI-I-1", "disconnected")
        self.assertEqual(edid_setup.free_output(self.drm), "DVI-I-1")
        self.assertEqual(edid_setup.preference("VGA-1"), (3, "VGA-1"))

    def test_no_free_output(self):
        self.output("card1-HDMI-A-1", "connected")
        self.output("card0-eDP-1", "disconnected")
        self.assertIsNone(edid_setup.free_output(self.drm))

    def test_missing_drm_folder(self):
        self.assertEqual(edid_setup.external_outputs(self.drm / "missing"), [])
        self.assertIsNone(edid_setup.free_output(self.drm / "missing"))

    def test_target_is_the_output_of_this_boot(self):
        self.output("card1-DP-1", "disconnected")
        with mock.patch.object(displays, "cmdline_connector", return_value="HDMI-A-1"):
            self.assertEqual(edid_setup.target_output(self.drm), "HDMI-A-1")

    def test_target_without_edid_at_boot_is_a_free_output(self):
        self.output("card1-DP-1", "disconnected")
        with mock.patch.object(displays, "cmdline_connector", return_value=None):
            self.assertEqual(edid_setup.target_output(self.drm), "DP-1")

    def test_default_folder(self):
        self.assertEqual(edid_setup.DRM, Path("/sys/class/drm"))


class InstallTest(unittest.TestCase):
    def test_write_edid_generates_the_modes(self):
        path = edid_setup.write_edid(["1920x1080@148.5"])
        self.addCleanup(path.parent.rmdir)
        self.addCleanup(path.unlink)

        self.assertEqual(path.name, "virtual-monitor.bin")
        self.assertTrue(path.parent.name.startswith("edid-"))
        self.assertEqual(path.read_bytes(), edid.generate(["1920x1080@148.5"])[1])

    def test_write_edid_refuses_invalid_modes(self):
        with self.assertRaises(edid.EdidError):
            edid_setup.write_edid(["nope"])

    def test_install_command(self):
        script = str(ROOT / "scripts" / "install-edid.sh")
        self.assertEqual(edid_setup.install_command(Path("/tmp/e.bin"), "DP-1", ["sudo"]), ["sudo", "bash", script, "/tmp/e.bin", "DP-1"])
        self.assertEqual(edid_setup.install_command(Path("/tmp/e.bin"), "DP-1", []), ["bash", script, "/tmp/e.bin", "DP-1"])

    def test_install_script_ships_with_the_app(self):
        self.assertTrue(edid_setup.INSTALL_SCRIPT.is_file())


if __name__ == "__main__":
    unittest.main()
