import contextlib
import io
import math
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from virtual_monitor import edid

ROOT = Path(__file__).resolve().parent.parent


def decode_dtd(dtd):
    """Reads back the fields that detailed_timing writes."""
    return {
        "clock_khz": (dtd[0] | dtd[1] << 8) * 10,
        "width": dtd[2] | (dtd[4] >> 4) << 8,
        "hblank": dtd[3] | (dtd[4] & 0xF) << 8,
        "height": dtd[5] | (dtd[7] >> 4) << 8,
        "vblank": dtd[6] | (dtd[7] & 0xF) << 8,
    }


class BuildTimingTest(unittest.TestCase):
    def test_rockchip_modes_land_near_60_hz(self):
        cases = {
            (3440, 1440, 312): (3600, 1463, 59.24),
            (2560, 1080, 216): (2720, 1324, 59.98),
            (3008, 1260, 241.5): (3168, 1283, 59.42),
        }
        for (width, height, clock), (htotal, vtotal, hz) in cases.items():
            with self.subTest(mode=f"{width}x{height}@{clock}"):
                timing = edid.build_timing(width, height, clock)
                self.assertEqual((timing.htotal, timing.vtotal), (htotal, vtotal))
                self.assertAlmostEqual(timing.refresh, hz, places=2)
                self.assertEqual(timing.clock_khz, round(clock * 1000))

    def test_low_clock_keeps_minimum_blanking(self):
        timing = edid.build_timing(1920, 1080, 10)
        self.assertEqual(timing.htotal, 1920 + edid.H_BLANK_MIN)
        self.assertEqual(timing.vtotal, 1080 + edid.V_BLANK_MIN)

    def test_spare_clock_goes_to_vertical_blanking(self):
        timing = edid.build_timing(1280, 720, 148.5, 30)
        self.assertGreater(timing.vtotal, 720 + edid.V_BLANK_MIN)
        self.assertAlmostEqual(timing.refresh, 30, delta=0.1)

    def test_label(self):
        timing = edid.build_timing(3440, 1440, 312)
        self.assertEqual(timing.label(), "3440x1440 @ 312 MHz = 59.24 Hz")

    def test_rejects_sizes_outside_12_bits(self):
        for width, height in ((0, 1080), (1920, 0), (4096, 1080), (1920, 4096), (-1, 10)):
            with self.subTest(size=(width, height)), self.assertRaisesRegex(edid.EdidError, "Resolution"):
                edid.build_timing(width, height, 148.5)

    def test_accepts_the_12_bit_limit(self):
        timing = edid.build_timing(4095, 2160, 600, 30)
        self.assertEqual(timing.width, 4095)

    def test_rejects_non_positive_or_non_finite_clock_and_rate(self):
        for clock, hz in ((0, 60), (-1, 60), (math.nan, 60), (math.inf, 60), (148.5, 0), (148.5, math.nan), (148.5, -60)):
            with self.subTest(clock=clock, hz=hz), self.assertRaisesRegex(edid.EdidError, "positive"):
                edid.build_timing(1920, 1080, clock, hz)

    def test_rejects_clock_above_the_16_bit_field(self):
        with self.assertRaisesRegex(edid.EdidError, "655.35"):
            edid.build_timing(1920, 1080, 655.36)
        self.assertEqual(edid.build_timing(3840, 2160, 655.35, 75).clock_khz, 655350)

    def test_rejects_blanking_that_does_not_fit(self):
        with self.assertRaisesRegex(edid.EdidError, "too high"):
            edid.build_timing(640, 480, 600, 1)

    def test_horizontal_blanking_stays_near_minimum(self):
        for clock, hz in ((74.25, 24), (312, 60), (10, 120), (148.5, 30)):
            with self.subTest(clock=clock, hz=hz):
                timing = edid.build_timing(1920, 1080, clock, hz)
                self.assertLessEqual(timing.htotal - 1920, edid.H_BLANK_MIN + 1)


class ParseModeTest(unittest.TestCase):
    def test_default_rate_is_60(self):
        self.assertEqual(edid.parse_mode("2560x1080@216"), edid.build_timing(2560, 1080, 216, 60))

    def test_explicit_rate_and_uppercase_x(self):
        self.assertEqual(edid.parse_mode("2560X1080@216:50"), edid.build_timing(2560, 1080, 216, 50))

    def test_decimal_clock(self):
        self.assertEqual(edid.parse_mode("3008x1260@241.5").clock_khz, 241500)

    def test_malformed_modes(self):
        for text in ("", "abc", "3440x1440", "3440x1440@", "3440x1440@x", "1x2x3@100", "3440x1440@312:abc", "ax1@1"):
            with self.subTest(text=text), self.assertRaisesRegex(edid.EdidError, "Invalid mode"):
                edid.parse_mode(text)

    def test_range_errors_pass_through(self):
        with self.assertRaisesRegex(edid.EdidError, "Resolution"):
            edid.parse_mode("5000x1080@216")


