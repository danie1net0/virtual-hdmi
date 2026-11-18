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


COSMIC = """output "HDMI-A-1" enabled=#true {
  description make="Linux Foundation" model="Virtual UW"
  physical 800 335
  position 0 0
  scale 1.00
  transform "normal"
  modes {
    mode 3440 1440 59240 preferred=#true
    mode 2360 1640 60010 current=#true
    mode 1920 1080 60000
  }
}
output "DP-1" enabled=#false {
  description model="Other"
  modes {
    mode 1920 1080 60000 current=#true
  }
}
output "DP-2" enabled=#true {
  description model="Second"
  modes {
    mode 2560 1440 143912 current=#true preferred=#true
  }
}
"""


def mutter_monitor(connector, *modes):
    """Monitor in the GetCurrentState format; each mode is (id, current, preferred)."""
    return (
        (connector, "VHD", "Virtual", "0"),
        [(mode_id, 1920, 1080, 60.0, 1.0, [1.0], {"is-current": current, "is-preferred": preferred}) for mode_id, current, preferred in modes],
        {},
    )


def sized_mutter_monitor(connector, width, height, scales):
    """Monitor with a single non-current mode "big" of the given size and supported scales."""
    return ((connector, "VHD", "Virtual", "0"), [("big", width, height, 60.0, 1.0, scales, {})], {})


def logical(left, primary, *connectors):
    return (left, 0, 1.0, 0, primary, [(connector, "VHD", "Virtual", "0") for connector in connectors], {})


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
        modes = {mode.id: mode for mode in self.outputs["HDMI-1"]}

        self.assertTrue(modes["3440x1440@59.24"].current)
        self.assertTrue(modes["3440x1440@59.24"].preferred)
        self.assertFalse(modes["2560x1080@59.98"].current)
        self.assertFalse(modes["2560x1080@59.98"].preferred)
        self.assertTrue(modes["1920x1080@60.00"].preferred)
        self.assertFalse(modes["1920x1080@59.94"].preferred)
        self.assertTrue(modes["1280x720@60.00"].current)
        self.assertEqual(modes["2560x1080@59.98"].refresh, 59.98)

    def test_skips_interlaced_and_detail_lines(self):
        ids = [mode.id for mode in self.outputs["HDMI-1"]]
        self.assertNotIn("1920x1080@30.00", ids)
        self.assertEqual(len(ids), 5)

    def test_ignores_modes_of_disconnected_and_before_any_output(self):
        all_ids = [mode.id for modes in self.outputs.values() for mode in modes]
        self.assertNotIn("1024x768@60.00", all_ids)
        self.assertNotIn("640x480@60.00", all_ids)

    def test_empty_text(self):
        self.assertEqual(displays.parse_xrandr(""), {})

    def test_ignores_stray_tokens(self):
        text = "HDMI-1 connected\n   800x600   +  60.32 junk 56.25*\n"
        modes = displays.parse_xrandr(text)["HDMI-1"]
        self.assertEqual([(mode.id, mode.current, mode.preferred) for mode in modes], [("800x600@60.32", False, False), ("800x600@56.25", True, False)])


