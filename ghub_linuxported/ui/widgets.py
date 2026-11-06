"""Custom-drawn widgets (GTK4 snapshot API): mouse diagram, battery ring, helpers."""
from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from . import draw as d  # noqa: E402

BUTTON_SHORT = ["Left", "Right", "Middle", "Back", "Forward"]


def accent_rgba():
    c = d.accent()
    return c.red, c.green, c.blue


def fg_rgba(widget):
    c = widget.get_color()
    return c.red, c.green, c.blue


# ---------------------------------------------------------------- mouse diagram
# Shapes in a unit box (x 0..1, y 0..1); the body is ~0.51:1 like the real
# 63.5 x 125 mm shell. This is an original schematic drawing.
def _body(p):
    p.move(0.50, 0.00).curve(0.80, 0.00, 0.95, 0.10, 0.97, 0.30).curve(1.00, 0.55, 0.98, 0.78, 0.90, 0.90)
    p.curve(0.80, 1.00, 0.20, 1.00, 0.10, 0.90).curve(0.02, 0.78, 0.00, 0.55, 0.03, 0.30)
    p.curve(0.05, 0.10, 0.20, 0.00, 0.50, 0.00).close()


def _left(p):
    p.move(0.485, 0.012).curve(0.24, 0.02, 0.07, 0.10, 0.045, 0.31).line(0.04, 0.40)
    p.curve(0.20, 0.42, 0.36, 0.425, 0.485, 0.425).close()


def _right(p):
    p.move(0.515, 0.012).curve(0.76, 0.02, 0.93, 0.10, 0.955, 0.31).line(0.96, 0.40)
    p.curve(0.80, 0.42, 0.64, 0.425, 0.515, 0.425).close()


def _wheel(p):
    p.rrect(0.445, 0.10, 0.11, 0.19, 0.05)


def _forward(p):
    p.rrect(-0.045, 0.36, 0.075, 0.14, 0.035)


def _back(p):
    p.rrect(-0.045, 0.52, 0.075, 0.14, 0.035)


SHAPES = [_left, _right, _wheel, _back, _forward]


class MouseDiagram(Gtk.Widget):
    """Top view of the mouse. Click a button to select it (calls on_select(i))."""

    def __init__(self, selectable=True, labels=None, height=360):
        super().__init__()
        self.selectable = selectable
        self.labels = labels
        self.selected: int | None = None
        self.hover: int | None = None
        self.pressed: set[int] = set()
        self.on_select = None
        self.set_size_request(int(height * 1.2) if labels else int(height * 0.62), height)
        self.set_hexpand(bool(labels))
        if selectable:
            motion = Gtk.EventControllerMotion()
            motion.connect("motion", lambda _c, x, y: self._set_hover(self._hit(x, y)))
            motion.connect("leave", lambda *_: self._set_hover(None))
            self.add_controller(motion)
            click = Gtk.GestureClick()
            click.connect("released", self._click)
            self.add_controller(click)
            self.set_cursor_from_name("pointer")
        sm = Adw.StyleManager.get_default()
        sm.connect("notify::accent-color", lambda *_: self.queue_draw())
        sm.connect("notify::dark", lambda *_: self.queue_draw())

    def set_labels(self, labels):
        self.labels = labels
        self.queue_draw()

    def set_selected(self, i):
        self.selected = i
        self.queue_draw()

    def flash(self, i: int, down: bool):
        (self.pressed.add if down else self.pressed.discard)(i)
        self.queue_draw()

    def _geom(self):
        w, h = self.get_width(), self.get_height()
        bh = h * 0.92
        bw = bh * 0.51
        ox = (w - bw) / 2 if not self.labels else max(bw * 0.12, w * 0.06)
        return ox, (h - bh) / 2, bw, bh

    def _path(self, shape, geom=None):
        p = d.Path(*(geom or self._geom()))
        shape(p)
        return p.done()

    def _hit(self, x, y):
        geom = self._geom()
        pt = d.point(x, y)
        for i in (2, 3, 4, 0, 1):  # small shapes first
            if self._path(SHAPES[i], geom).in_fill(pt, d.Gsk.FillRule.WINDING):
                return i
        return None

    def _set_hover(self, i):
        if i != self.hover:
            self.hover = i
            self.queue_draw()

    def _click(self, _g, _n, x, y):
        i = self._hit(x, y)
        if i is not None:
            self.set_selected(i)
            if self.on_select:
                self.on_select(i)

    def do_snapshot(self, snap):
        fg = self.get_color()
        ac = d.accent()
        dark = d.is_dark()
        geom = ox, oy, bw, bh = self._geom()
        body = self._path(_body, geom)
        base = 0.22 if dark else 0.95
        d.gradient_fill(snap, body, d.rect(ox, oy, bw, bh), d.rgba(base + 0.06, base + 0.06, base + 0.07),
                        d.rgba(base - 0.06, base - 0.06, base - 0.05))
        d.stroke(snap, body, d.with_alpha(fg, 0.35), 1.6)
        palm = d.Path(*geom).move(0.30, 0.80).curve(0.40, 0.84, 0.60, 0.84, 0.70, 0.80).done()
        d.stroke(snap, palm, d.with_alpha(fg, 0.12), 3, round_cap=True)
        for i, shape in enumerate(SHAPES):
            path = self._path(shape, geom)
            if i in self.pressed:
                col = d.with_alpha(ac, 0.85)
            elif i == self.selected:
                col = d.with_alpha(ac, 0.45)
            elif i == self.hover:
                col = d.with_alpha(ac, 0.22)
            else:
                col = d.with_alpha(fg, 0.05)
            d.fill(snap, path, col)
            hl = i in (self.selected, self.hover) or i in self.pressed
            d.stroke(snap, path, d.with_alpha(ac, 0.95) if hl else d.with_alpha(fg, 0.30),
                     2.4 if i == self.selected else 1.4)
        ribs = d.Path(*geom)
        for k in range(7):
            y = 0.125 + k * 0.023
            ribs.move(0.462, y).line(0.538, y)
        d.stroke(snap, ribs.done(), d.with_alpha(fg, 0.25), 1.2)
        if self.labels:
            self._labels(snap, geom, fg, ac)

    def _labels(self, snap, geom, fg, ac):
        ox, oy, bw, bh = geom
        anchors = [(0.25, 0.22), (0.75, 0.22), (0.5, 0.20), (-0.01, 0.59), (-0.01, 0.43)]
        rows = [0.10, 0.26, 0.42, 0.74, 0.58]
        tx = ox + bw * 1.22
        for i, (ax, ay) in enumerate(anchors):
            px, py = ox + ax * bw, oy + ay * bh
            ly = oy + rows[i] * bh
            sel = i == self.selected
            col = d.with_alpha(ac if sel else fg, 0.9 if sel else 0.35)
            d.fill(snap, d.Path().circle(px, py, 3.5).done(), col)
            line = d.Path().move(px, py).line(tx - 12, ly).line(tx - 4, ly).done()
            d.stroke(snap, line, col, 1.3)
            d.text(self, snap, BUTTON_SHORT[i].upper(), tx, ly - 17, d.with_alpha(fg, 0.55), 8, bold=True)
            label = self.labels[i] if i < len(self.labels) else ""
            d.text(self, snap, label, tx, ly - 1, ac if sel else fg, 11, bold=sel)


