"""
GTK4/libadwaita window of the Virtual monitor:

  - shows whether the virtual EDID is active at the current boot
  - lists the monitor modes and switches the resolution right away (displays.py)
  - "Remember choice" reapplies the resolution at every login (choice.py)
  - generates a new EDID (edid.py) and installs it (scripts/install-edid.sh, via pkexec)
"""

import tempfile
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from virtual_monitor import choice, displays, edid  # noqa: E402

APP_ID = "br.app.VirtualMonitor"
INSTALL_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "install-edid.sh"
EDID_HELP = (
    "Modes the virtual monitor advertises, in the format WIDTHxHEIGHT@MHz. "
    "On the Orange Pi (RK3566) the clock must be 312, 297, 241.5, 216, 200, 148.5 or 74.25. "
    "Takes effect after a reboot."
)


def run_async(argv, done):
    """Runs argv without freezing the window and calls done(ok, output) at the end."""
    process = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)

    def finished(proc, result):
        try:
            _ok, stdout, _err = proc.communicate_utf8_finish(result)
        except GLib.Error as error:
            done(False, error.message)
            return
        done(proc.get_exit_status() == 0, stdout or "")

    process.communicate_utf8_async(None, None, finished)


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Virtual monitor", default_width=520, default_height=760)
        self.backend = displays.detect()
        self.connector = displays.pick_connector(self.backend) if self.backend else None
        self.mode_rows = []

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        page = Adw.PreferencesPage()
        view.set_content(page)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        page.add(self.build_status())
        page.add(self.build_modes())
        page.add(self.build_edid())
        self.refresh()

    def build_status(self):
        group = Adw.PreferencesGroup(title="Status")
        self.session_row = Adw.ActionRow(title="Session")
        self.edid_row = Adw.ActionRow(title="Virtual EDID")
        self.output_row = Adw.ActionRow(title="Output")
        for row in (self.session_row, self.edid_row, self.output_row):
            group.add(row)
        return group

    def build_modes(self):
        self.modes_group = Adw.PreferencesGroup(title="Resolution", description="Tap a mode to switch right away.")
        self.remember = Adw.SwitchRow(title="Remember choice", subtitle="Reapplies the resolution on the next logins.")
        self.remember.set_active(True)
        self.modes_group.add(self.remember)
        return self.modes_group

    def build_edid(self):
        group = Adw.PreferencesGroup(title="EDID", description=EDID_HELP)
        self.modes_entry = Adw.EntryRow(title="Modes")
        self.modes_entry.set_text(" ".join(edid.DEFAULT_MODES))
        group.add(self.modes_entry)
        install = Adw.ActionRow(title="Generate and install EDID", subtitle="Asks for the administrator password.")
        self.install_button = Gtk.Button(label="Install", valign=Gtk.Align.CENTER)
        self.install_button.add_css_class("suggested-action")
        self.install_button.connect("clicked", self.on_install)
        install.add_suffix(self.install_button)
        group.add(install)
        return group

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text))

    def refresh(self):
        wanted = displays.cmdline_connector()
        self.session_row.set_subtitle(self.backend.name if self.backend else "unsupported video environment")
        self.edid_row.set_subtitle(f"active at boot ({wanted})" if wanted else "not configured at this boot")
        self.output_row.set_subtitle(self.connector or "no monitor found")

        for row in self.mode_rows:
            self.modes_group.remove(row)
        self.mode_rows = []
        if not self.connector:
            return
        for mode in self.backend.modes(self.connector):
            row = self.mode_row(mode)
            self.modes_group.add(row)
            self.mode_rows.append(row)

    def mode_row(self, mode):
        row = Adw.ActionRow(title=f"{mode.width}×{mode.height}", subtitle=f"{mode.refresh:.2f} Hz")
        row.set_activatable(True)
        if mode.preferred:
            tag = Gtk.Label(label="default of the EDID", valign=Gtk.Align.CENTER)
            tag.add_css_class("dim-label")
            row.add_suffix(tag)
        if mode.current:
            row.add_suffix(Gtk.Image.new_from_icon_name("object-select-symbolic"))
        row.connect("activated", self.on_mode, mode)
        return row

    def on_mode(self, _row, mode):
        try:
            choice.apply_mode(self.backend, self.connector, mode.id, self.remember.get_active())
        except Exception as error:  # xrandr, kscreen-doctor or DBus refused the mode
            self.toast(f"Failed: {error}")
            return
        self.toast(f"{mode.width}×{mode.height} applied")
        GLib.timeout_add(600, self.refresh_once)

    def refresh_once(self):
        self.refresh()
        return GLib.SOURCE_REMOVE

    def on_install(self, _button):
        try:
            _timings, data = edid.generate(self.modes_entry.get_text().split())
        except edid.EdidError as error:
            self.toast(f"Invalid EDID: {error}")
            return
        out = Path(tempfile.mkdtemp(prefix="edid-")) / "ultrawide-app.bin"
        out.write_bytes(data)
        self.install_button.set_sensitive(False)
        run_async(["pkexec", "bash", str(INSTALL_SCRIPT), str(out)], self.after_install)

    def after_install(self, ok, _text):
        self.install_button.set_sensitive(True)
        if not ok:
            self.toast("Install cancelled or failed")
            return
        dialog = Adw.AlertDialog(heading="EDID installed", body="Restart for it to take effect. Restart now?")
        dialog.add_response("later", "Later")
        dialog.add_response("reboot", "Restart")
        dialog.set_response_appearance("reboot", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self.on_reboot_response)
        dialog.present(self)

    def on_reboot_response(self, _dialog, response):
        if response == "reboot":
            Gio.Subprocess.new(["systemctl", "reboot"], Gio.SubprocessFlags.NONE)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        (self.props.active_window or Window(self)).present()


def run():
    return App().run([])
