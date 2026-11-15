import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from virtual_monitor import session


class SessionTestCase(unittest.TestCase):
    """A fake /run/user/1000, /tmp/.X11-unix and home, with real Unix sockets (under /tmp: short paths)."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(folder.cleanup)
        self.base = Path(folder.name)
        self.runtime_root = self.base / "run"
        self.runtime = self.runtime_root / "1000"
        self.x11 = self.base / "x11"
        self.home = self.base / "home"
        for path in (self.runtime, self.x11, self.home):
            path.mkdir(parents=True)

    def make_socket(self, path):
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        server.bind(str(path))
        return path

    def missing(self, environ=None):
        return session.missing_variables(environ or {}, 1000, self.home, self.runtime_root, self.x11)


class MissingVariablesTest(SessionTestCase):
    def test_finds_a_full_wayland_session(self):
        self.make_socket(self.runtime / "bus")
        self.make_socket(self.runtime / "wayland-1")
        self.make_socket(self.runtime / "wayland-0")
        (self.runtime / "wayland-0.lock").write_text("")
        self.make_socket(self.x11 / "X1")
        self.make_socket(self.x11 / "X0")
        (self.runtime / ".mutter-Xwaylandauth.ABC123").write_text("cookie")

        self.assertEqual(
            self.missing(),
            {
                "XDG_RUNTIME_DIR": str(self.runtime),
                "DBUS_SESSION_BUS_ADDRESS": f"unix:path={self.runtime / 'bus'}",
                "WAYLAND_DISPLAY": "wayland-0",
                "DISPLAY": ":0",
                "XAUTHORITY": str(self.runtime / ".mutter-Xwaylandauth.ABC123"),
            },
        )

    def test_keeps_what_is_already_set(self):
        self.make_socket(self.runtime / "bus")
        self.make_socket(self.runtime / "wayland-0")
        self.make_socket(self.x11 / "X0")
        (self.home / ".Xauthority").write_text("cookie")
        environ = {
            "XDG_RUNTIME_DIR": str(self.runtime),
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/elsewhere",
            "WAYLAND_DISPLAY": "wayland-9",
            "DISPLAY": ":5",
        }

        self.assertEqual(self.missing(environ), {})

    def test_keeps_a_set_xauthority(self):
        self.make_socket(self.x11 / "X0")
        (self.home / ".Xauthority").write_text("cookie")

        self.assertEqual(self.missing({"XAUTHORITY": "/mine"}), {"XDG_RUNTIME_DIR": str(self.runtime), "DISPLAY": ":0"})

    def test_x11_session_uses_the_home_cookie_first(self):
        self.make_socket(self.x11 / "X0")
        (self.home / ".Xauthority").write_text("cookie")
        (self.runtime / "gdm").mkdir()
        (self.runtime / "gdm/Xauthority").write_text("cookie")

        self.assertEqual(self.missing()["XAUTHORITY"], str(self.home / ".Xauthority"))

    def test_display_manager_cookies(self):
        for name in ("gdm/Xauthority", "xauth_KdRtZp"):
            with self.subTest(name=name):
                self.setUp()
                self.make_socket(self.x11 / "X0")
                cookie = self.runtime / name
                cookie.parent.mkdir(exist_ok=True)
                cookie.write_text("cookie")
                self.assertEqual(self.missing()["XAUTHORITY"], str(cookie))

    def test_display_without_cookie(self):
        self.make_socket(self.x11 / "X2")
        self.assertEqual(self.missing(), {"XDG_RUNTIME_DIR": str(self.runtime), "DISPLAY": ":2"})

    def test_ignores_files_and_names_that_are_not_sockets(self):
        (self.runtime / "bus").write_text("not a socket")
        (self.runtime / "wayland-0").write_text("not a socket")
        self.make_socket(self.runtime / "wayland-x")
        self.make_socket(self.x11 / "X0-lock")
        (self.x11 / "X1").write_text("not a socket")

        self.assertEqual(self.missing(), {"XDG_RUNTIME_DIR": str(self.runtime)})

    def test_without_runtime_folder_finds_nothing(self):
        self.make_socket(self.x11 / "X0")
        missing = session.missing_variables({}, 2000, self.home, self.runtime_root, self.x11)
        self.assertEqual(missing, {})

    def test_set_runtime_folder_is_used(self):
        other = self.base / "other"
        other.mkdir()
        self.make_socket(other / "wayland-3")

        self.assertEqual(self.missing({"XDG_RUNTIME_DIR": str(other)}), {"WAYLAND_DISPLAY": "wayland-3"})

    def test_unreadable_folders_find_nothing(self):
        missing = session.missing_variables(
            {"XDG_RUNTIME_DIR": str(self.base / "gone")}, 1000, self.home, self.runtime_root, self.base / "none"
        )
        self.assertEqual(missing, {})


class HelpersTest(unittest.TestCase):
    def test_has_display(self):
        self.assertTrue(session.has_display({"WAYLAND_DISPLAY": "wayland-0"}))
        self.assertTrue(session.has_display({"DISPLAY": ":0"}))
        self.assertFalse(session.has_display({"DISPLAY": ""}))
        self.assertFalse(session.has_display({}))

    def test_socket_number(self):
        self.assertEqual(session.socket_number(Path("wayland-12"), "wayland-"), 12)
        self.assertIsNone(session.socket_number(Path("wayland-0.lock"), "wayland-"))
        self.assertIsNone(session.socket_number(Path("X0"), "wayland-"))

    def test_is_socket_of_a_missing_path(self):
        self.assertFalse(session.is_socket(Path("/nonexistent/socket")))

    def test_default_locations(self):
        self.assertEqual(session.RUNTIME_ROOT, Path("/run/user"))
        self.assertEqual(session.X11_SOCKETS, Path("/tmp/.X11-unix"))


class AttachTest(SessionTestCase):
    def test_completes_the_environment(self):
        found = {"WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": "/run/user/1000"}
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(
            session, "missing_variables", return_value=found
        ) as missing:
            self.assertTrue(session.attach())
            self.assertEqual(os.environ["WAYLAND_DISPLAY"], "wayland-0")

        environ, uid, home = missing.call_args.args
        self.assertEqual((uid, home), (os.getuid(), Path.home()))
        self.assertIs(environ, os.environ)

    def test_without_a_session_reports_no_display(self):
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(session, "missing_variables", return_value={}):
            self.assertFalse(session.attach())


if __name__ == "__main__":
    unittest.main()