class ParseOtherBackendsTest(unittest.TestCase):
    def test_wlr(self):
        outputs = displays.parse_wlr(WLR)
        modes = outputs["HDMI-A-1"]

        self.assertEqual([mode.id for mode in modes], ["3440x1440@59.239", "1920x1080@60.000"])
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

    def test_cosmic(self):
        outputs = displays.parse_cosmic(COSMIC)

        self.assertEqual(list(outputs), ["HDMI-A-1", "DP-2"])
        self.assertEqual(
            outputs["HDMI-A-1"],
            [
                displays.Mode("3440x1440@59.240", 3440, 1440, 59.24, False, True),
                displays.Mode("2360x1640@60.010", 2360, 1640, 60.01, True, False),
                displays.Mode("1920x1080@60.000", 1920, 1080, 60.0, False, False),
            ],
        )
        self.assertEqual(outputs["DP-2"][0].id, "2560x1440@143.912")

    def test_cosmic_ignores_modes_before_any_output(self):
        self.assertEqual(displays.parse_cosmic("    mode 1920 1080 60000\n"), {})

    def test_kscreen_without_outputs(self):
        self.assertEqual(displays.parse_kscreen("{}"), {})

    def test_mutter(self):
        monitors = [mutter_monitor("HDMI-1", ("a", True, False), ("b", False, True)), mutter_monitor("DP-1")]
        outputs = displays.parse_mutter(monitors)

        self.assertEqual(list(outputs), ["HDMI-1", "DP-1"])
        first, second = outputs["HDMI-1"]
        self.assertEqual((first.id, first.width, first.height, first.refresh), ("a", 1920, 1080, 60.0))
        self.assertTrue(first.current and not first.preferred)
        self.assertTrue(second.preferred and not second.current)

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
    def test_defaults_to_1x(self):
        self.assertEqual(displays.ModeChange("HDMI-1", "m").scale, 1.0)

    def test_refuses_scale_that_is_not_positive(self):
        for scale in (0, -1.5):
            with self.subTest(scale=scale), self.assertRaisesRegex(ValueError, "scale must be positive"):
                displays.ModeChange("HDMI-1", "m", scale)


class SetXfceDpiTest(unittest.TestCase):
    def test_sets_dpi_from_scale(self):
        with mock.patch("shutil.which", return_value="/usr/bin/xfconf-query"), mock.patch.object(displays, "run") as run:
            displays.set_xfce_dpi(1.5)
        run.assert_called_once_with(["xfconf-query", "-c", "xsettings", "-p", "/Xft/DPI", "-n", "-t", "int", "-s", "144"])

    def test_skips_without_xfconf(self):
        with mock.patch("shutil.which", return_value=None), mock.patch.object(displays, "run") as run:
            displays.set_xfce_dpi(1.5)
        run.assert_not_called()


def change(connector, mode_id, scale=1.0):
    return displays.ModeChange(connector, mode_id, scale)


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

    def test_layout_scales_only_the_target_connector_and_keeps_every_rotation(self):
        monitors = [sized_mutter_monitor("HDMI-1", 2360, 1640, [1.0, 1.5]), mutter_monitor("DP-1", ("c", True, False))]
        hdmi_logical = (0, 0, 1.0, 1, True, [("HDMI-1", "VHD", "Virtual", "0")], {})
        dp_logical = (2360, 0, 2.0, 2, False, [("DP-1", "VHD", "Virtual", "0")], {})
        layout = displays.mutter_layout(monitors, [hdmi_logical, dp_logical], change("HDMI-1", "big", 1.5))
        self.assertEqual(
            layout,
            [(0, 0, 1.5, 1, True, [("HDMI-1", "big", {})]), (2360, 0, 2.0, 2, False, [("DP-1", "c", {})])],
        )

    def test_layout_adds_missing_connector_with_its_scale_and_no_rotation(self):
        monitors = [sized_mutter_monitor("HDMI-1", 2360, 1640, [1.0, 1.5])]
        layout = displays.mutter_layout(monitors, [], change("HDMI-1", "big", 1.5))
        self.assertEqual(layout, [(0, 0, 1.5, 0, True, [("HDMI-1", "big", {})])])


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

    def test_failure_says_what_the_command_printed(self):
        script = "import sys; print('Can\\'t open display :0', file=sys.stderr); print('second'); raise SystemExit(1)"
        with self.assertRaisesRegex(displays.DisplayError, r"^\S+ -c: Can't open display :0$"):
            displays.run([sys.executable, "-c", script])

    def test_failure_without_output_gives_the_exit_status(self):
        with self.assertRaisesRegex(displays.DisplayError, r"-c: exit status 3$"):
            displays.run([sys.executable, "-c", "raise SystemExit(3)"])

    def test_failure_with_only_stdout_uses_it(self):
        error = subprocess.CalledProcessError(1, ["xrandr"], output="  stdout line\n", stderr="")
        self.assertEqual(displays.command_message(error), "stdout line")

    def test_missing_tool(self):
        with self.assertRaisesRegex(displays.DisplayError, "^no-such-tool-here is not installed$"):
            displays.run(["no-such-tool-here", "--query"])

    def test_display_error_is_a_runtime_error(self):
        self.assertTrue(issubclass(displays.DisplayError, RuntimeError))


