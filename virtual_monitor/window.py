"""
GTK4/libadwaita window of the Virtual monitor:

  - shows whether the virtual EDID is active at the current boot
  - lists the monitor modes and switches the resolution right away (displays.py); a new mode
    goes back to the previous one after REVERT_SECONDS unless Keep is pressed, in case it shows
    no picture
  - "Remember choice" reapplies the resolution at every login (choice.py)
  - scale and orientation of the current mode, saved for each mode size (choice.py)
  - on its own page, opened from the status row, generates a new EDID (edid.py), with a preview
    of the timings, and installs it (scripts/install-edid.sh, via pkexec)
"""

import tempfile
from dataclasses import dataclass
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
REVERT_SECONDS = 15
SCALES = (("Automatic", None), ("100%", 1.0), ("125%", 1.25), ("150%", 1.5), ("175%", 1.75), ("200%", 2.0))
ROTATIONS = (("Landscape", "normal"), ("Portrait", "left"), ("Portrait, flipped", "right"))


@dataclass
class PendingMode:
    """A mode applied temporarily, waiting for Keep; without it, previous_id comes back."""

    dialog: object
    mode_id: str
    previous_id: str
    remaining: int = REVERT_SECONDS


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


def countdown_text(seconds):
    return f"Going back to the previous resolution in {seconds} s."


def timings_text(texts):
    """The timings the EDID would get for these modes, one per line, or why they do not fit."""
    try:
        timings, _data = edid.generate(texts)
    except edid.EdidError as error:
        return f"Invalid: {error}"

    return "\n".join(timing.label() for timing in timings)


def choice_index(choices, value):
    """Position of value in (label, value) choices; 0 (the first) when it is not there."""
    return next((index for index, (_label, choice_value) in enumerate(choices) if choice_value == value), 0)


def combo_row(title, choices):
    labels = [label for label, _value in choices]
    return Adw.ComboRow(title=title, model=Gtk.StringList.new(labels))


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
        self.current = None
        self.pending = None
        self.syncing = False

        # Day to day the window only switches resolutions; the EDID, set once, lives on its own page
        main = Adw.PreferencesPage()
        main.add(self.build_status())
        main.add(self.build_current())
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

    def build_current(self):
        group = Adw.PreferencesGroup(title="Current mode", description="Saved for each resolution.")
        self.scale_row = combo_row("Scale", SCALES)
        self.scale_row.connect("notify::selected", self.on_scale)
        group.add(self.scale_row)

        self.rotation_row = combo_row("Orientation", ROTATIONS)
        self.rotation_row.connect("notify::selected", self.on_rotation)
        group.add(self.rotation_row)
        return group

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

        self.timings_row = Adw.ActionRow(title="Timings")
        self.timings_row.add_css_class("property")
        group.add(self.timings_row)

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
        texts = self.modes_entry.get_text().split()
        self.timings_row.set_subtitle(timings_text(texts))
        installed = edid.is_installed(texts)
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
        self.current = None
        if self.connector:
            self.add_mode_rows()

        self.sync_current()

    def add_mode_rows(self):
        for mode in self.backend.modes(self.connector):
            row = self.mode_row(mode)
            self.modes_group.add(row)
            self.mode_rows.append(row)
            self.remember_current(mode)

    def remember_current(self, mode):
        if mode.current:
            self.current = mode

    def sync_current(self):
        """Shows the scale and orientation of the current mode, without applying them again."""
        self.scale_row.set_sensitive(self.current is not None)
        self.rotation_row.set_sensitive(self.current is not None)
        if self.current is None:
            self.scale_row.set_subtitle("no current mode")
            return

        settings = choice.size_settings(self.current.width, self.current.height)
        change = choice.change_for(self.backend, self.connector, self.current.id)
        self.syncing = True
        self.scale_row.set_selected(choice_index(SCALES, settings.get("scale")))
        self.rotation_row.set_selected(choice_index(ROTATIONS, change.rotation))
        self.syncing = False
        self.scale_row.set_subtitle(f"{change.scale * 100:g}% at {self.current.width}×{self.current.height}")

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

    def apply(self, mode_id, persistent):
        """Applies mode_id; on failure shows a toast and returns False."""
        try:
            choice.apply_mode(self.backend, self.connector, mode_id, persistent)
        except Exception as error:  # xrandr, kscreen-doctor or DBus refused the mode
            self.toast(f"Failed: {error}")
            return False

        GLib.timeout_add(600, self.refresh_once)
        return True

    def on_mode(self, _row, mode):
        previous = self.current
        if not self.apply(mode.id, False):
            return

        self.toast(f"{mode.width}×{mode.height} applied")
        if previous is None or previous.id == mode.id:
            self.keep(mode.id)
            return

        self.ask_to_keep(mode.id, previous.id)

    def ask_to_keep(self, mode_id, previous_id):
        dialog = Adw.AlertDialog(heading="Keep this resolution?", body=countdown_text(REVERT_SECONDS))
        dialog.add_response("revert", "Go back")
        dialog.add_response("keep", "Keep")
        dialog.set_response_appearance("keep", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_close_response("revert")

        self.pending = PendingMode(dialog, mode_id, previous_id)
        dialog.connect("response", self.on_keep_response, self.pending)
        GLib.timeout_add_seconds(1, self.count_down, self.pending)
        dialog.present(self)

    def on_keep_response(self, _dialog, response, pending):
        if pending is not self.pending:
            return

        self.pending = None
        if response == "keep":
            self.keep(pending.mode_id)
            return

        self.go_back(pending)

    def count_down(self, pending):
        if pending is not self.pending:
            return GLib.SOURCE_REMOVE

        pending.remaining -= 1
        if pending.remaining > 0:
            pending.dialog.set_body(countdown_text(pending.remaining))
            return GLib.SOURCE_CONTINUE

        self.pending = None
        pending.dialog.force_close()
        self.go_back(pending)
        return GLib.SOURCE_REMOVE

    def keep(self, mode_id):
        """With Remember choice on, makes the mode last past the next login."""
        if not self.remember.get_active():
            return

        try:
            choice.commit(self.backend, self.connector, mode_id)
        except Exception as error:  # GNOME refused to write the mode as persistent
            self.toast(f"Failed: {error}")

    def go_back(self, pending):
        if self.apply(pending.previous_id, False):
            self.toast("Previous resolution restored")

    def on_scale(self, row, _pspec):
        self.save_current_setting("scale", SCALES[row.get_selected()][1])

    def on_rotation(self, row, _pspec):
        self.save_current_setting("rotation", ROTATIONS[row.get_selected()][1])

    def save_current_setting(self, name, value):
        """Saves a setting of the current mode size and applies the mode again with it."""
        if self.syncing or self.current is None:
            return

        choice.save_setting(self.current.width, self.current.height, name, value)
        if self.apply(self.current.id, False):
            self.keep(self.current.id)

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
