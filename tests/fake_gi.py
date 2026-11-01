"""
Fake gi, to test the window and the GNOME backend without GTK, libadwaita or DBus.

Each widget keeps what it received (subtitle, children, suffixes, signals) for the
tests to check; signals fire with widget.emit(name, *args).
"""

import sys
import types


class Widget:
    def __init__(self, **props):
        self.init_props = props
        self.children = []
        self.suffixes = []
        self.css_classes = []
        self.handlers = {}
        self.toasts = []
        self.responses = []
        self.subtitle = props.get("subtitle")
        self.text = ""
        self.active = False
        self.sensitive = True
        self.activatable = False
        self.child = None
        self.content = None
        self.top_bars = []
        self.appearances = {}
        self.presented_on = []

    def connect(self, signal, handler, *args):
        self.handlers[signal] = (handler, args)

    def emit(self, signal, *extra):
        handler, args = self.handlers[signal]
        return handler(self, *extra, *args)

    def add(self, child):
        self.children.append(child)

    def remove(self, child):
        self.children.remove(child)

    def add_suffix(self, widget):
        self.suffixes.append(widget)

    def add_css_class(self, name):
        self.css_classes.append(name)

    def add_top_bar(self, bar):
        self.top_bars.append(bar)

    def add_toast(self, toast):
        self.toasts.append(toast)

    def add_response(self, response_id, label):
        self.responses.append((response_id, label))

    def set_response_appearance(self, response_id, appearance):
        self.appearances[response_id] = appearance

    def set_subtitle(self, text):
        self.subtitle = text

    def set_text(self, text):
        self.text = text

    def get_text(self):
        return self.text

    def set_active(self, value):
        self.active = value

    def get_active(self):
        return self.active

    def set_sensitive(self, value):
        self.sensitive = value

    def set_activatable(self, value):
        self.activatable = value

    def set_child(self, child):
        self.child = child

    def set_content(self, content):
        self.content = content

    def present(self, parent=None):
        self.presented_on.append(parent)


class ApplicationWindow(Widget):
    def present(self, parent=None):
        super().present(parent)
        self.init_props["application"].props.active_window = self


class AlertDialog(Widget):
    created = []

    def __init__(self, **props):
        super().__init__(**props)
        AlertDialog.created.append(self)


class Application:
    created = []

    def __init__(self, application_id):
        Application.created.append(self)
        self.application_id = application_id
        self.props = types.SimpleNamespace(active_window=None)
        self.run_args = None

    def run(self, argv):
        self.run_args = argv
        self.do_activate()
        return 0


class Image(Widget):
    @classmethod
    def new_from_icon_name(cls, name):
        return cls(icon_name=name)


class GError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


class Subprocess:
    created = []

    def __init__(self, argv, flags):
        self.argv = argv
        self.flags = flags
        self.callback = None
        self.status = 0
        self.stdout = ""
        self.error = None

    @classmethod
    def new(cls, argv, flags):
        process = cls(argv, flags)
        cls.created.append(process)
        return process

    def communicate_utf8_async(self, stdin, cancellable, callback):
        self.callback = callback

    def communicate_utf8_finish(self, result):
        if self.error:
            raise GError(self.error)
        return True, self.stdout, None

    def get_exit_status(self):
        return self.status

    def finish(self, status=0, stdout="", error=None):
        """Simulates the end of the process and calls the communicate_utf8_async callback."""
        self.status, self.stdout, self.error = status, stdout, error
        self.callback(self, "resultado")


class DBusProxy:
    """new_for_bus_sync returns DBusProxy.next, which the test sets up; raises if it is an exception."""

    next = None
    calls = []

    @classmethod
    def new_for_bus_sync(cls, *args):
        cls.calls.append(args)
        if isinstance(cls.next, Exception):
            raise cls.next
        return cls.next


class Variant:
    def __init__(self, signature, value):
        self.signature = signature
        self.value = value


def namespace(name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    return module


Gtk = namespace(
    "gi.repository.Gtk",
    Button=type("Button", (Widget,), {}),
    Label=type("Label", (Widget,), {}),
    Image=Image,
    Align=types.SimpleNamespace(CENTER="center"),
)

Adw = namespace(
    "gi.repository.Adw",
    ApplicationWindow=ApplicationWindow,
    Application=Application,
    ToastOverlay=type("ToastOverlay", (Widget,), {}),
    ToolbarView=type("ToolbarView", (Widget,), {}),
    HeaderBar=type("HeaderBar", (Widget,), {}),
    PreferencesPage=type("PreferencesPage", (Widget,), {}),
    PreferencesGroup=type("PreferencesGroup", (Widget,), {}),
    ActionRow=type("ActionRow", (Widget,), {}),
    SwitchRow=type("SwitchRow", (Widget,), {}),
    EntryRow=type("EntryRow", (Widget,), {}),
    Toast=type("Toast", (Widget,), {}),
    AlertDialog=AlertDialog,
    ResponseAppearance=types.SimpleNamespace(DESTRUCTIVE="destructive"),
)

Gio = namespace(
    "gi.repository.Gio",
    Subprocess=Subprocess,
    SubprocessFlags=types.SimpleNamespace(NONE=0, STDOUT_PIPE=1, STDERR_MERGE=2),
    DBusProxy=DBusProxy,
    BusType=types.SimpleNamespace(SESSION="session"),
    DBusProxyFlags=types.SimpleNamespace(NONE="none", DO_NOT_AUTO_START="do-not-auto-start"),
    DBusCallFlags=types.SimpleNamespace(NONE="none"),
)

GLib = namespace(
    "gi.repository.GLib",
    Error=GError,
    Variant=Variant,
    SOURCE_REMOVE=False,
    timeouts=[],
    timeout_add=lambda ms, callback: GLib.timeouts.append((ms, callback)),
)

repository = namespace("gi.repository", Adw=Adw, Gio=Gio, GLib=GLib, Gtk=Gtk)
gi = namespace("gi", repository=repository, versions={})
gi.require_version = lambda name, version: gi.versions.__setitem__(name, version)


def install():
    """Puts the fake gi in place of the real one (or of its absence) and clears what was recorded."""
    sys.modules["gi"] = gi
    sys.modules["gi.repository"] = repository
    reset()


def reset():
    AlertDialog.created.clear()
    Application.created.clear()
    Subprocess.created.clear()
    DBusProxy.calls.clear()
    DBusProxy.next = None
    GLib.timeouts.clear()
