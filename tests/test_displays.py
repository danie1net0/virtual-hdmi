import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from virtual_monitor import displays
from tests import fake_gi

XRANDR = """Screen 0: minimum 320 x 200, current 3440 x 1440, maximum 16384 x 16384
   640x480       60.00
HDMI-1 connected primary 3440x1440+0+0 (normal left inverted right x axis y axis) 800mm x 335mm
   3440x1440     59.24*+
   2560x1080     59.98
   1920x1080     60.00 +  59.94
   1280x720      60.00 *
   1920x1080i    30.00
  h: width  3440 start 3488 end 3520 total 3600 skew    0 clock  88.67KHz
HDMI-2 disconnected (normal left inverted right x axis y axis)
   1024x768      60.00
DP-1 connected 1920x1080+3440+0 (normal) 530mm x 300mm
   1920x1080     60.00*+
"""

WLR = json.dumps(
    [
        {
            "name": "HDMI-A-1",
            "modes": [
                {"width": 3440, "height": 1440, "refresh": 59.239, "preferred": True, "current": True},
                {"width": 1920, "height": 1080, "refresh": 60.0, "preferred": False, "current": False},
            ],
        },
        {"name": "eDP-1"},
    ]
)

KSCREEN = json.dumps(
    {
        "outputs": [
            {
                "name": "HDMI-A-1",
                "connected": True,
                "currentModeId": "2",
                "preferredModes": ["1"],
                "modes": [
                    {"id": "1", "size": {"width": 3440, "height": 1440}, "refreshRate": 59.239},
                    {"id": 2, "size": {"width": 1920, "height": 1080}, "refreshRate": 60.0},
                ],
            },
            {"name": "HDMI-A-2", "connected": False, "modes": []},
            {"name": "DP-1", "connected": True, "preferredModes": []},
        ]
    }
)


def mutter_monitor(connector, *modes):
    """Monitor in the GetCurrentState format; each mode is (id, current, preferred)."""
    return (
        (connector, "VHD", "Virtual", "0"),
        [(mode_id, 1920, 1080, 60.0, 1.0, [1.0], {"is-current": cur, "is-preferred": pref}) for mode_id, cur, pref in modes],
        {},
    )


def sized_mutter_monitor(connector, width, height, scales):
    """Monitor with a single non-current mode "big" of the given size and supported scales."""
    return ((connector, "VHD", "Virtual", "0"), [("big", width, height, 60.0, 1.0, scales, {})], {})


def logical(x, primary, *connectors):
    return (x, 0, 1.0, 0, primary, [(c, "VHD", "Virtual", "0") for c in connectors], {})


class FakeBackend(displays.Backend):
    def __init__(self, outputs):
        self._outputs = outputs

    def outputs(self):
        return self._outputs


class ParseXrandrTest(unittest.TestCase):
    def setUp(self):
        self.outputs = displays.parse_xrandr(XRANDR)

    def test_lists_connected_outputs_only(self):
        self.assertEqual(list(self.outputs), ["HDMI-1", "DP-1"])

    def test_flags_and_ids(self):
        modes = {m.id: m for m in self.outputs["HDMI-1"]}

        self.assertTrue(modes["3440x1440@59.24"].current)
        self.assertTrue(modes["3440x1440@59.24"].preferred)
        self.assertFalse(modes["2560x1080@59.98"].current)
        self.assertFalse(modes["2560x1080@59.98"].preferred)
        self.assertTrue(modes["1920x1080@60.00"].preferred)
        self.assertFalse(modes["1920x1080@59.94"].preferred)
        self.assertTrue(modes["1280x720@60.00"].current)
        self.assertEqual(modes["2560x1080@59.98"].refresh, 59.98)

    def test_skips_interlaced_and_detail_lines(self):
        ids = [m.id for m in self.outputs["HDMI-1"]]
        self.assertNotIn("1920x1080@30.00", ids)
        self.assertEqual(len(ids), 5)

    def test_ignores_modes_of_disconnected_and_before_any_output(self):
        all_ids = [m.id for modes in self.outputs.values() for m in modes]
        self.assertNotIn("1024x768@60.00", all_ids)
        self.assertNotIn("640x480@60.00", all_ids)

    def test_empty_text(self):
        self.assertEqual(displays.parse_xrandr(""), {})

    def test_ignores_stray_tokens(self):
        text = "HDMI-1 connected\n   800x600   +  60.32 junk 56.25*\n"
        modes = displays.parse_xrandr(text)["HDMI-1"]
        self.assertEqual([(m.id, m.current, m.preferred) for m in modes], [("800x600@60.32", False, False), ("800x600@56.25", True, False)])


