"""Keyboard view: LIGHTSYNC-style lighting editor with live animated preview."""
from __future__ import annotations

import colorsys
import copy
import math
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from .keyboard_widget import KeyboardWidget
from .widgets import Debouncer
from ..hidpp.lighting import DIRECTIONS
from ..model.keyboard_layout import TKL_ANSI, WASD, ARROWS, FUNCTION_ROW, NUMBER_ROW, WIDTH_U, HEIGHT_U

MODES = [("onboard", "Onboard", "input-keyboard-symbolic", "The keyboard's own lighting (G HUB-free default)"),
         ("off", "Off", "weather-clear-night-symbolic", "All LEDs off"),
         ("static", "Static", "starred-symbolic", "One fixed color"),
         ("breathe", "Breathing", "weather-fog-symbolic", "Fades in and out"),
         ("cycle", "Color cycle", "view-refresh-symbolic", "All keys cycle through the spectrum"),
         ("wave", "Color wave", "weather-windy-symbolic", "A rainbow sweeps across the keys"),
         ("ripple", "Ripple", "weather-showers-symbolic", "Light ripples out from each key press"),
         ("perkey", "Per-key", "input-dialpad-symbolic", "Paint every key yourself")]
SWATCHES = [(0, 168, 232), (255, 255, 255), (255, 32, 64), (255, 0, 129), (255, 106, 0), (255, 200, 0),
            (0, 230, 118), (0, 200, 200), (128, 170, 255), (140, 60, 255)]
COLOR_MODES = {"static", "breathe", "ripple", "perkey"}
SPEED_MODES = {"breathe", "cycle", "wave", "ripple"}


def _rgb_to_gdk(rgb):
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1
    return c


def _hsv(h, v=1.0):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, 1.0, v)
    return int(r * 255), int(g * 255), int(b * 255)