class CommandBackendsTest(unittest.TestCase):
    def check_requirement(self, backend_class, environment, tool):
        variable = next(iter(environment), None)
        cases = [
            (environment, f"/usr/bin/{tool}", ""),
            (environment, None, f"{tool} is not installed"),
        ]
        if variable:
            cases.append(({}, f"/usr/bin/{tool}", f"{variable} is not set"))

        for environment, which, expected in cases:
            with self.subTest(backend_class=backend_class.name, environment=environment, which=which):
                with mock.patch.dict("os.environ", environment, clear=True), mock.patch("shutil.which", return_value=which):
                    self.assertEqual(backend_class.requirement(), expected)
                    self.assertIs(backend_class.available(), not expected)

    def test_requirements(self):
        self.check_requirement(displays.XrandrBackend, {"DISPLAY": ":0"}, "xrandr")
        self.check_requirement(displays.WlrBackend, {"WAYLAND_DISPLAY": "wayland-0"}, "wlr-randr")
        self.check_requirement(displays.KScreenBackend, {}, "kscreen-doctor")
        self.check_requirement(displays.CosmicBackend, {"WAYLAND_DISPLAY": "wayland-1"}, "cosmic-randr")

    def test_cosmic(self):
        backend = displays.CosmicBackend()
        with mock.patch.object(displays, "run", return_value=COSMIC) as run:
            self.assertEqual(backend.connectors(), ["HDMI-A-1", "DP-2"])
            run.assert_called_with(["cosmic-randr", "list", "--kdl"])
            backend.apply(change("HDMI-A-1", "2360x1640@60.010", 1.5), True)
            run.assert_called_with(
                [
                    "cosmic-randr",
                    "mode",
                    "HDMI-A-1",
                    "2360",
                    "1640",
                    "--refresh",
                    "60.010",
                    "--scale",
                    "1.5",
                ]
            )

    def test_kscreen_does_not_need_the_kde_desktop_name(self):
        with mock.patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "XFCE"}), mock.patch("shutil.which", return_value="/x"):
            self.assertTrue(displays.KScreenBackend.available())

    def test_xrandr_skips_xwayland_outputs(self):
        text = XRANDR.replace("DP-1 connected", "XWAYLAND0 connected")
        with mock.patch.object(displays, "run", return_value=text):
            self.assertEqual(displays.XrandrBackend().connectors(), ["HDMI-1"])

    def test_xrandr_with_only_xwayland_outputs_fails(self):
        text = "XWAYLAND0 connected 1920x1080+0+0\n   1920x1080     59.96*+\n"
        with mock.patch.object(displays, "run", return_value=text), self.assertRaisesRegex(displays.DisplayError, "only XWayland"):
            displays.XrandrBackend().outputs()

    def test_xrandr_without_outputs_is_empty(self):
        with mock.patch.object(displays, "run", return_value=""):
            self.assertEqual(displays.XrandrBackend().outputs(), {})

    def test_xrandr(self):
        backend = displays.XrandrBackend()
        with mock.patch.object(displays, "run", return_value=XRANDR) as run, mock.patch("shutil.which", return_value=None):
            self.assertEqual(backend.connectors(), ["HDMI-1", "DP-1"])
            self.assertEqual(len(backend.modes("HDMI-1")), 5)
            run.assert_called_with(["xrandr", "--query"])
            backend.apply(change("HDMI-1", "2560x1080@59.98"), True)
            run.assert_called_with(
                ["xrandr", "--output", "HDMI-1", "--mode", "2560x1080", "--rate", "59.98"]
            )

    def test_wlr(self):
        backend = displays.WlrBackend()
        with mock.patch.object(displays, "run", return_value=WLR) as run:
            self.assertEqual(backend.connectors(), ["HDMI-A-1", "eDP-1"])
            run.assert_called_with(["wlr-randr", "--json"])
            backend.apply(change("HDMI-A-1", "1920x1080@60.000"), False)
            run.assert_called_with(
                ["wlr-randr", "--output", "HDMI-A-1", "--mode", "1920x1080@60.000Hz", "--scale", "1"]
            )

    def test_kscreen(self):
        backend = displays.KScreenBackend()
        with mock.patch.object(displays, "run", return_value=KSCREEN) as run:
            self.assertEqual(backend.connectors(), ["HDMI-A-1", "DP-1"])
            run.assert_called_with(["kscreen-doctor", "-j"])
            backend.apply(change("HDMI-A-1", "2"), False)
            run.assert_called_with(
                ["kscreen-doctor", "output.HDMI-A-1.mode.2", "output.HDMI-A-1.scale.1"]
            )

    def test_xrandr_sets_xfce_dpi_after_the_mode(self):
        with mock.patch.object(displays, "run") as run, mock.patch("shutil.which", return_value="/usr/bin/xfconf-query"):
            displays.XrandrBackend().apply(change("HDMI-1", "2360x1640@60.01", 1.5), True)

        self.assertEqual(
            run.call_args_list[0].args[0],
            ["xrandr", "--output", "HDMI-1", "--mode", "2360x1640", "--rate", "60.01"],
        )
        self.assertEqual(run.call_args_list[1].args[0][-1], "144")

    def test_wlr_passes_fractional_scale(self):
        with mock.patch.object(displays, "run") as run:
            displays.WlrBackend().apply(change("HDMI-A-1", "2360x1640@60.000", 1.25), False)
        self.assertEqual(run.call_args.args[0][-2:], ["--scale", "1.25"])

    def test_kscreen_passes_fractional_scale(self):
        with mock.patch.object(displays, "run") as run:
            displays.KScreenBackend().apply(change("HDMI-A-1", "2", 1.5), False)
        self.assertEqual(run.call_args.args[0][-1], "output.HDMI-A-1.scale.1.5")

    def test_modes_of_unknown_connector_is_empty(self):
        self.assertEqual(FakeBackend({"HDMI-1": []}).modes("DP-9"), [])


