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

    def test_built_in_panels_are_never_free(self):
        for name in ("card0-eDP-1", "card0-LVDS-1", "card0-DSI-1", "card0-DPI-1", "card0-Virtual-1", "card0-Writeback-1"):
            self.output(name, "disconnected")

        self.assertIsNone(edid_setup.free_output(self.drm))

    def test_dp_comes_before_dvi_and_dvi_before_the_rest(self):
        self.output("card1-DVI-D-1", "disconnected")
        self.output("card1-DP-1", "disconnected")
        self.assertEqual(edid_setup.free_output(self.drm), "DP-1")

        (self.drm / "card1-DP-1" / "status").write_text("connected\n")
        self.output("card1-Composite-1", "disconnected")
        self.assertEqual(edid_setup.free_output(self.drm), "DVI-D-1")

    def test_no_free_output(self):
        self.output("card1-HDMI-A-1", "connected")
        self.output("card0-eDP-1", "disconnected")
        self.assertIsNone(edid_setup.free_output(self.drm))

    def test_missing_drm_folder(self):
        self.assertEqual(edid_setup.external_outputs(self.drm / "missing"), [])
        self.assertIsNone(edid_setup.free_output(self.drm / "missing"))

    def test_target_is_the_output_of_this_boot(self):
        self.output("card1-DP-1", "disconnected")
        with mock.patch.object(displays, "command_line_connector", return_value="HDMI-A-1"):
            self.assertEqual(edid_setup.target_output(self.drm), "HDMI-A-1")

    def test_target_without_edid_at_boot_is_a_free_output(self):
        self.output("card1-DP-1", "disconnected")
        with mock.patch.object(displays, "command_line_connector", return_value=None):
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
        self.assertEqual(edid_setup.install_command(Path("/tmp/edid.bin"), "DP-1", ["sudo"]), ["sudo", "bash", script, "/tmp/edid.bin", "DP-1"])
        self.assertEqual(edid_setup.install_command(Path("/tmp/edid.bin"), "DP-1", []), ["bash", script, "/tmp/edid.bin", "DP-1"])

    def test_install_script_ships_with_the_app(self):
        self.assertTrue(edid_setup.INSTALL_SCRIPT.is_file())


def listed(width, height, refresh):
    return displays.Mode(f"{width}x{height}@{refresh}", width, height, refresh, False, False)


class ModesBackend(displays.Backend):
    """Lists the modes of each call in turn, the last one from then on; an exception is raised."""

    name = "Fake (test)"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def outputs(self):
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        if isinstance(answer, Exception):
            raise answer

        return {"HDMI-1": answer}

    def apply(self, change, persistent):
        raise AssertionError("not used")


