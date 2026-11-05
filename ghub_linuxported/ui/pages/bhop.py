from __future__ import annotations

from gi.repository import Adw, Gtk

from .base import Page
from ..widgets import Debouncer
from .. import draw as d


class Timeline(Gtk.Widget):
    """Explains the filter: a lone wheel tick is dropped; a second tick inside the window passes."""

    def __init__(self):
        super().__init__()
        self.window_ms = 200
        self.set_size_request(-1, 110)
        self.set_hexpand(True)

    def do_snapshot(self, snap):
        w, h = self.get_width(), self.get_height()
        fg, ac = self.get_color(), d.accent()
        span = 1200.0
        x0, x1, y = 24, w - 24, h * 0.5

        def px(ms):
            return x0 + (x1 - x0) * ms / span
        d.stroke(snap, d.Path().move(x0, y).line(x1, y).done(), d.with_alpha(fg, 0.25), 2)
        if self.window_ms:
            win = d.Path().rrect(px(100), y - 26, px(100 + self.window_ms) - px(100), 52, 8).done()
            d.fill(snap, win, d.with_alpha(ac, 0.16))
            d.text(self, snap, f"{self.window_ms} ms window", px(100) + 6, y - 46, ac, 9, bold=True)
            ticks = [(100, "1st tick", True), (100 + self.window_ms * 0.6, "2nd tick", True),
                     (1000, "lone tick", False)]
        else:
            ticks = [(100, "tick", True), (450, "tick", True), (1000, "tick", True)]
        for ms, label, passes in ticks:
            x = px(ms)
            dot = d.Path().circle(x, y, 7).done()
            d.fill(snap, dot, ac if passes else d.with_alpha(fg, 0.35))
            if not passes:
                cross = d.Path().move(x - 6, y - 6).line(x + 6, y + 6).move(x + 6, y - 6).line(x - 6, y + 6).done()
                d.stroke(snap, cross, d.rgba(0.88, 0.27, 0.24, 0.95), 2.2, round_cap=True)
            d.text(self, snap, label + ("" if passes else " (ignored)"), x, y + 16, d.with_alpha(fg, 0.7), 8.5,
                   center=True)


class BhopPage(Page):
    key, title, icon = "bhop", "Bhop mode", "view-list-symbolic"
    subtitle = "Bunny-hop scroll filter"

    def build(self):
        self.debounce = Debouncer(200)
        g = self.group("Bhop mode",
                       "Ignores a single accidental scroll-wheel tick. A scroll only goes through when a "
                       "second tick follows within the window, which is what you want when scroll is bound "
                       "to jump. Applies instantly, and is stored in the profile when you save.")
        self.enabled = Adw.SwitchRow(title="Enable bhop filter")
        self.enabled.connect("notify::active", lambda *_: self._changed())
        g.add(self.enabled)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 100, 1000, 10)
        self.scale.set_hexpand(True)
        self.scale.set_draw_value(False)
        for v in (100, 250, 500, 750, 1000):
            self.scale.add_mark(v, Gtk.PositionType.BOTTOM, f"{v}")
        self.scale.connect("value-changed", lambda *_: self._changed())
        self.value_label = Gtk.Label(css_classes=["title-4", "numeric"], width_chars=7)
        self.window_row = Adw.ActionRow(title="Window", subtitle="Time allowed between the two ticks")
        wbox = Gtk.Box(spacing=12, hexpand=True, width_request=440)
        wbox.append(self.scale)
        wbox.append(self.value_label)
        self.window_row.add_suffix(wbox)
        g.add(self.window_row)

        how = self.group("How it works")
        self.timeline = Timeline()
        frame = Gtk.Box(css_classes=["card"], margin_top=6)
        self.timeline.set_margin_top(10)
        self.timeline.set_margin_bottom(10)
        frame.append(self.timeline)
        how.add(frame)
        return self.prefs_page(g, how)

    def _changed(self):
        ms = int(round(self.scale.get_value() / 10) * 10) if self.enabled.get_active() else 0
        self.value_label.set_label(f"{ms} ms" if ms else "off")
        self.window_row.set_sensitive(self.enabled.get_active())
        self.timeline.window_ms = ms
        self.timeline.queue_draw()
        e = self.win.edit
        if self.loading or not e:
            return
        e.bhop_ms = ms
        self.debounce(lambda: self.win.live(lambda s: s.apply_bhop(ms)))
        self.win.changed()

    def fill(self, snap, edit):
        if not edit:
            return
        ms = edit.bhop_ms
        self.enabled.set_active(bool(ms))
        self.scale.set_value(ms or 200)
        self._changed()
        self.widget.set_sensitive(snap.bhop_ms is not None)