class ParseOtherBackendsTest(unittest.TestCase):
    def test_wlr(self):
        outputs = displays.parse_wlr(WLR)
        modes = outputs["HDMI-A-1"]

        self.assertEqual([m.id for m in modes], ["3440x1440@59.239", "1920x1080@60.000"])
        self.assertTrue(modes[0].current and modes[0].preferred)
        self.assertFalse(modes[1].current or modes[1].preferred)
        self.assertEqual(outputs["eDP-1"], [])

    def test_kscreen(self):
        outputs = displays.parse_kscreen(KSCREEN)

        self.assertEqual(list(outputs), ["HDMI-A-1", "DP-1"])
        first, second = outputs["HDMI-A-1"]
        self.assertEqual((first.id, second.id), ("1", "2"))
        self.assertTrue(first.preferred and not first.current)
        self.assertTrue(second.current and not second.preferred)
        self.assertEqual(outputs["DP-1"], [])

    def test_kscreen_without_outputs(self):
        self.assertEqual(displays.parse_kscreen("{}"), {})

    def test_mutter(self):
        monitors = [mutter_monitor("HDMI-1", ("a", True, False), ("b", False, True)), mutter_monitor("DP-1")]
        outputs = displays.parse_mutter(monitors)

        self.assertEqual(list(outputs), ["HDMI-1", "DP-1"])
        a, b = outputs["HDMI-1"]
        self.assertEqual((a.id, a.width, a.height, a.refresh), ("a", 1920, 1080, 60.0))
        self.assertTrue(a.current and not a.preferred)
        self.assertTrue(b.preferred and not b.current)

    def test_normalize_matches_kernel_and_mutter_names(self):
        self.assertEqual(displays.normalize("HDMI-A-1"), "HDMI-1")
        self.assertEqual(displays.normalize("DP-2"), "DP-2")
        self.assertEqual(displays.normalize(None), "")


class AutoScaleTest(unittest.TestCase):
    def test_tablet_modes_scale(self):
        for width, height in ((2360, 1640), (2560, 1600), (2048, 1536), (1640, 2360)):
            with self.subTest(size=(width, height)):
                self.assertEqual(displays.auto_scale(width, height), 1.5)

    def test_other_modes_keep_1x(self):
        for width, height in ((3440, 1440), (3008, 1260), (1920, 1200), (1920, 1080), (2700, 1500)):
            with self.subTest(size=(width, height)):
                self.assertEqual(displays.auto_scale(width, height), 1.0)

    def test_find_mode_looks_up_the_mode(self):
        ipad = displays.Mode("ipad", 2360, 1640, 60.0, False, False)
        backend = FakeBackend({"HDMI-1": [ipad]})

        self.assertIs(backend.find_mode("HDMI-1", "ipad"), ipad)
        self.assertIsNone(backend.find_mode("HDMI-1", "missing"))
        self.assertIsNone(backend.find_mode("DP-1", "ipad"))