class BytesTest(unittest.TestCase):
    def test_detailed_timing_round_trip(self):
        timing = edid.build_timing(3440, 1440, 312)
        dtd = edid.detailed_timing(timing)

        self.assertEqual(len(dtd), 18)
        self.assertEqual(
            decode_dtd(dtd),
            {"clock_khz": 312000, "width": 3440, "hblank": 160, "height": 1440, "vblank": 23},
        )
        self.assertEqual((dtd[8], dtd[9]), (edid.H_FRONT, edid.H_SYNC))
        self.assertEqual(dtd[10], (edid.V_FRONT << 4) | edid.V_SYNC)
        self.assertEqual(dtd[12] | (dtd[14] >> 4) << 8, edid.WIDTH_MM)
        self.assertEqual(dtd[13] | (dtd[14] & 0xF) << 8, edid.HEIGHT_MM)
        self.assertEqual(dtd[17], 0x1E)

    def test_name_descriptor_pads_short_names(self):
        self.assertEqual(edid.name_descriptor("UW"), b"\x00\x00\x00\xfc\x00UW\n" + b" " * 10)

    def test_name_descriptor_truncates_at_13(self):
        descriptor = edid.name_descriptor("ABCDEFGHIJKLMNOP")
        self.assertEqual(len(descriptor), 18)
        self.assertEqual(descriptor[5:], b"ABCDEFGHIJKLM")

    def test_name_descriptor_exact_13_has_no_newline(self):
        self.assertEqual(edid.name_descriptor("ABCDEFGHIJKLM")[5:], b"ABCDEFGHIJKLM")

    def test_name_descriptor_rejects_non_ascii(self):
        with self.assertRaisesRegex(edid.EdidError, "ASCII"):
            edid.name_descriptor("Résolution")

    def test_checksum_makes_block_sum_zero(self):
        block = bytearray(range(128))
        edid.checksum(block)
        self.assertEqual(sum(block) % 256, 0)

    def test_checksum_when_sum_already_zero(self):
        block = bytearray(128)
        edid.checksum(block)
        self.assertEqual(block[127], 0)

    def test_base_block(self):
        descriptor = bytes(range(18))
        block = edid.base_block([descriptor, descriptor])

        self.assertEqual(block[:8], b"\x00\xff\xff\xff\xff\xff\xff\x00")
        self.assertEqual(block[54:72], descriptor)
        self.assertEqual(block[72:90], descriptor)
        self.assertEqual(block[90:108], bytes(18))
        self.assertEqual((block[18], block[19]), (1, 3))
        self.assertEqual(block[126], 1)
        self.assertEqual(sum(block) % 256, 0)

    def test_cta_block_with_vics(self):
        block = edid.cta_block([16, 4], [])

        self.assertEqual(block[:2], b"\x02\x03")
        self.assertEqual(block[4:7], bytes([0x42, 16, 4]))
        self.assertEqual(block[7:10], bytes([0x67, 0x03, 0x0C]))
        self.assertEqual(block[2], 4 + 3 + 8)
        self.assertEqual(sum(block) % 256, 0)

    def test_cta_block_without_vics_starts_with_hdmi_block(self):
        block = edid.cta_block([], [])
        self.assertEqual(block[4], 0x67)
        self.assertEqual(block[2], 4 + 8)

    def test_cta_block_places_dtds_after_data(self):
        dtd = bytes([7] * 18)
        block = edid.cta_block([16], [dtd, dtd])
        start = 4 + 2 + 8

        self.assertEqual(block[start : start + 36], dtd * 2)

    def test_cta_block_fits_six_dtds_but_not_seven(self):
        dtd = bytes(18)
        edid.cta_block([], [dtd] * 6)
        with self.assertRaisesRegex(edid.EdidError, "Too many modes"):
            edid.cta_block([], [dtd] * 7)

    def test_cta_block_rejects_bad_vics(self):
        for vics in ([0], [128], [16] * 32):
            with self.subTest(vics=vics), self.assertRaisesRegex(edid.EdidError, "VIC"):
                edid.cta_block(vics, [])
        self.assertEqual(edid.cta_block([1, 127] + [16] * 29, [])[4], 0x40 | 31)


