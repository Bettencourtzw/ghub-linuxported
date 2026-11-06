"""Custom-drawn TKL keyboard showing per-key RGB, with click/drag painting."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from . import draw as d
from ..model.keyboard_layout import TKL_ANSI, WIDTH_U, HEIGHT_U

OFF = (0, 0, 0)


class KeyboardWidget(Gtk.Widget):
    """colors: {hid_usage: (r, g, b)} 0..255. on_paint(usages:set) is called while painting."""

    def __init__(self, interactive=True, min_height=260):
        super().__init__()
        self.colors: dict[int, tuple[int, int, int]] = {}
        self.selected: set[int] = set()
        self.hover: int | None = None
        self.interactive = interactive
        self.on_paint = None
        self._painting = False
        self.set_size_request(int(min_height * WIDTH_U / HEIGHT_U * 0.55) if interactive else 200, min_height)
        self.set_hexpand(True)
        if interactive:
            self.set_cursor_from_name("crosshair")
            drag = Gtk.GestureDrag()
            drag.connect("drag-begin", self._begin)
            drag.connect("drag-update", self._update)
            drag.connect("drag-end", lambda *_: setattr(self, "_painting", False))
            self.add_controller(drag)
            motion = Gtk.EventControllerMotion()
            motion.connect("motion", lambda _c, x, y: self._set_hover(self._hit(x, y)))
            motion.connect("leave", lambda *_: self._set_hover(None))
            self.add_controller(motion)
        self._start = (0, 0)

    # ---- data
    def set_colors(self, colors: dict[int, tuple[int, int, int]]):
        self.colors = dict(colors)
        self.queue_draw()

    def fill(self, rgb):
        self.colors = {k.usage: rgb for k in TKL_ANSI}
        self.queue_draw()

    # ---- geometry
    def _geom(self):
        w, h = self.get_width(), self.get_height()
        u = min((w - 8) / (WIDTH_U + 0.7), (h - 8) / (HEIGHT_U + 0.7))  # room for the bezel
        ox = (w - u * WIDTH_U) / 2
        oy = (h - u * HEIGHT_U) / 2
        return ox, oy, u

    def _hit(self, x, y):
        ox, oy, u = self._geom()
        for k in TKL_ANSI:
            kx, ky = ox + k.x * u, oy + k.y * u
            if kx <= x <= kx + k.w * u and ky <= y <= ky + k.h * u:
                return k.usage
        return None

    def _set_hover(self, usage):
        if usage != self.hover:
            self.hover = usage
            self.queue_draw()

    def _paint_at(self, x, y):
        usage = self._hit(x, y)
        if self.interactive and usage is not None and self.on_paint:
            self.on_paint({usage})

    def _begin(self, _g, x, y):
        self._start = (x, y)
        self._painting = True
        self._paint_at(x, y)

    def _update(self, _g, dx, dy):
        if self._painting:
            self._paint_at(self._start[0] + dx, self._start[1] + dy)

    # ---- drawing
    def do_snapshot(self, snap):
        fg = self.get_color()
        ac = d.accent()
        ox, oy, u = self._geom()
        pad = max(1.5, u * 0.07)
        # chassis
        chassis = d.Path().rrect(ox - u * 0.35, oy - u * 0.35, u * (WIDTH_U + 0.7), u * (HEIGHT_U + 0.7),
                                 u * 0.45).done()
        d.gradient_fill(snap, chassis, d.rect(ox, oy - u * 0.35, u * WIDTH_U, u * (HEIGHT_U + 0.7)),
                        d.rgba(0.11, 0.12, 0.15), d.rgba(0.06, 0.065, 0.08))
        d.stroke(snap, chassis, d.rgba(1, 1, 1, 0.06), 1.2)
        for k in TKL_ANSI:
            x, y, w, h = ox + k.x * u + pad, oy + k.y * u + pad, k.w * u - 2 * pad, k.h * u - 2 * pad
            r, g, b = (c / 255 for c in self.colors.get(k.usage, OFF))
            lit = max(r, g, b) > 0.02
            if lit:  # under-glow halo
                halo = d.Path().rrect(x - pad * 0.9, y - pad * 0.9, w + pad * 1.8, h + pad * 1.8, u * 0.2).done()
                d.fill(snap, halo, d.rgba(r, g, b, 0.28))
            cap = d.Path().rrect(x, y, w, h, u * 0.14).done()
            d.gradient_fill(snap, cap, d.rect(x, y, w, h), d.rgba(0.20, 0.21, 0.25), d.rgba(0.14, 0.15, 0.18))
            sel = k.usage in self.selected
            if sel or k.usage == self.hover:
                d.stroke(snap, cap, d.with_alpha(ac, 0.95 if sel else 0.6), 2 if sel else 1.4)
            else:
                d.stroke(snap, cap, d.rgba(0, 0, 0, 0.45), 1)
            if lit:  # light bleed along the top edge of the cap
                edge = d.Path().rrect(x + w * 0.12, y + 1.5, w * 0.76, max(1.5, u * 0.05), 1).done()
                d.fill(snap, edge, d.rgba(r, g, b, 0.55))
            label_col = d.rgba(r, g, b, 1) if lit else d.with_alpha(fg, 0.28)
            size = 7.5 if len(k.label) > 3 else 9.5
            if u < 34:
                size *= u / 34
            if k.label and size >= 4:
                d.text(self, snap, k.label, x + w / 2, y + h / 2, label_col, size, bold=lit, center=True,
                       valign_center=True)