class KeyboardView(Adw.BreakpointBin):
    def __init__(self, shell, found):
        super().__init__()
        self.set_size_request(360, 420)
        self.shell = shell
        self.found = found
        self.service = shell.get_application().keyboard_service(found)
        self.state = copy.deepcopy(self.service.state)
        self.brush = tuple(self.state["color"])
        self._loading = False
        self.push = Debouncer(140)
        self.push_brightness = Debouncer(160)
        self._t0 = time.monotonic()

        tb = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.views = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.views, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        self.spinner = Adw.Spinner(visible=False)
        header.pack_end(self.spinner)
        tb.add_top_bar(header)
        self.banner = Adw.Banner()
        tb.add_top_bar(self.banner)
        tb.set_content(self.views)
        self.set_child(tb)

        self.views.add_titled_with_icon(self._lighting_page(), "lighting", "LIGHTSYNC", "starred-symbolic")
        self.views.add_titled_with_icon(self._device_page(), "device", "Device", "input-keyboard-symbolic")

        self._subs = [("status", self.service.on("status", self._on_status)),
                      ("info", self.service.on("info", lambda _s: self._fill_info())),
                      ("battery", self.service.on("battery", lambda _b: self._fill_info()))]
        self._on_status(self.service.status, self.service.status_detail)
        self._fill_info()
        self._anim = None
        self._load_state()
        self._update_preview()

    # ------------------------------------------------------------ building
    def _lighting_page(self):
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=1180, margin_top=20, margin_bottom=28, margin_start=16, margin_end=16)
        scroller.set_child(clamp)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        clamp.set_child(col)

        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["card", "hero"])
        top = Gtk.Box(margin_top=14, margin_start=20, margin_end=20)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        titles.append(Gtk.Label(label="LIGHTSYNC", css_classes=["eyebrow"], xalign=0))
        self.mode_title = Gtk.Label(css_classes=["title-2"], xalign=0)
        titles.append(self.mode_title)
        top.append(titles)
        self.hint = Gtk.Label(css_classes=["caption", "dim-label"], xalign=1, valign=Gtk.Align.END, wrap=True,
                              max_width_chars=40)
        top.append(self.hint)
        hero.append(top)
        self.kb = KeyboardWidget(interactive=True, min_height=300)
        self.kb.set_margin_start(12)
        self.kb.set_margin_end(12)
        self.kb.set_margin_bottom(12)
        self.kb.on_paint = self._on_paint
        hero.append(self.kb)
        col.append(hero)

        # effects
        eg = Adw.PreferencesGroup(title="Effect")
        wrap = Adw.WrapBox(child_spacing=10, line_spacing=10)
        self.mode_buttons = {}
        first = None
        for key, label, icon, tip in MODES:
            b = Gtk.ToggleButton(css_classes=["effect-card", "flat"], tooltip_text=tip)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.append(Gtk.Image(icon_name=icon, pixel_size=22))
            box.append(Gtk.Label(label=label, css_classes=["caption-heading"]))
            b.set_child(box)
            if first:
                b.set_group(first)
            first = first or b
            b.connect("toggled", lambda btn, k=key: btn.get_active() and self._set_mode(k))
            self.mode_buttons[key] = b
            wrap.append(b)
        eg.add(wrap)
        col.append(eg)

        # color
        self.color_group = Adw.PreferencesGroup(title="Color")
        sw_row = Adw.WrapBox(child_spacing=10, line_spacing=10)
        self.swatch_buttons = []
        for rgb in SWATCHES:
            b = Gtk.Button(css_classes=["swatch"], tooltip_text="#%02X%02X%02X" % rgb)
            prov = Gtk.CssProvider()
            prov.load_from_string(".swatch { background: rgb(%d,%d,%d); }" % rgb)
            b.get_style_context().add_provider(prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2)
            b.connect("clicked", lambda _b, c=rgb: self._set_color(c))
            b.rgb = rgb
            self.swatch_buttons.append(b)
            sw_row.append(b)
        self.color_btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER,
                                               tooltip_text="Custom color")
        self.color_btn.connect("notify::rgba", self._on_custom_color)
        sw_row.append(self.color_btn)
        self.color_group.add(sw_row)
        col.append(self.color_group)

        # animation
        self.anim_group = Adw.PreferencesGroup(title="Animation")
        self.speed = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 10, 1)
        self.speed.set_hexpand(True)
        self.speed.set_draw_value(False)
        for v, lab in ((1, "Slow"), (10, "Fast")):
            self.speed.add_mark(v, Gtk.PositionType.BOTTOM, lab)
        self.speed.connect("value-changed", lambda *_: self._on_speed())
        sr = Adw.ActionRow(title="Speed")
        sbox = Gtk.Box(width_request=320, hexpand=True)
        sbox.append(self.speed)
        sr.add_suffix(sbox)
        self.anim_group.add(sr)
        self.direction = Adw.ComboRow(title="Direction", model=Gtk.StringList.new([d[0] for d in DIRECTIONS]))
        self.direction.connect("notify::selected", lambda *_: self._on_direction())
        self.anim_group.add(self.direction)
        col.append(self.anim_group)

        # per-key tools
        self.perkey_group = Adw.PreferencesGroup(
            title="Per-key painting",
            description="Pick a color above, then click or drag across keys on the keyboard.")
        tools = Adw.WrapBox(child_spacing=8, line_spacing=8)
        for label, cb in (("Fill all", self._fill_all), ("Clear", self._clear_keys),
                          ("WASD + arrows", lambda: self._preset("wasd")),
                          ("Gamer (cyan + pink)", lambda: self._preset("gamer")),
                          ("Rainbow columns", lambda: self._preset("rainbow")),
                          ("Function row glow", lambda: self._preset("frow"))):
            b = Gtk.Button(label=label, css_classes=["pill"])
            b.connect("clicked", lambda _b, cb=cb: cb())
            tools.append(b)
        self.perkey_group.add(tools)
        col.append(self.perkey_group)

        # brightness
        bg = Adw.PreferencesGroup(title="Brightness",
                                  description="Hardware brightness — the same level as FN + F8 on the keyboard.")
        self.bright = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.bright.set_hexpand(True)
        self.bright.set_value_pos(Gtk.PositionType.RIGHT)
        for v in (0, 25, 50, 75, 100):
            self.bright.add_mark(v, Gtk.PositionType.BOTTOM, None)
        self.bright.connect("value-changed", lambda *_: self._on_brightness())
        br = Adw.ActionRow(title="Level")
        bbox = Gtk.Box(width_request=320, hexpand=True)
        bbox.append(self.bright)
        br.add_suffix(bbox)
        bg.add(br)
        col.append(bg)

        note = Gtk.Label(wrap=True, xalign=0, css_classes=["caption", "dim-label"],
                         label="Custom lighting is applied by this app and kept alive from the tray, also after "
                               "the keyboard sleeps or reconnects. Choose Onboard to hand lighting back to the "
                               "keyboard; quitting the app does the same.")
        col.append(note)
        return scroller

    def _device_page(self):
        page = Adw.PreferencesPage()
        self.dev_group = Adw.PreferencesGroup(title="Device")
        page.add(self.dev_group)
        self.dev_rows = {}
        for k, t in (("name", "Name"), ("battery", "Battery"), ("conn", "Connection"), ("fw", "Firmware"),
                     ("unit", "Unit ID"), ("model", "Model"), ("zones", "Per-key zones"), ("effects", "Effects")):
            r = Adw.ActionRow(title=t, css_classes=["property"], subtitle_selectable=True)
            self.dev_rows[k] = r
            self.dev_group.add(r)
        return page

    # ------------------------------------------------------------ state
    def _load_state(self):
        self._loading = True
        st = self.state
        self.mode_buttons[st["mode"]].set_active(True)
        self.speed.set_value(self._period_to_speed(st["period"], st["mode"]))
        dirs = [d[1] for d in DIRECTIONS]
        self.direction.set_selected(dirs.index(st["direction"]) if st["direction"] in dirs else 0)
        if st["brightness"] is not None:
            self.bright.set_value(st["brightness"])
        self.color_btn.set_rgba(_rgb_to_gdk(st["color"]))
        self._loading = False
        self._sync_visibility()

    def _sync_visibility(self):
        mode = self.state["mode"]
        self.color_group.set_visible(mode in COLOR_MODES)
        self.anim_group.set_visible(mode in SPEED_MODES)
        self.direction.set_visible(mode == "wave")
        self.perkey_group.set_visible(mode == "perkey")
        self.kb.interactive = mode == "perkey"
        self.kb.set_cursor_from_name("crosshair" if mode == "perkey" else "default")
        label, tip = next((m[1], m[3]) for m in MODES if m[0] == mode)
        self.mode_title.set_label(label)
        self.hint.set_label(tip)
        for b in self.swatch_buttons:
            (b.add_css_class if tuple(b.rgb) == tuple(self.brush) else b.remove_css_class)("selected")

    def _send(self):
        st = copy.deepcopy(self.state)

        def done(_r):
            self.spinner.set_visible(False)

        def fail(exc):
            self.spinner.set_visible(False)
            self.shell.toast(f"Keyboard: {exc}")
        self._update_preview()
        self.spinner.set_visible(True)
        self.service.submit(lambda s: s.apply(st), done, fail)

    def _changed(self):
        if not self._loading:
            self._update_preview()
            self.push(self._send)

    # ------------------------------------------------------------ handlers
    def _set_mode(self, mode):
        if self._loading:
            self.state["mode"] = mode
            return
        self.state["mode"] = mode
        if mode == "perkey" and not self.state["keys"]:
            self._preset("gamer", send=False)
        self._sync_visibility()
        self._send()

    def _set_color(self, rgb):
        self.brush = tuple(rgb)
        if self.state["mode"] != "perkey":
            self.state["color"] = list(rgb)
            self._changed()
        self._loading = True
        self.color_btn.set_rgba(_rgb_to_gdk(rgb))
        self._loading = False
        self._sync_visibility()

    def _on_custom_color(self, btn, _p):
        if self._loading:
            return
        c = btn.get_rgba()
        self._set_color((int(c.red * 255), int(c.green * 255), int(c.blue * 255)))

    def _period_to_speed(self, period, mode):
        if mode == "ripple":
            return max(1, min(10, 11 - period // 500))
        return max(1, min(10, round(11 - period / 1000)))

    def _on_speed(self):
        v = int(self.speed.get_value())
        self.state["period"] = int((11 - v) * 1000) if self.state["mode"] != "ripple" else int((11 - v) * 500)
        self._changed()

    def _on_direction(self):
        self.state["direction"] = DIRECTIONS[self.direction.get_selected()][1]
        self._changed()

    def _on_brightness(self):
        if self._loading:
            return
        v = int(self.bright.get_value())
        self.state["brightness"] = v
        self.push_brightness(lambda: self.service.submit(lambda s: s.set_brightness(v),
                                                         on_error=lambda e: self.shell.toast(f"Brightness: {e}")))

    def _on_paint(self, usages):
        if self.state["mode"] != "perkey":
            return
        for u in usages:
            self.state["keys"][str(u)] = list(self.brush)
        self.kb.set_colors(self._perkey_colors())
        self._changed()

    def _fill_all(self):
        self.state["keys"] = {str(k.usage): list(self.brush) for k in TKL_ANSI}
        self._changed()

    def _clear_keys(self):
        self.state["keys"] = {}
        self._changed()

    def _preset(self, name, send=True):
        keys = {}
        if name == "wasd":
            keys = {str(k.usage): [20, 22, 30] for k in TKL_ANSI}
            keys.update({str(u): list(self.brush) for u in WASD | ARROWS})
        elif name == "gamer":
            keys = {str(k.usage): [0, 168, 232] for k in TKL_ANSI}
            keys.update({str(u): [255, 0, 129] for u in WASD | ARROWS})
        elif name == "rainbow":
            keys = {str(k.usage): list(_hsv((k.x + k.w / 2) / WIDTH_U)) for k in TKL_ANSI}
        elif name == "frow":
            keys = {str(k.usage): [24, 26, 34] for k in TKL_ANSI}
            fkeys = sorted((k for k in TKL_ANSI if k.usage in FUNCTION_ROW | NUMBER_ROW), key=lambda k: k.x)
            for k in fkeys:
                keys[str(k.usage)] = list(_hsv(0.52 + 0.3 * k.x / WIDTH_U))
        self.state["keys"] = keys
        if send:
            self._changed()

    # ------------------------------------------------------------ preview
    def _perkey_colors(self):
        base = tuple(self.state["base"])
        out = {k.usage: base for k in TKL_ANSI}
        out.update({int(u): tuple(c) for u, c in self.state["keys"].items()})
        return out

    def _update_preview(self):
        animated = self.state["mode"] in {"breathe", "cycle", "wave", "ripple"}
        if self._anim and not animated:
            GLib.source_remove(self._anim)
            self._anim = None
        elif animated and not self._anim:
            self._anim = GLib.timeout_add(33, self._animate)
        self._animate(force=True)

    def _animate(self, force=False):
        if not force and not self.get_mapped():
            return True
        st, t = self.state, time.monotonic() - self._t0
        mode, rgb = st["mode"], tuple(st["color"])
        period = max(0.3, st["period"] / 1000)
        if mode == "onboard":
            colors = {k.usage: (0, 120, 170) for k in TKL_ANSI}
        elif mode == "off":
            colors = {}
        elif mode == "static":
            colors = {k.usage: rgb for k in TKL_ANSI}
        elif mode == "breathe":
            f = 0.12 + 0.88 * (0.5 - 0.5 * math.cos(2 * math.pi * t / period))
            colors = {k.usage: tuple(int(c * f) for c in rgb) for k in TKL_ANSI}
        elif mode == "cycle":
            colors = {k.usage: _hsv(t / period) for k in TKL_ANSI}
        elif mode == "wave":
            d = st["direction"]
            colors = {}
            for k in TKL_ANSI:
                cx, cy = (k.x + k.w / 2) / WIDTH_U, (k.y + 0.5) / HEIGHT_U
                pos = {1: cx, 6: 1 - cx, 2: cy, 7: 1 - cy, 3: abs(cx - 0.5) * 2, 8: 1 - abs(cx - 0.5) * 2}.get(d, cx)
                colors[k.usage] = _hsv(pos * 0.9 - t / period)
        elif mode == "ripple":
            # simulate a ripple from a moving pseudo key press
            cx = 0.5 + 0.35 * math.sin(t * 0.9)
            cy = 0.5 + 0.3 * math.cos(t * 0.6)
            r = (t * (2.0 / period)) % 1.4
            colors = {}
            for k in TKL_ANSI:
                dx = (k.x + k.w / 2) / WIDTH_U - cx
                dy = ((k.y + 0.5) / HEIGHT_U - cy) * 0.4
                dist = math.hypot(dx, dy)
                f = max(0.0, 1 - abs(dist - r) * 7)
                colors[k.usage] = tuple(int(c * f) for c in rgb)
        else:
            colors = self._perkey_colors()
        self.kb.set_colors(colors)
        return True

    # ------------------------------------------------------------ device info
    def _on_status(self, status, detail):
        self.banner.set_revealed(status != "connected")
        self.banner.set_title({"searching": "Looking for the keyboard…",
                               "asleep": "The keyboard is asleep — press a key to wake it.",
                               "permission": "No access to the keyboard (udev rule missing)."}.get(status, detail))

    def _fill_info(self):
        s = self.service
        ident = s.identity
        if not ident:
            return
        self.dev_rows["name"].set_subtitle(ident.name)
        b = s.battery
        self.dev_rows["battery"].set_subtitle(f"{b.percent}% · {b.label}" if b else "—")
        self.dev_rows["conn"].set_subtitle(ident.connection)
        self.dev_rows["fw"].set_subtitle("\n".join(ident.firmware) or "—")
        self.dev_rows["unit"].set_subtitle(ident.unit_id or "—")
        self.dev_rows["model"].set_subtitle(f"{ident.model_id} {ident.model_string}".strip() or "—")
        if s.lighting:
            info = s.lighting.info
            self.dev_rows["zones"].set_subtitle(f"{len(info.zones)} zones")
            self.dev_rows["effects"].set_subtitle(", ".join(e.name for e in info.effects) or "—")
            if info.brightness is not None and self.state["brightness"] is None:
                self.state["brightness"] = info.brightness
                self._loading = True
                self.bright.set_value(info.brightness)
                self._loading = False

    def close(self):
        self.push_brightness.flush()
        self.push.flush()
        for event, cb in self._subs:
            self.service.off(event, cb)
        if self._anim:
            GLib.source_remove(self._anim)
            self._anim = None
        self.shell.get_application().keyboard_view_closed(self.found, self.state["mode"])