# ---------------------------------------------------------------- battery ring
class BatteryRing(Gtk.Widget):
    def __init__(self, size=132):
        super().__init__()
        self.percent: int | None = None
        self.charging = False
        self._shown = 0.0
        self._anim = None
        self.set_size_request(size, size)

    def set_value(self, percent, charging):
        self.percent, self.charging = percent, charging
        if self._anim is None:
            self._anim = GLib.timeout_add(16, self._tick)
        self.queue_draw()

    def _tick(self):
        target = float(self.percent or 0)
        self._shown += (target - self._shown) * 0.15
        self.queue_draw()
        if abs(target - self._shown) < 0.3:
            self._shown = target
            self._anim = None
            return False
        return True

    def do_snapshot(self, snap):
        fg = self.get_color()
        w, h = self.get_width(), self.get_height()
        size = min(w, h)
        cx, cy, r = w / 2, h / 2, size / 2 - 9
        d.stroke(snap, d.Path().circle(cx, cy, r).done(), d.with_alpha(fg, 0.10), 10)
        if self.percent is None:
            main, sub = "—", "battery"
        else:
            if self.percent <= 15 and not self.charging:
                col = d.rgba(0.88, 0.27, 0.24)
            elif self.percent <= 30 and not self.charging:
                col = d.rgba(0.95, 0.62, 0.15)
            else:
                col = d.rgba(0.18, 0.76, 0.49) if self.charging else d.accent()
            frac = max(0.004, min(0.9999, self._shown / 100))
            start = -math.pi / 2
            d.stroke(snap, d.arc_path(cx, cy, r, start, start + 2 * math.pi * frac), col, 10, round_cap=True)
            main, sub = f"{round(self._shown)}%", "charging" if self.charging else "battery"
        d.text(self, snap, main, cx, cy - 6, fg, size * 0.14, bold=True, center=True, valign_center=True)
        d.text(self, snap, sub, cx, cy + size * 0.16, d.with_alpha(fg, 0.6), size * 0.065, center=True,
               valign_center=True)


# ---------------------------------------------------------------- helpers
def toggle_group(labels: list[str], on_change=None, active=0) -> Adw.ToggleGroup:
    g = Adw.ToggleGroup()
    for i, label in enumerate(labels):
        g.add(Adw.Toggle(label=label, name=str(i)))
    g.set_active(active)
    g.set_valign(Gtk.Align.CENTER)
    g._silent = False
    if on_change:
        def changed(grp, _p):
            if not grp._silent:
                on_change(grp.get_active())
        g.connect("notify::active", changed)
    return g


def set_toggle_silent(g: Adw.ToggleGroup, index: int):
    g._silent = True
    g.set_active(index)
    g._silent = False


class Debouncer:
    """Collapse rapid UI changes (sliders) into one device call."""

    def __init__(self, ms=180):
        self.ms = ms
        self._id = None
        self._pending = None

    def __call__(self, fn):
        if self._id:
            GLib.source_remove(self._id)

        self._pending = fn

        def fire():
            self._id = None
            self._pending = None
            fn()
            return False
        self._id = GLib.timeout_add(self.ms, fire)

    def flush(self):
        if self._id:
            GLib.source_remove(self._id)
            self._id = None
        fn, self._pending = self._pending, None
        if fn:
            fn()