class FakeProxy:
    def __init__(self, owner=":1.2", state=None):
        self.owner = owner
        self.state = state
        self.calls = []

    def get_name_owner(self):
        return self.owner

    def call_sync(self, method, arguments, flags, timeout, cancellable):
        self.calls.append((method, arguments, flags, timeout))
        return mock.Mock(unpack=mock.Mock(return_value=self.state))


class MutterBackendTest(unittest.TestCase):
    def setUp(self):
        fake_gi.install()
        self.monitors = [mutter_monitor("HDMI-1", ("a", True, True), ("b", False, False))]
        self.proxy = FakeProxy(state=(7, self.monitors, [logical(0, True, "HDMI-1")], {}))
        fake_gi.DBusProxy.next = self.proxy

    def test_available_when_mutter_owns_the_name(self):
        self.assertEqual(displays.MutterBackend.requirement(), "")
        self.assertTrue(displays.MutterBackend.available())
        bus, flags, information, *names, cancellable = fake_gi.DBusProxy.calls[-1]

        self.assertEqual((bus, flags), ("session", "do-not-auto-start"))
        self.assertEqual(tuple(names), displays.MUTTER)

    def test_not_available_without_owner(self):
        self.proxy.owner = None
        self.assertEqual(displays.MutterBackend.requirement(), "GNOME Shell is not running")

    def test_not_available_when_dbus_fails(self):
        fake_gi.DBusProxy.next = RuntimeError("no bus")
        self.assertEqual(displays.MutterBackend.requirement(), "no session bus (no bus)")

    def test_constructor_starts_the_proxy(self):
        backend = displays.MutterBackend()
        self.assertIs(backend.proxy, self.proxy)
        self.assertEqual(fake_gi.DBusProxy.calls[-1][1], "none")

    def test_outputs(self):
        backend = displays.MutterBackend()
        self.assertEqual([mode.id for mode in backend.modes("HDMI-1")], ["a", "b"])
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


class ProbeBackend(displays.Backend):
    """Backend whose requirement and outputs the test sets on the class."""

    name = "Probe"
    reason = ""
    listed = {"HDMI-1": []}
    error = None

    @classmethod
    def requirement(cls):
        return cls.reason

    def outputs(self):
        if self.error:
            raise self.error

        return self.listed