class ModeChangeTest(unittest.TestCase):
    def test_defaults_to_1x_without_rotation(self):
        change = displays.ModeChange("HDMI-1", "m")
        self.assertEqual((change.scale, change.rotation), (1.0, "normal"))

    def test_accepts_every_rotation(self):
        for rotation in displays.ROTATIONS:
            with self.subTest(rotation=rotation):
                self.assertEqual(displays.ModeChange("HDMI-1", "m", 1.5, rotation).rotation, rotation)

    def test_refuses_unknown_rotation(self):
        with self.assertRaisesRegex(ValueError, "Unknown rotation: inverted"):
            displays.ModeChange("HDMI-1", "m", 1.0, "inverted")

    def test_refuses_scale_that_is_not_positive(self):
        for scale in (0, -1.5):
            with self.subTest(scale=scale), self.assertRaisesRegex(ValueError, "scale must be positive"):
                displays.ModeChange("HDMI-1", "m", scale)

    def test_every_rotation_has_a_transform(self):
        self.assertEqual(set(displays.WLR_TRANSFORMS), set(displays.ROTATIONS))
        self.assertEqual(set(displays.MUTTER_TRANSFORMS), set(displays.ROTATIONS))


class SetXfceDpiTest(unittest.TestCase):
    def test_sets_dpi_from_scale(self):
        with mock.patch("shutil.which", return_value="/usr/bin/xfconf-query"), mock.patch.object(displays, "run") as run:
            displays.set_xfce_dpi(1.5)
        run.assert_called_once_with(["xfconf-query", "-c", "xsettings", "-p", "/Xft/DPI", "-n", "-t", "int", "-s", "144"])

    def test_skips_without_xfconf(self):
        with mock.patch("shutil.which", return_value=None), mock.patch.object(displays, "run") as run:
            displays.set_xfce_dpi(1.5)
        run.assert_not_called()


def change(connector, mode_id, scale=1.0, rotation="normal"):
    return displays.ModeChange(connector, mode_id, scale, rotation)


class MutterScaleTest(unittest.TestCase):
    def test_picks_closest_supported_scale(self):
        cases = (([1.0, 1.25, 1.5, 2.0], 1.5, 1.5), ([1.0, 2.0], 1.5, 1.0), ([2.0], 1.0, 2.0), ([1.0, 1.25, 2.0], 1.25, 1.25))
        for scales, wanted, expected in cases:
            with self.subTest(scales=scales, wanted=wanted):
                monitors = [sized_mutter_monitor("HDMI-1", 2360, 1640, scales)]
                self.assertEqual(displays.mutter_scale(monitors, change("HDMI-1", "big", wanted)), expected)

    def test_unknown_mode_is_1x(self):
        monitors = [sized_mutter_monitor("HDMI-1", 2360, 1640, [1.5])]
        self.assertEqual(displays.mutter_scale(monitors, change("HDMI-1", "other", 1.5)), 1.0)
        self.assertEqual(displays.mutter_scale(monitors, change("DP-1", "big", 1.5)), 1.0)

    def test_layout_scales_and_rotates_only_the_target_connector(self):
        monitors = [sized_mutter_monitor("HDMI-1", 2360, 1640, [1.0, 1.5]), mutter_monitor("DP-1", ("c", True, False))]
        dp_logical = (2360, 0, 2.0, 2, False, [("DP-1", "VHD", "Virtual", "0")], {})
        layout = displays.mutter_layout(monitors, [logical(0, True, "HDMI-1"), dp_logical], change("HDMI-1", "big", 1.5, "left"))
        self.assertEqual(
            layout,
            [(0, 0, 1.5, 1, True, [("HDMI-1", "big", {})]), (2360, 0, 2.0, 2, False, [("DP-1", "c", {})])],
        )

    def test_layout_adds_missing_connector_with_its_scale_and_rotation(self):
        monitors = [sized_mutter_monitor("HDMI-1", 2360, 1640, [1.0, 1.5])]
        layout = displays.mutter_layout(monitors, [], change("HDMI-1", "big", 1.5, "right"))
        self.assertEqual(layout, [(0, 0, 1.5, 3, True, [("HDMI-1", "big", {})])])