class BuildEdidTest(unittest.TestCase):
    def test_needs_a_mode(self):
        with self.assertRaisesRegex(edid.EdidError, "at least one mode"):
            edid.build_edid([], [16])

    def test_first_three_modes_in_base_rest_in_extension(self):
        timings = [edid.build_timing(1000 + i, 700, 100) for i in range(5)]
        data = edid.build_edid(timings, [])

        self.assertEqual(len(data), 256)
        self.assertEqual([decode_dtd(data[54 + 18 * i : 72 + 18 * i])["width"] for i in range(3)], [1000, 1001, 1002])
        self.assertEqual(data[108:113], b"\x00\x00\x00\xfc\x00")
        offset = 128 + data[130]
        self.assertEqual(decode_dtd(data[offset : offset + 18])["width"], 1003)
        self.assertEqual(decode_dtd(data[offset + 18 : offset + 36])["width"], 1004)

    def test_single_mode(self):
        data = edid.build_edid([edid.build_timing(1920, 1080, 148.5)], [16])

        self.assertEqual(decode_dtd(data[54:72])["width"], 1920)
        self.assertEqual(data[72:77], b"\x00\x00\x00\xfc\x00")
        self.assertEqual(sum(data[:128]) % 256, 0)
        self.assertEqual(sum(data[128:]) % 256, 0)

    def test_generate_reproduces_committed_rockchip_edid(self):
        timings, data = edid.generate(list(edid.DEFAULT_MODES))
        self.assertEqual(data, (ROOT / "edid" / "ultrawide-rockchip.bin").read_bytes())
        self.assertEqual([t.width for t in timings], [3440, 2560, 3008])

    def test_generate_propagates_errors(self):
        with self.assertRaises(edid.EdidError):
            edid.generate([])
        with self.assertRaises(edid.EdidError):
            edid.generate(["oi"])


class InstalledPathTest(unittest.TestCase):
    def test_is_where_the_install_script_copies_the_edid(self):
        script = (ROOT / "scripts" / "install-edid.sh").read_text()

        self.assertEqual(edid.INSTALLED, Path("/usr/lib/firmware/edid/ultrawide.bin"))
        self.assertIn('EDID_REL="edid/ultrawide.bin"', script)
        self.assertIn('EDID_DST="$ROOT/usr/lib/firmware/$EDID_REL"', script)


class IsInstalledTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.installed = Path(tmp.name) / "ultrawide.bin"
        patcher = mock.patch.object(edid, "INSTALLED", self.installed)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_same_modes_are_installed(self):
        self.installed.write_bytes(edid.generate(list(edid.DEFAULT_MODES))[1])

        self.assertTrue(edid.is_installed(list(edid.DEFAULT_MODES)))

    def test_other_modes_are_not_installed(self):
        self.installed.write_bytes(edid.generate(list(edid.DEFAULT_MODES))[1])

        self.assertFalse(edid.is_installed(["1920x1080@148.5"]))

    def test_nothing_installed(self):
        self.assertFalse(edid.is_installed(list(edid.DEFAULT_MODES)))

    def test_invalid_modes_are_not_installed(self):
        self.installed.write_bytes(b"")

        self.assertFalse(edid.is_installed([]))
        self.assertFalse(edid.is_installed(["oi"]))


class MainTest(unittest.TestCase):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = edid.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_writes_file_and_lists_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.bin"
            code, out, _ = self.run_main([str(path), "3440x1440@312", "2560x1080@216", "--vic", "16", "--vic", "4"])
            self.assertEqual(code, 0)
            self.assertEqual(len(path.read_bytes()), 256)
        self.assertEqual(
            out.splitlines(),
            ["3440x1440 @ 312 MHz = 59.24 Hz", "2560x1080 @ 216 MHz = 59.98 Hz", "VICs: 16 4"],
        )

    def test_without_vics_prints_no_vic_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = self.run_main([str(Path(tmp) / "x.bin"), "1920x1080@148.5", "--name", "Test"])
        self.assertEqual(code, 0)
        self.assertNotIn("VICs", out)

    def test_invalid_mode_returns_1_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.bin"
            code, out, err = self.run_main([str(path), "ruim"])
            self.assertFalse(path.exists())
        self.assertEqual((code, out), (1, ""))
        self.assertIn("Error: Invalid mode: ruim", err)

    def test_missing_modes_is_usage_error(self):
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(io.StringIO()):
            edid.main(["x.bin"])
        self.assertEqual(raised.exception.code, 2)

    def test_runs_as_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["edid", str(Path(tmp) / "x.bin"), "1920x1080@148.5"]
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    runpy.run_path(edid.__file__, run_name="__main__")
        self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
