"""Tiny drawing helpers on top of GTK4's native vector API (Gsk paths).

No pycairo needed: widgets override do_snapshot and use these helpers.
"""
from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Graphene, Gsk, Gtk, Pango  # noqa: E402


def rgba(r, g, b, a=1.0) -> Gdk.RGBA:
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = r, g, b, a
    return c


def with_alpha(c: Gdk.RGBA, a: float) -> Gdk.RGBA:
    return rgba(c.red, c.green, c.blue, a)


ACCENT_OVERRIDE: Gdk.RGBA | None = None  # set by theme.apply()


def accent() -> Gdk.RGBA:
    if ACCENT_OVERRIDE is not None:
        return ACCENT_OVERRIDE
    try:
        return Adw.StyleManager.get_default().get_accent_color_rgba()
    except AttributeError:
        return rgba(0.21, 0.52, 0.89)


def is_dark() -> bool:
    return Adw.StyleManager.get_default().get_dark()


def point(x, y) -> Graphene.Point:
    return Graphene.Point().init(x, y)


def rect(x, y, w, h) -> Graphene.Rect:
    return Graphene.Rect().init(x, y, w, h)


class Path:
    """Builder that applies an affine map (ox, oy, sx, sy) to unit-space coordinates."""

    def __init__(self, ox=0.0, oy=0.0, sx=1.0, sy=1.0):
        self.b = Gsk.PathBuilder.new()
        self.ox, self.oy, self.sx, self.sy = ox, oy, sx, sy

    def _p(self, x, y):
        return self.ox + x * self.sx, self.oy + y * self.sy

    def move(self, x, y):
        self.b.move_to(*self._p(x, y))
        return self

    def line(self, x, y):
        self.b.line_to(*self._p(x, y))
        return self

    def curve(self, x1, y1, x2, y2, x3, y3):
        self.b.cubic_to(*self._p(x1, y1), *self._p(x2, y2), *self._p(x3, y3))
        return self

    def close(self):
        self.b.close()
        return self

    def rrect(self, x, y, w, h, r):
        rr = Gsk.RoundedRect()
        x0, y0 = self._p(x, y)
        rr.init_from_rect(rect(x0, y0, w * self.sx, h * self.sy), r * min(self.sx, self.sy))
        self.b.add_rounded_rect(rr)
        return self

    def circle(self, cx, cy, r):
        self.b.add_circle(point(*self._p(cx, cy)), r * min(self.sx, self.sy))
        return self

    def done(self) -> Gsk.Path:
        return self.b.to_path()


def arc_path(cx, cy, r, start, end) -> Gsk.Path:
    """Circular arc from angle start to end (radians, clockwise on screen)."""
    b = Gsk.PathBuilder.new()
    b.move_to(cx + r * math.cos(start), cy + r * math.sin(start))
    sweep = end - start
    steps = max(1, int(abs(sweep) / (math.pi / 2)) + 1)
    for k in range(1, steps + 1):
        a = start + sweep * k / steps
        b.svg_arc_to(r, r, 0, False, sweep > 0, cx + r * math.cos(a), cy + r * math.sin(a))
    return b.to_path()


def fill(snap: Gtk.Snapshot, path: Gsk.Path, color: Gdk.RGBA):
    snap.append_fill(path, Gsk.FillRule.WINDING, color)


def stroke(snap: Gtk.Snapshot, path: Gsk.Path, color: Gdk.RGBA, width=1.5, round_cap=False):
    s = Gsk.Stroke.new(width)
    if round_cap:
        s.set_line_cap(Gsk.LineCap.ROUND)
        s.set_line_join(Gsk.LineJoin.ROUND)
    snap.append_stroke(path, s, color)


def gradient_fill(snap: Gtk.Snapshot, path: Gsk.Path, bounds: Graphene.Rect, top: Gdk.RGBA, bottom: Gdk.RGBA):
    snap.push_fill(path, Gsk.FillRule.WINDING)
    stop0, stop1 = Gsk.ColorStop(), Gsk.ColorStop()
    stop0.offset, stop0.color = 0.0, top
    stop1.offset, stop1.color = 1.0, bottom
    snap.append_linear_gradient(bounds, point(bounds.get_x(), bounds.get_y()),
                                point(bounds.get_x(), bounds.get_y() + bounds.get_height()), [stop0, stop1])
    snap.pop()


def text(widget: Gtk.Widget, snap: Gtk.Snapshot, s: str, x: float, y: float, color: Gdk.RGBA,
         size_pt=10.0, bold=False, center=False, valign_center=False):
    layout = widget.create_pango_layout(s)
    fd = Pango.FontDescription()
    fd.set_size(int(size_pt * Pango.SCALE))
    fd.set_weight(Pango.Weight.BOLD if bold else Pango.Weight.NORMAL)
    layout.set_font_description(fd)
    _ink, logical = layout.get_pixel_extents()
    dx = -logical.width / 2 if center else 0
    dy = -logical.height / 2 if valign_center else 0
    snap.save()
    snap.translate(point(x + dx, y + dy))
    snap.append_layout(layout, color)
    snap.restore()
    return logical.width, logical.height