class MutterLayoutTest(unittest.TestCase):
    def test_changes_only_the_target_connector(self):
        monitors = [mutter_monitor("HDMI-1", ("a", True, False), ("b", False, False)), mutter_monitor("DP-1", ("c", True, False))]
        layout = displays.mutter_layout(monitors, [logical(0, True, "HDMI-1"), logical(3440, False, "DP-1")], change("HDMI-1", "b"))
        self.assertEqual(
            layout,
            [(0, 0, 1.0, 0, True, [("HDMI-1", "b", {})]), (3440, 0, 1.0, 0, False, [("DP-1", "c", {})])],
        )

    def test_drops_logical_monitors_without_current_mode(self):
        monitors = [mutter_monitor("HDMI-1", ("a", True, False)), mutter_monitor("DP-1", ("c", False, False))]
        layout = displays.mutter_layout(monitors, [logical(0, True, "HDMI-1"), logical(1, False, "DP-1")], change("HDMI-1", "a"))
        self.assertEqual(layout, [(0, 0, 1.0, 0, True, [("HDMI-1", "a", {})])])

    def test_adds_connector_missing_from_layout_as_primary_when_alone(self):
        monitors = [mutter_monitor("HDMI-1", ("a", False, True))]
        self.assertEqual(displays.mutter_layout(monitors, [], change("HDMI-1", "a")), [(0, 0, 1.0, 0, True, [("HDMI-1", "a", {})])])

    def test_adds_connector_missing_from_layout_as_secondary(self):
        monitors = [mutter_monitor("HDMI-1", ("a", False, True)), mutter_monitor("DP-1", ("c", True, False))]
        layout = displays.mutter_layout(monitors, [logical(0, True, "DP-1")], change("HDMI-1", "a"))
        self.assertEqual(layout[-1], (0, 0, 1.0, 0, False, [("HDMI-1", "a", {})]))


class RunTest(unittest.TestCase):
    def test_returns_stdout(self):
        self.assertEqual(displays.run([sys.executable, "-c", "print('hi')"]), "hi\n")

    def test_raises_on_failure(self):
        with self.assertRaises(subprocess.CalledProcessError):
            displays.run([sys.executable, "-c", "raise SystemExit(3)"])


