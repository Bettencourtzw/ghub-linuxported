"""Physical TKL (ANSI) layout used to draw keyboards and address per-key lighting.

Each key: (label, x, y, w, h, hid_usage) in key units (1u = one alpha key).
`hid_usage` is the USB HID keyboard usage; lighting zone ids are derived from it
(see hidpp/lighting.py).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Key:
    label: str
    x: float
    y: float
    w: float
    h: float
    usage: int


def _row(y, items, x=0.0):
    out = []
    for item in items:
        if item is None:
            x += 0.5
            continue
        label, usage, *w = item
        width = w[0] if w else 1.0
        out.append(Key(label, x, y, width, 1.0, usage))
        x += width
    return out


_F = [(f"F{i}", 0x3A + i - 1) for i in range(1, 13)]
TKL_ANSI: list[Key] = (
    _row(0, [("Esc", 0x29), None, None, *_F[0:4], None, *_F[4:8], None, *_F[8:12]])
    + _row(0, [("PrtSc", 0x46), ("ScrLk", 0x47), ("Pause", 0x48)], x=15.25)
    + _row(1.25, [("`", 0x35), ("1", 0x1E), ("2", 0x1F), ("3", 0x20), ("4", 0x21), ("5", 0x22), ("6", 0x23),
                  ("7", 0x24), ("8", 0x25), ("9", 0x26), ("0", 0x27), ("-", 0x2D), ("=", 0x2E),
                  ("Backspace", 0x2A, 2.0)])
    + _row(1.25, [("Ins", 0x49), ("Home", 0x4A), ("PgUp", 0x4B)], x=15.25)
    + _row(2.25, [("Tab", 0x2B, 1.5), ("Q", 0x14), ("W", 0x1A), ("E", 0x08), ("R", 0x15), ("T", 0x17),
                  ("Y", 0x1C), ("U", 0x18), ("I", 0x0C), ("O", 0x12), ("P", 0x13), ("[", 0x2F), ("]", 0x30),
                  ("\\", 0x31, 1.5)])
    + _row(2.25, [("Del", 0x4C), ("End", 0x4D), ("PgDn", 0x4E)], x=15.25)
    + _row(3.25, [("Caps", 0x39, 1.75), ("A", 0x04), ("S", 0x16), ("D", 0x07), ("F", 0x09), ("G", 0x0A),
                  ("H", 0x0B), ("J", 0x0D), ("K", 0x0E), ("L", 0x0F), (";", 0x33), ("'", 0x34),
                  ("Enter", 0x28, 2.25)])
    + _row(4.25, [("Shift", 0xE1, 2.25), ("Z", 0x1D), ("X", 0x1B), ("C", 0x06), ("V", 0x19), ("B", 0x05),
                  ("N", 0x11), ("M", 0x10), (",", 0x36), (".", 0x37), ("/", 0x38), ("Shift", 0xE5, 2.75)])
    + _row(4.25, [("↑", 0x52)], x=16.25)
    + _row(5.25, [("Ctrl", 0xE0, 1.25), ("Super", 0xE3, 1.25), ("Alt", 0xE2, 1.25), ("", 0x2C, 6.25),
                  ("Alt", 0xE6, 1.25), ("Fn", 0x00, 1.25), ("Menu", 0x65, 1.25), ("Ctrl", 0xE4, 1.25)])
    + _row(5.25, [("←", 0x50), ("↓", 0x51), ("→", 0x4F)], x=15.25)
)

WIDTH_U = 18.25
HEIGHT_U = 6.25

# Handy key groups for presets
WASD = {0x1A, 0x04, 0x16, 0x07}
ARROWS = {0x52, 0x50, 0x51, 0x4F}
FUNCTION_ROW = {k.usage for k in TKL_ANSI if 0x3A <= k.usage <= 0x45}
NUMBER_ROW = {k.usage for k in TKL_ANSI if 0x1E <= k.usage <= 0x27}
