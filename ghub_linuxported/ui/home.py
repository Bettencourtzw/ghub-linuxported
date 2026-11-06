"""Landing page: every detected Logitech device as a tile (G HUB style home)."""
from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ..devices import scan, FoundDevice
from ..assets import HEADER_LOGO, device_image

SCAN_EVERY_S = 4


class DeviceTile(Gtk.Button):
    def __init__(self, dev: FoundDevice, on_open):
        super().__init__(css_classes=["device-tile", "flat"])
        self.dev = dev
        self.set_size_request(300, -1)
        self.set_valign(Gtk.Align.START)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_child(box)
        self.art = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, height_request=210)
        self._art_key = None
        box.append(self.art)
        box.append(Gtk.Label(label=dev.kind.upper(), css_classes=["eyebrow"], margin_top=8))
        self.name = Gtk.Label(label=dev.title.upper(), css_classes=["tile-name"], wrap=True, justify=Gtk.Justification.CENTER)
        box.append(self.name)
        row = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER, margin_top=4)
        self.conn = Gtk.Label(css_classes=["caption", "dim-label"])
        self.batt = Gtk.Label(css_classes=["battery-pill"])
        row.append(self.conn)
        row.append(self.batt)
        box.append(row)
        self.update(dev)
        self.connect("clicked", lambda *_: on_open(self.dev))

    def update(self, dev: FoundDevice):
        self.dev = dev
        path = device_image(dev)
        art_key = (path, dev.kind)
        if art_key != self._art_key:
            self._art_key = art_key
            child = self.art.get_first_child()
            if child:
                self.art.remove(child)
            if path:
                picture = Gtk.Picture.new_for_filename(str(path))
                picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                picture.set_can_shrink(True)
                picture.set_alternative_text(f"{dev.title} product image; color and layout may vary")
                # Overlay children do not contribute the source image's natural size.
                frame = Gtk.Overlay(width_request=260, height_request=210)
                frame.add_overlay(picture)
                self.art.append(frame)
            else:
                icon = {"mouse": "input-mouse-symbolic", "keyboard": "input-keyboard-symbolic"}.get(
                    dev.kind, "preferences-system-devices-symbolic")
                self.art.append(Gtk.Image(icon_name=icon, pixel_size=96, css_classes=["dim-label"]))
        self.conn.set_label(dev.connection if dev.awake else "Asleep — use it to wake")
        b = dev.battery
        self.batt.set_visible(bool(b) and dev.awake)
        if b:
            self.batt.set_label(f"{'⚡ ' if b.charging else ''}{b.percent}%")
        (self.remove_css_class if dev.awake else self.add_css_class)("asleep")
        self.set_tooltip_text("Open settings" if dev.awake else "Asleep — move or press a key, then click")


class HomePage(Adw.NavigationPage):
    def __init__(self, shell):
        super().__init__(title="Devices", tag="home")
        self.shell = shell
        self.devices: dict[str, FoundDevice] = {}
        self.tiles: dict[str, DeviceTile] = {}
        self._scanning = False
        self.paused = False

        tb = Adw.ToolbarView()
        header = Adw.HeaderBar()
        logo = Gtk.Picture.new_for_filename(str(HEADER_LOGO))
        logo.set_content_fit(Gtk.ContentFit.CONTAIN)
        logo.set_can_shrink(True)
        logo.set_alternative_text("GLP")
        brand = Gtk.Overlay(width_request=96, height_request=40, margin_top=4, margin_bottom=4)
        brand.add_overlay(logo)
        header.set_title_widget(brand)
        menu = Gio.Menu()
        theme = Gio.Menu()
        theme.append("G HUB dark", "app.theme::ghub")
        theme.append("Follow system", "app.theme::system")
        menu.append_submenu("Appearance", theme)
        menu.append("Rescan devices", "app.rescan")
        menu.append("About", "app.about")
        menu.append("Quit", "app.quit")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Menu"))
        tb.add_top_bar(header)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, hhomogeneous=False, vhomogeneous=False)
        tb.set_content(self.stack)

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=36, margin_bottom=36,
                      margin_start=24, margin_end=24)
        self.flow = Adw.WrapBox(child_spacing=24, line_spacing=24, halign=Gtk.Align.CENTER,
                                justify=Adw.JustifyMode.NONE, align=0.5)
        col.append(self.flow)
        scroller.set_child(col)
        self.stack.add_named(scroller, "grid")

        self.empty = Adw.StatusPage(icon_name="preferences-system-devices-symbolic", title="Looking for Logitech devices…",
                                    description="Connect a LIGHTSPEED receiver or a USB cable, then wake the "
                                                "device by moving it or pressing a key.")
        self.empty.set_child(Adw.Spinner(width_request=32, height_request=32))
        self.stack.add_named(self.empty, "empty")
        self.stack.add_named(shell.build_permission_page(), "permission")
        self.stack.set_visible_child_name("empty")
        self.set_child(tb)
        GLib.idle_add(self.rescan)
        GLib.timeout_add_seconds(SCAN_EVERY_S, self._tick)

    def _tick(self):
        if not self.paused:
            self.rescan()
        return True

    def rescan(self, *_):
        if self._scanning:
            return False
        self._scanning = True
        previous = dict(self.devices)

        def work():
            try:
                devs, denied = scan(previous)
            except Exception as exc:  # noqa: BLE001 - never kill the scanner
                print("scan failed:", exc)
                devs, denied = list(previous.values()), False
            GLib.idle_add(self._done, devs, denied)
        threading.Thread(target=work, daemon=True).start()
        return False

    def _done(self, devs, denied):
        self._scanning = False
        if denied and not devs:
            self.stack.set_visible_child_name("permission")
            return False
        keys = [d.key for d in devs]
        for key in list(self.tiles):
            if key not in keys:
                self.flow.remove(self.tiles.pop(key))
        for d in devs:
            if d.key in self.tiles:
                self.tiles[d.key].update(d)
            else:
                tile = DeviceTile(d, self.shell.open_device)
                self.tiles[d.key] = tile
                self.flow.append(tile)
        self.devices = {d.key: d for d in devs}
        self.stack.set_visible_child_name("grid" if devs else "empty")
        self.shell.devices_changed(devs)
        return False