class CommandBackendsTest(unittest.TestCase):
    def check_available(self, cls, env, tool):
        cases = [
            (env, f"/usr/bin/{tool}", True),
            (env, None, False),
            ({}, f"/usr/bin/{tool}", False),
        ]
        for environ, which, expected in cases:
            with self.subTest(env=environ, which=which):
                with mock.patch.dict("os.environ", environ, clear=True), mock.patch("shutil.which", return_value=which):
                    self.assertIs(cls.available(), expected)

    def test_available(self):
        self.check_available(displays.XrandrBackend, {"DISPLAY": ":0"}, "xrandr")
        self.check_available(displays.WlrBackend, {"WAYLAND_DISPLAY": "wayland-0"}, "wlr-randr")
        self.check_available(displays.KScreenBackend, {"XDG_CURRENT_DESKTOP": "KDE"}, "kscreen-doctor")

    def test_kscreen_needs_kde_desktop(self):
        with mock.patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "XFCE"}), mock.patch("shutil.which", return_value="/x"):
            self.assertFalse(displays.KScreenBackend.available())

    def test_xrandr(self):
        backend = displays.XrandrBackend()
        with mock.patch.object(displays, "run", return_value=XRANDR) as run, mock.patch("shutil.which", return_value=None):
            self.assertEqual(backend.connectors(), ["HDMI-1", "DP-1"])
            self.assertEqual(len(backend.modes("HDMI-1")), 5)
            run.assert_called_with(["xrandr", "--query"])
            backend.apply(change("HDMI-1", "2560x1080@59.98"), True)
            run.assert_called_with(
                ["xrandr", "--output", "HDMI-1", "--mode", "2560x1080", "--rate", "59.98", "--rotate", "normal"]
            )

    def test_wlr(self):
        backend = displays.WlrBackend()
        with mock.patch.object(displays, "run", return_value=WLR) as run:
            self.assertEqual(backend.connectors(), ["HDMI-A-1", "eDP-1"])
            run.assert_called_with(["wlr-randr", "--json"])
            backend.apply(change("HDMI-A-1", "1920x1080@60.000"), False)
            run.assert_called_with(
                ["wlr-randr", "--output", "HDMI-A-1", "--mode", "1920x1080@60.000Hz", "--scale", "1", "--transform", "normal"]
            )

    def test_kscreen(self):
        backend = displays.KScreenBackend()
        with mock.patch.object(displays, "run", return_value=KSCREEN) as run:
            self.assertEqual(backend.connectors(), ["HDMI-A-1", "DP-1"])
            run.assert_called_with(["kscreen-doctor", "-j"])
            backend.apply(change("HDMI-A-1", "2"), False)
            run.assert_called_with(
                ["kscreen-doctor", "output.HDMI-A-1.mode.2", "output.HDMI-A-1.scale.1", "output.HDMI-A-1.rotation.normal"]
            )

    def test_xrandr_rotates_and_sets_xfce_dpi_after_the_mode(self):
        with mock.patch.object(displays, "run") as run, mock.patch("shutil.which", return_value="/usr/bin/xfconf-query"):
            displays.XrandrBackend().apply(change("HDMI-1", "2360x1640@60.01", 1.5, "left"), True)

        self.assertEqual(
            run.call_args_list[0].args[0],
            ["xrandr", "--output", "HDMI-1", "--mode", "2360x1640", "--rate", "60.01", "--rotate", "left"],
        )
        self.assertEqual(run.call_args_list[1].args[0][-1], "144")

    def test_wlr_passes_fractional_scale_and_transform(self):
        for rotation, transform in (("left", "90"), ("right", "270")):
            with self.subTest(rotation=rotation), mock.patch.object(displays, "run") as run:
                displays.WlrBackend().apply(change("HDMI-A-1", "2360x1640@60.000", 1.25, rotation), False)
                self.assertEqual(run.call_args.args[0][-4:], ["--scale", "1.25", "--transform", transform])

    def test_kscreen_passes_fractional_scale_and_rotation(self):
        with mock.patch.object(displays, "run") as run:
            displays.KScreenBackend().apply(change("HDMI-A-1", "2", 1.5, "right"), False)
        self.assertEqual(run.call_args.args[0][-2:], ["output.HDMI-A-1.scale.1.5", "output.HDMI-A-1.rotation.right"])

    def test_modes_of_unknown_connector_is_empty(self):
        self.assertEqual(FakeBackend({"HDMI-1": []}).modes("DP-9"), [])


class FakeProxy:
    def __init__(self, owner=":1.2", state=None):
        self.owner = owner
        self.state = state
        self.calls = []

    def get_name_owner(self):
        return self.owner

    def call_sync(self, method, args, flags, timeout, cancellable):
        self.calls.append((method, args, flags, timeout))
        return mock.Mock(unpack=mock.Mock(return_value=self.state))


