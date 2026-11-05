"""Main window: navigation from the device landing page into per-device views."""
from __future__ import annotations

import subprocess

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .. import storage
from .mouse_view import UDEV_RULE, UDEV_CMD


class AppWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=storage.APP_NAME)
        self.set_default_size(1240, 840)
        self.set_size_request(380, 500)
        self.config = storage.load_config()
        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        self.nav = Adw.NavigationView()
        self.toasts.set_child(self.nav)
        from .home import HomePage
        self.home = HomePage(self)
        self.nav.add(self.home)
        self.nav.connect("popped", self._on_popped)
        self.nav.connect("pushed", lambda *_: setattr(self.home, "paused", True))
        self.views = []

    # ---------- device views
    def open_device(self, dev):
        if not dev.awake:
            self.toast(f"{dev.title} is asleep — move it or press a key, then try again")
            return
        if dev.model == "superstrike":
            from .mouse_view import MouseView
            view = MouseView(self, dev)
        elif dev.model == "keyboard":
            from .keyboard_view import KeyboardView
            view = KeyboardView(self, dev)
        else:
            from .generic_view import GenericView
            view = GenericView(self, dev)
        page = Adw.NavigationPage(title=dev.title, child=view)
        page.view = view
        self.nav.push(page)

    def _on_popped(self, _nav, page):
        view = getattr(page, "view", None)
        if view:
            view.close()
        if self.nav.get_visible_page() is self.home:
            self.home.paused = False
            self.home.rescan()

    def devices_changed(self, devs):
        app = self.get_application()
        if app and hasattr(app, "devices_changed"):
            app.devices_changed(devs)

    # ---------- permission
    def build_permission_page(self):
        page = Adw.StatusPage(icon_name="dialog-password-symbolic", title="Allow access to your devices",
                              description="Linux only lets root talk to the control interface of Logitech "
                                          "devices. Install the access rule once, then this window "
                                          "connects automatically.")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, halign=Gtk.Align.CENTER)
        cmd = Gtk.Label(label=UDEV_CMD, selectable=True, wrap=True, max_width_chars=70,
                        css_classes=["monospace", "card"])
        btns = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        install = Gtk.Button(label="Install access rule", css_classes=["suggested-action", "pill"])
        install.connect("clicked", self._install_udev)
        copyb = Gtk.Button(label="Copy command", css_classes=["pill"])
        copyb.connect("clicked", lambda *_: (self.get_clipboard().set(UDEV_CMD), self.toast("Command copied")))
        btns.append(install)
        btns.append(copyb)
        box.append(cmd)
        box.append(btns)
        page.set_child(box)
        return page

    def _install_udev(self, *_):
        script = (f"install -m644 '{UDEV_RULE}' /etc/udev/rules.d/ && udevadm control --reload && "
                  "udevadm trigger --subsystem-match=hidraw")
        try:
            proc = subprocess.Popen(["pkexec", "sh", "-c", script])
        except FileNotFoundError:
            self.toast("pkexec is not available — run the command in a terminal")
            return

        def check():
            if proc.poll() is None:
                return True
            self.toast("Access rule installed" if proc.returncode == 0 else "Installation cancelled or failed")
            self.home.rescan()
            return False
        GLib.timeout_add(300, check)

    def toast(self, text, timeout=3):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(str(text)), timeout=timeout))
