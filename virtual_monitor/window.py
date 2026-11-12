"""
GTK4/libadwaita window of the Virtual monitor:

  - shows whether the virtual EDID is active at the current boot
  - lists the monitor modes and switches the resolution right away (displays.py)
  - "Remember choice" reapplies the resolution at every login (choice.py)
  - on its own page, opened from the status row, generates a new EDID (edid.py) and installs it
    (scripts/install-edid.sh, via pkexec)
"""

import tempfile
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from virtual_monitor import choice, displays, edid  # noqa: E402

APP_ID = "br.app.VirtualMonitor"
ICON_NAME = "virtual-monitor"
INSTALL_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "install-edid.sh"
EDID_HELP = (
    "Modes the virtual monitor advertises, as WIDTHxHEIGHT or WIDTHxHEIGHT@MHz, separated by spaces. "
    "Without MHz, the mode takes the Orange Pi (RK3566) clock closest to 60 Hz. "
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


def edid_text(wanted):
    if not wanted:
        return "not configured at this boot"

    return f"active at boot ({wanted})"


def navigation_page(content, title, tag):
    """A page with its own header bar, which shows the back button on pushed pages."""
    view = Adw.ToolbarView()
    view.add_top_bar(Adw.HeaderBar())
    view.set_content(content)
    return Adw.NavigationPage(child=view, title=title, tag=tag)


def install_label(installed):
    if installed:
        return "Installed"

    return "Install"


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Virtual monitor", default_width=520, default_height=840)
        self.backend = displays.detect()
        self.connector = None
        if self.backend:
            self.connector = displays.pick_connector(self.backend)
        self.mode_rows = []

        # Day to day the window only switches resolutions; the EDID, set once, lives on its own page
        main = Adw.PreferencesPage()
        main.add(self.build_status())
        main.add(self.build_modes())
        edid_page = Adw.PreferencesPage()
        edid_page.add(self.build_edid())

        self.navigation = Adw.NavigationView()
        self.navigation.add(navigation_page(main, "Virtual monitor", "main"))
        self.edid_page = navigation_page(edid_page, "Virtual EDID", "edid")
        self.navigation.add(self.edid_page)

        self.toasts = Adw.ToastOverlay()
        self.toasts.set_child(self.navigation)
        self.set_content(self.toasts)
        self.refresh()

    def build_status(self):
        group = Adw.PreferencesGroup(title="Status")
        self.display_row = Adw.ActionRow(title="Display")
        group.add(self.display_row)

        self.edid_row = Adw.ActionRow(title="Virtual EDID")
        self.edid_row.set_activatable(True)
        self.edid_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        self.edid_row.connect("activated", self.on_edid_row)
        group.add(self.edid_row)
        return group

    def on_edid_row(self, _row):
        self.navigation.push(self.edid_page)

    def build_modes(self):
        self.modes_group = Adw.PreferencesGroup(title="Resolution", description="Tap a mode to switch right away.")
        self.remember = Adw.SwitchRow(title="Remember choice", subtitle="Reapplies the resolution on the next logins.")
        self.remember.set_active(True)
        self.modes_group.add(self.remember)
        return self.modes_group

    def build_edid(self):
        group = Adw.PreferencesGroup(description=EDID_HELP)
        self.modes_entry = Adw.EntryRow(title="Modes")
        self.modes_entry.set_text(" ".join(edid.DEFAULT_MODES))
        group.add(self.modes_entry)

        install = Adw.ActionRow(title="Generate and install EDID", subtitle="Asks for the administrator password.")
        self.install_button = Gtk.Button(label="Install", valign=Gtk.Align.CENTER)
        self.install_button.add_css_class("suggested-action")
        self.install_button.connect("clicked", self.on_install)
        install.add_suffix(self.install_button)
        group.add(install)

        self.modes_entry.connect("changed", self.update_install_button)
        self.update_install_button()
        return group

    def update_install_button(self, *_args):
        installed = edid.is_installed(self.modes_entry.get_text().split())
        self.install_button.set_label(install_label(installed))
        self.install_button.set_sensitive(not installed)

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text))

    def refresh(self):
        self.display_row.set_subtitle(self.display_text())
        self.edid_row.set_subtitle(edid_text(displays.cmdline_connector()))

        for row in self.mode_rows:
            self.modes_group.remove(row)
        self.mode_rows = []
        if not self.connector:
            return

        for mode in self.backend.modes(self.connector):
            row = self.mode_row(mode)
            self.modes_group.add(row)
            self.mode_rows.append(row)

    def display_text(self):
        if not self.backend:
            return "unsupported video environment"

        return f"{self.backend.name} · {self.connector or 'no monitor found'}"

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
        self.update_install_button()
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
        if response != "reboot":
            return

        Gio.Subprocess.new(["systemctl", "reboot"], Gio.SubprocessFlags.NONE)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        (self.props.active_window or Window(self)).present()


def run():
    # The panel matches the window to the launcher by its class and icon name.
    GLib.set_prgname(ICON_NAME)
    Gtk.Window.set_default_icon_name(ICON_NAME)
    return App().run([])