def probe_backend(name, reason="", listed=None, error=None):
    attributes = {"name": name, "reason": reason, "error": error}
    if listed is not None:
        attributes["listed"] = listed

    return type(name, (ProbeBackend,), attributes)


class DetectTest(unittest.TestCase):
    def test_first_working_backend_wins(self):
        missing = probe_backend("Missing", reason="tool is not installed")
        broken = probe_backend("Broken", error=displays.DisplayError("xrandr --query: Can't open display"))
        empty = probe_backend("Empty", listed={})
        working = probe_backend("Working")
        later = probe_backend("Later")

        with mock.patch.object(displays, "BACKENDS", (missing, broken, empty, working, later)):
            self.assertIsInstance(displays.detect(), working)

    def test_none_working(self):
        missing = probe_backend("Missing", reason="tool is not installed")
        with mock.patch.object(displays, "BACKENDS", (missing,)):
            self.assertIsNone(displays.detect())

    def test_diagnose_says_why_each_backend_fails(self):
        backends = (
            probe_backend("Missing", reason="wlr-randr is not installed"),
            probe_backend("Broken", error=RuntimeError("xrandr --query: Can't open display :0")),
            probe_backend("Empty", listed={}),
            probe_backend("Working"),
        )
        with mock.patch.object(displays, "BACKENDS", backends):
            self.assertEqual(
                displays.diagnose(),
                [
                    ("Missing", "wlr-randr is not installed"),
                    ("Broken", "xrandr --query: Can't open display :0"),
                    ("Empty", "no connected output"),
                    ("Working", ""),
                ],
            )

    def test_probe_catches_a_failing_constructor(self):
        class FailingConstructor(ProbeBackend):
            name = "FailingInit"

            def __init__(self):
                raise RuntimeError("DBus refused")

        self.assertEqual(displays.probe(FailingConstructor), (None, "DBus refused"))

    def test_backend_order_prefers_native_tools(self):
        self.assertEqual(
            displays.BACKENDS,
            (
                displays.MutterBackend,
                displays.KScreenBackend,
                displays.CosmicBackend,
                displays.WlrBackend,
                displays.XrandrBackend,
            ),
        )


class ConnectorTest(unittest.TestCase):
    def command_line(self, text):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "cmdline"
        if text is not None:
            path.write_text(text)
        patcher = mock.patch.object(displays, "KERNEL_COMMAND_LINE", path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reads_connector_from_the_command_line(self):
        self.command_line("root=/dev/mmcblk0p1 drm.edid_firmware=HDMI-A-1:edid/ultrawide.bin video=HDMI-A-1:e\n")
        self.assertEqual(displays.command_line_connector(), "HDMI-A-1")

    def test_command_line_without_edid(self):
        self.command_line("root=/dev/sda1 quiet")
        self.assertIsNone(displays.command_line_connector())

    def test_unreadable_command_line(self):
        self.command_line(None)
        self.assertIsNone(displays.command_line_connector())

    def test_picks_edid_connector_by_normalized_name(self):
        self.command_line("drm.edid_firmware=HDMI-A-1:edid/ultrawide.bin")
        backend = FakeBackend({"DP-1": [], "HDMI-1": []})
        self.assertEqual(displays.pick_connector(backend), "HDMI-1")

    def test_falls_back_to_first_when_edid_connector_absent(self):
        self.command_line("drm.edid_firmware=HDMI-A-2:edid/ultrawide.bin")
        self.assertEqual(displays.pick_connector(FakeBackend({"DP-1": [], "HDMI-1": []})), "DP-1")

    def test_first_connector_without_edid(self):
        self.command_line("quiet")
        self.assertEqual(displays.pick_connector(FakeBackend({"DP-1": [], "HDMI-1": []})), "DP-1")

    def test_no_connectors(self):
        self.command_line("drm.edid_firmware=HDMI-A-1:edid/ultrawide.bin")
        self.assertIsNone(displays.pick_connector(FakeBackend({})))


if __name__ == "__main__":
    unittest.main()
