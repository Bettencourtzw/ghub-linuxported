from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from ..service import DeviceService  # noqa: E402
from ..hidpp.transport import SWID_GUI  # noqa: E402
from .. import storage  # noqa: E402

CSS = b"""
.hero {
  padding: 8px;
  background-image: linear-gradient(135deg, alpha(@accent_bg_color, 0.16), alpha(@accent_bg_color, 0.02) 60%);
}
.chip {
  padding: 4px 12px;
  border-radius: 999px;
  background: alpha(currentColor, 0.08);
  font-weight: 600;
  font-size: 0.9em;
}
.chip.accent { background: alpha(@accent_bg_color, 0.18); color: @accent_color; }
.tile { padding: 16px 18px; min-height: 84px; }
.hits-card { padding: 20px 22px; }
.click-pad { min-height: 260px; }
.console { font-size: 0.9em; }
.display { font-size: 42px; font-weight: 800; }
label.accent { color: @accent_color; }
"""


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=storage.APP_ID)
        GLib.set_application_name(storage.APP_NAME)
        self.service = None
        self.win = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        scheme = storage.load_config().get("color_scheme", "system")
        Adw.StyleManager.get_default().set_color_scheme(
            {"light": Adw.ColorScheme.FORCE_LIGHT, "dark": Adw.ColorScheme.FORCE_DARK}.get(
                scheme, Adw.ColorScheme.DEFAULT))
        self.set_accels_for_action("app.quit", ["<Control>q"])
        from gi.repository import Gio
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)

    def do_activate(self):
        if self.win is None:
            from .window import MainWindow
            self.service = DeviceService(dispatch=lambda fn, *a: GLib.idle_add(lambda: fn(*a) and False),
                                         swid=SWID_GUI)
            self.win = MainWindow(self, self.service)
            self.service.start()
        self.win.present()

    def do_shutdown(self):
        if self.service:
            self.service.stop()
        Adw.Application.do_shutdown(self)


def main():
    return App().run(sys.argv)
