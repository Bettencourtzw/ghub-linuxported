"""Application: single instance, tray integration, close-to-tray, themes."""
from __future__ import annotations

import signal
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import storage  # noqa: E402
from ..assets import APP_ICON, APP_ICON_NAME  # noqa: E402
from . import theme  # noqa: E402


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=storage.APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        GLib.set_application_name(storage.APP_NAME)
        self.win = None
        self.tray = None
        self._held = False
        self._told_tray = False
        self.add_main_option("background", ord("b"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Start hidden in the tray", None)

    # ---------- lifecycle
    def do_startup(self):
        Adw.Application.do_startup(self)
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(str(APP_ICON.parent))
        Gtk.Window.set_default_icon_name(APP_ICON_NAME)
        cfg = storage.load_config()
        theme.apply(cfg.get("theme", "ghub"))

        def act(name, cb, param=None, accels=None):
            a = Gio.SimpleAction.new(name, GLib.VariantType(param) if param else None)
            a.connect("activate", lambda _a, p: cb(p))
            self.add_action(a)
            if accels:
                self.set_accels_for_action(f"app.{name}" if not param else f"app.{name}::x", accels)
        act("quit", lambda _p: self.really_quit(), accels=["<Control>q"])
        act("about", lambda _p: self._about())
        act("rescan", lambda _p: self.win and self.win.home.rescan())
        act("theme", lambda p: self._set_theme(p.get_string()), param="s")

        # Always run the tray: the item (re)registers whenever a tray host
        # (Waybar, KDE...) appears, so a bar restart brings the icon back.
        from ..tray.main import Tray
        self.tray = Tray(on_open=self.show_window, on_quit=self.really_quit)
        self.tray.start()
        self.hold()  # keep running without a window
        self._held = True
        self.keyboards = {}  # FoundDevice.key -> KeyboardService (lives as long as the app)
        self._restore_keyboards()
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: self.really_quit() or False)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: self.really_quit() or False)

    def do_command_line(self, cmdline):
        opts = cmdline.get_options_dict().end().unpack()
        if opts.get("background") and self.tray:
            return 0
        self.show_window()
        return 0

    def do_activate(self):
        self.show_window()

    def show_window(self):
        if self.win is None:
            from .shell import AppWindow
            self.win = AppWindow(self)
            self.win.connect("close-request", self._on_close)
        self.win.set_visible(True)
        self.win.present()
        self.win.home.paused = self.win.nav.get_visible_page() is not self.win.home
        self.win.home.rescan()

    def _on_close(self, win):
        win.set_visible(False)
        win.home.paused = True  # don't keep waking wireless devices while hidden
        if not self._told_tray:
            self._told_tray = True
            from ..tray.sni import notify
            from ..tray.main import tray_host_available
            where = ("Right-click the tray icon and choose Quit to exit." if tray_host_available() else
                     "Open it again from the app menu; use the menu's Quit (Ctrl+Q) to exit.")
            notify("G HUB is still running in the background", where, "io.github.ghub_linuxported")
        return True

    def really_quit(self):
        if self.win:
            for page in list(self.win.nav.get_navigation_stack()):
                view = getattr(page, "view", None)
                if view:
                    view.close()
        for svc in self.keyboards.values():
            svc.stop()  # gives lighting control back to the keyboard
        if self.tray:
            self.tray.stop()
        if self._held:
            self.release()
            self._held = False
        self.quit()

    def devices_changed(self, devs):
        if self.tray:
            self.tray.set_devices(devs)

    # ---------- keyboards (lighting must be kept alive by a running service)
    def keyboard_service(self, found):
        svc = self.keyboards.get(found.key)
        if svc and svc.identity and found.unit_id and svc.identity.unit_id != found.unit_id:
            svc.stop()
            del self.keyboards[found.key]
            svc = None
        if svc is None and found.unit_id:
            for key, existing in list(self.keyboards.items()):
                if (existing.found.pid == found.pid and existing.identity and
                        existing.identity.unit_id == found.unit_id):
                    svc = self.keyboards.pop(key)
                    svc.found = found
                    self.keyboards[found.key] = svc
                    break
        if svc is None:
            from ..keyboard_service import KeyboardService
            svc = KeyboardService(lambda fn, *a: GLib.idle_add(lambda: fn(*a) and False), found)
            svc.on("battery", lambda b, f=found: self._keyboard_battery(f, b))
            self.keyboards[found.key] = svc
            svc.start()
        return svc

    def keyboard_view_closed(self, found, mode):
        svc = self.keyboards.get(found.key)
        if svc and mode == "onboard":
            svc.stop()  # nothing to keep alive
            del self.keyboards[found.key]

    def _keyboard_battery(self, found, battery):
        found.battery = battery
        if self.tray:
            self.tray.keyboard_battery(found)

    def _restore_keyboards(self):
        """Start services for keyboards with saved custom lighting (also when started hidden)."""
        import threading
        from ..devices import scan
        from ..keyboard_service import load_state, config_key

        def work():
            try:
                devs, _ = scan()
            except Exception as exc:  # noqa: BLE001
                print("startup scan failed:", exc)
                return
            GLib.idle_add(lambda: [self.keyboard_service(d) for d in devs
                                   if d.model == "keyboard" and load_state(config_key(d))["mode"] != "onboard"]
                          and False)
            GLib.idle_add(lambda: self.devices_changed(devs) and False)
        threading.Thread(target=work, daemon=True).start()

    # ---------- misc
    def _set_theme(self, name):
        storage.update_config({"theme": name})
        theme.apply(name)
        if self.win:
            self.win.queue_draw()

    def _about(self):
        about = Adw.AboutDialog(
            application_name=storage.APP_NAME, application_icon=APP_ICON_NAME, version="2.0.0",
            developer_name="Bettencourtzw", license_type=Gtk.License.MIT_X11,
            website="https://github.com/Bettencourtzw/ghub-linuxported",
            comments="Local, offline control panel for Logitech G devices on Linux.\n"
                     "Not affiliated with or endorsed by Logitech.")
        about.add_credit_section("Protocol research", [
            "xatuke/logitech-superstrike-pro-x2-controller", "kazehana99k (HITS 0x1B0C)",
            "oddvalue & mclol0/linux-superstrike", "Solaar & libratbag", "OpenRGB"])
        about.present(self.win)


def main():
    return App().run(sys.argv)