class CustomSizeTest(unittest.TestCase):
    def test_custom_modes_put_the_size_first_then_the_defaults(self):
        self.assertEqual(edid_setup.custom_modes("2880x1800"), ["2880x1800", *edid.DEFAULT_MODES])

    def test_custom_modes_drop_the_default_of_the_same_size(self):
        self.assertEqual(
            edid_setup.custom_modes("3440x1440@350"),
            ["3440x1440@350", "2560x1080@216", "3008x1260@241.5", "2360x1640@297"],
        )

    def test_custom_modes_keep_a_default_of_the_same_width_only(self):
        self.assertIn("3440x1440@312", edid_setup.custom_modes("3440x1441"))
        self.assertIn("3440x1440@312", edid_setup.custom_modes("3441x1440"))

    def test_custom_modes_fit_in_the_edid(self):
        self.assertEqual(len(edid.generate(edid_setup.custom_modes("2880x1800"))[1]), 256)

    def test_custom_modes_refuse_an_invalid_size(self):
        with self.assertRaisesRegex(edid.EdidError, r"^Invalid mode: 2880 \(use WIDTHxHEIGHT\[@MHZ\]\[:HZ\]\)$"):
            edid_setup.custom_modes("2880")

    def test_size_mode_takes_the_rate_closest_to_the_timing(self):
        timing = edid.parse_mode("2880x1800")  # 56.3 Hz
        modes = [listed(2880, 1800, 60.0), listed(2880, 1800, 56.0), listed(2880, 1800, 50.0), listed(1920, 1080, 56.3)]
        self.assertEqual(edid_setup.size_mode(modes, timing), modes[1])
        self.assertEqual(edid_setup.size_mode(list(reversed(modes)), timing), modes[1])

    def test_size_mode_needs_width_and_height(self):
        timing = edid.parse_mode("2880x1800")
        self.assertIsNone(edid_setup.size_mode([listed(2880, 1864, 56.3), listed(2560, 1800, 56.3)], timing))
        self.assertIsNone(edid_setup.size_mode([], timing))

    def test_listed_mode_of_a_plain_size(self):
        modes = [listed(1920, 1080, 60.0), listed(2880, 1800, 56.3)]
        self.assertEqual(edid_setup.listed_mode(modes, "2880x1800"), modes[1])
        self.assertIsNone(edid_setup.listed_mode(modes, "2560x1600"))

    def test_listed_mode_with_a_clock_or_rate_needs_a_new_edid(self):
        modes = [listed(2880, 1800, 56.3)]
        self.assertIsNone(edid_setup.listed_mode(modes, "2880x1800@350"))
        self.assertIsNone(edid_setup.listed_mode(modes, "2880x1800:50"))

    def test_listed_mode_refuses_an_invalid_size(self):
        with self.assertRaises(edid.EdidError):
            edid_setup.listed_mode([], "2880x")

    def test_listed_modes_while_the_output_is_away(self):
        self.assertEqual(edid_setup.listed_modes(ModesBackend(displays.DisplayError("gone")), "HDMI-1"), [])
        self.assertEqual(edid_setup.listed_modes(ModesBackend([listed(1920, 1080, 60.0)]), "HDMI-1"), [listed(1920, 1080, 60.0)])

    def test_listed_modes_let_other_errors_through(self):
        with self.assertRaises(RuntimeError):
            edid_setup.listed_modes(ModesBackend(RuntimeError("bug")), "HDMI-1")

    def test_wait_for_size_checks_until_the_desktop_lists_it(self):
        wanted = listed(2880, 1800, 56.3)
        backend = ModesBackend([listed(1920, 1080, 60.0)], displays.DisplayError("gone"), [listed(1920, 1080, 60.0), wanted])
        with mock.patch.object(edid_setup.time, "sleep") as sleep:
            found = edid_setup.wait_for_size(backend, "HDMI-1", edid.parse_mode("2880x1800"))

        self.assertEqual(found, wanted)
        self.assertEqual(sleep.call_args_list, [mock.call(0.5), mock.call(0.5)])

    def test_wait_for_size_gives_up(self):
        backend = ModesBackend([listed(1920, 1080, 60.0)])
        with mock.patch.object(edid_setup.time, "sleep") as sleep:
            found = edid_setup.wait_for_size(backend, "HDMI-1", edid.parse_mode("2880x1800"))

        self.assertIsNone(found)
        self.assertEqual(backend.calls, 20)
        self.assertEqual(sleep.call_count, 20)

    def test_wait_takes_ten_seconds_at_most(self):
        self.assertEqual(edid_setup.WAIT_ATTEMPTS * edid_setup.WAIT_MILLISECONDS, 10000)

    def test_set_command(self):
        script = str(ROOT / "scripts" / "set-edid.sh")
        self.assertEqual(edid_setup.set_command(Path("/tmp/edid.bin"), "HDMI-A-1", ["pkexec"]), ["pkexec", "bash", script, "/tmp/edid.bin", "HDMI-A-1"])
        self.assertEqual(edid_setup.set_command(Path("/tmp/edid.bin"), "HDMI-A-1", []), ["bash", script, "/tmp/edid.bin", "HDMI-A-1"])

    def test_set_script_ships_with_the_app(self):
        self.assertTrue(edid_setup.SET_SCRIPT.is_file())


if __name__ == "__main__":
    unittest.main()