class MutterBackendTest(unittest.TestCase):
    def setUp(self):
        fake_gi.install()
        self.monitors = [mutter_monitor("HDMI-1", ("a", True, True), ("b", False, False))]
        self.proxy = FakeProxy(state=(7, self.monitors, [logical(0, True, "HDMI-1")], {}))
        fake_gi.DBusProxy.next = self.proxy

    def test_available_when_mutter_owns_the_name(self):
        self.assertTrue(displays.MutterBackend.available())
        bus, flags, info, *names, cancellable = fake_gi.DBusProxy.calls[-1]

        self.assertEqual((bus, flags), ("session", "do-not-auto-start"))
        self.assertEqual(tuple(names), displays.MUTTER)

    def test_not_available_without_owner(self):
        self.proxy.owner = None
        self.assertFalse(displays.MutterBackend.available())

    def test_not_available_when_dbus_fails(self):
        fake_gi.DBusProxy.next = RuntimeError("no bus")
        self.assertFalse(displays.MutterBackend.available())

    def test_init_auto_starts(self):
        backend = displays.MutterBackend()
        self.assertIs(backend.proxy, self.proxy)
        self.assertEqual(fake_gi.DBusProxy.calls[-1][1], "none")

    def test_outputs(self):
        backend = displays.MutterBackend()
        self.assertEqual([m.id for m in backend.modes("HDMI-1")], ["a", "b"])
        self.assertEqual(self.proxy.calls[-1][0], "GetCurrentState")

    def test_apply_persistent_and_temporary(self):
        backend = displays.MutterBackend()
        for persistent, method in ((True, 2), (False, 1)):
            with self.subTest(persistent=persistent):
                backend.apply(change("HDMI-1", "b"), persistent)
                name, variant, *_ = self.proxy.calls[-1]
                self.assertEqual(name, "ApplyMonitorsConfig")
                self.assertEqual(variant.signature, "(uua(iiduba(ssa{sv}))a{sv})")
                self.assertEqual(variant.value, (7, method, [(0, 0, 1.0, 0, True, [("HDMI-1", "b", {})])], {}))


class DetectTest(unittest.TestCase):
    def test_first_available_backend_wins(self):
        with (
            mock.patch.object(displays.MutterBackend, "available", return_value=False),
            mock.patch.object(displays.KScreenBackend, "available", return_value=False),
            mock.patch.object(displays.WlrBackend, "available", return_value=True),
            mock.patch.object(displays.XrandrBackend, "available", return_value=True),
        ):
            self.assertIsInstance(displays.detect(), displays.WlrBackend)

    def test_none_available(self):
        with mock.patch.multiple(displays, BACKENDS=(displays.XrandrBackend,)):
            with mock.patch.object(displays.XrandrBackend, "available", return_value=False):
                self.assertIsNone(displays.detect())


class ConnectorTest(unittest.TestCase):
    def cmdline(self, text):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "cmdline"
        if text is not None:
            path.write_text(text)
        patcher = mock.patch.object(displays, "CMDLINE", path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reads_connector_from_cmdline(self):
        self.cmdline("root=/dev/mmcblk0p1 drm.edid_firmware=HDMI-A-1:edid/ultrawide.bin video=HDMI-A-1:e\n")
        self.assertEqual(displays.cmdline_connector(), "HDMI-A-1")

    def test_cmdline_without_edid(self):
        self.cmdline("root=/dev/sda1 quiet")
        self.assertIsNone(displays.cmdline_connector())

    def test_unreadable_cmdline(self):
        self.cmdline(None)
        self.assertIsNone(displays.cmdline_connector())

    def test_picks_edid_connector_by_normalized_name(self):
        self.cmdline("drm.edid_firmware=HDMI-A-1:edid/ultrawide.bin")
        backend = FakeBackend({"DP-1": [], "HDMI-1": []})
        self.assertEqual(displays.pick_connector(backend), "HDMI-1")

    def test_falls_back_to_first_when_edid_connector_absent(self):
        self.cmdline("drm.edid_firmware=HDMI-A-2:edid/ultrawide.bin")
        self.assertEqual(displays.pick_connector(FakeBackend({"DP-1": [], "HDMI-1": []})), "DP-1")

    def test_first_connector_without_edid(self):
        self.cmdline("quiet")
        self.assertEqual(displays.pick_connector(FakeBackend({"DP-1": [], "HDMI-1": []})), "DP-1")

    def test_no_connectors(self):
        self.cmdline("drm.edid_firmware=HDMI-A-1:edid/ultrawide.bin")
        self.assertIsNone(displays.pick_connector(FakeBackend({})))


if __name__ == "__main__":
    unittest.main()
