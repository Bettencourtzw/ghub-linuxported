"""Onboard-profile button actions (4 bytes per slot).

  [0x80][0x01][mask BE16]        send mouse button(s)
  [0x80][0x02][modifiers][usage] send key (+ modifiers, HID keyboard usage)
  [0x80][0x03][usage BE16]       send consumer (media) key
  [0x80][0x00][0xFF][0xFF]       no action (disabled)
  [0x90][function][0xFF][data]   built-in function (DPI / profile ...)
  [0x0X]...                      macro reference — preserved verbatim
  [0xFF][0xFF][0xFF][0xFF]       unassigned (firmware default)
"""
from __future__ import annotations

from dataclasses import dataclass

KIND_DEFAULT, KIND_DISABLED, KIND_MOUSE, KIND_KEY, KIND_CONSUMER, KIND_FUNCTION, KIND_RAW = range(7)
KIND_LABELS = {KIND_DEFAULT: "Default", KIND_DISABLED: "Disabled", KIND_MOUSE: "Mouse button",
               KIND_KEY: "Keyboard", KIND_CONSUMER: "Media key", KIND_FUNCTION: "Function",
               KIND_RAW: "Macro / other"}

PHYSICAL_BUTTONS = ["Left click", "Right click", "Middle click (wheel)", "Back (side, rear)", "Forward (side, front)"]
FACTORY_MASKS = [0x0001, 0x0002, 0x0004, 0x0008, 0x0010]

MOUSE_BUTTONS = [("Left click", 0x0001), ("Right click", 0x0002), ("Middle click", 0x0004),
                 ("Back", 0x0008), ("Forward", 0x0010), ("Button 6", 0x0020), ("Button 7", 0x0040),
                 ("Button 8", 0x0080)]
CONSUMER_KEYS = [("Play / Pause", 0x00CD), ("Next track", 0x00B5), ("Previous track", 0x00B6),
                 ("Stop", 0x00B7), ("Mute", 0x00E2), ("Volume up", 0x00E9), ("Volume down", 0x00EA),
                 ("Brightness up", 0x006F), ("Brightness down", 0x0070), ("Calculator", 0x0192),
                 ("Browser home", 0x0223), ("Browser back", 0x0224), ("Browser forward", 0x0225),
                 ("Browser refresh", 0x0227), ("Mail", 0x018A), ("File manager", 0x0194)]
FUNCTIONS = [("Next DPI stage", 0x03), ("Previous DPI stage", 0x04), ("Cycle DPI stages", 0x05),
             ("Default DPI stage", 0x06), ("DPI shift (hold)", 0x07), ("Next profile", 0x08),
             ("Previous profile", 0x09), ("Cycle profiles", 0x0A), ("G-Shift (hold)", 0x0B),
             ("Battery status", 0x0C), ("Scroll up", 0x11), ("Scroll down", 0x10)]
MODIFIERS = [("Ctrl", 0x01), ("Shift", 0x02), ("Alt", 0x04), ("Super", 0x08),
             ("Right Ctrl", 0x10), ("Right Shift", 0x20), ("AltGr", 0x40), ("Right Super", 0x80)]

# HID keyboard usage -> label
_KEY_NAMES = {**{0x04 + i: chr(ord("A") + i) for i in range(26)},
              **{0x1E + i: str((i + 1) % 10) for i in range(10)},
              **{0x3A + i: f"F{i + 1}" for i in range(12)},
              **{0x68 + i: f"F{i + 13}" for i in range(12)},
              0x28: "Enter", 0x29: "Esc", 0x2A: "Backspace", 0x2B: "Tab", 0x2C: "Space", 0x2D: "-",
              0x2E: "=", 0x2F: "[", 0x30: "]", 0x31: "\\", 0x33: ";", 0x34: "'", 0x35: "`", 0x36: ",",
              0x37: ".", 0x38: "/", 0x39: "Caps Lock", 0x46: "Print Screen", 0x47: "Scroll Lock",
              0x48: "Pause", 0x49: "Insert", 0x4A: "Home", 0x4B: "Page Up", 0x4C: "Delete", 0x4D: "End",
              0x4E: "Page Down", 0x4F: "Right", 0x50: "Left", 0x51: "Down", 0x52: "Up", 0x53: "Num Lock",
              0x54: "KP /", 0x55: "KP *", 0x56: "KP -", 0x57: "KP +", 0x58: "KP Enter",
              **{0x59 + i: f"KP {(i + 1) % 10}" for i in range(10)}, 0x63: "KP .", 0x65: "Menu"}

# Linux evdev keycode -> HID usage (GDK hardware keycode = evdev + 8)
EVDEV_TO_HID = {1: 0x29, 2: 0x1E, 3: 0x1F, 4: 0x20, 5: 0x21, 6: 0x22, 7: 0x23, 8: 0x24, 9: 0x25, 10: 0x26,
                11: 0x27, 12: 0x2D, 13: 0x2E, 14: 0x2A, 15: 0x2B, 16: 0x14, 17: 0x1A, 18: 0x08, 19: 0x15,
                20: 0x17, 21: 0x1C, 22: 0x18, 23: 0x0C, 24: 0x12, 25: 0x13, 26: 0x2F, 27: 0x30, 28: 0x28,
                30: 0x04, 31: 0x16, 32: 0x07, 33: 0x09, 34: 0x0A, 35: 0x0B, 36: 0x0D, 37: 0x0E, 38: 0x0F,
                39: 0x33, 40: 0x34, 41: 0x35, 43: 0x31, 44: 0x1D, 45: 0x1B, 46: 0x06, 47: 0x19, 48: 0x05,
                49: 0x11, 50: 0x10, 51: 0x36, 52: 0x37, 53: 0x38, 55: 0x55, 57: 0x2C, 58: 0x39,
                **{59 + i: 0x3A + i for i in range(10)}, 69: 0x53, 70: 0x47, 71: 0x5F, 72: 0x60, 73: 0x61,
                74: 0x56, 75: 0x5C, 76: 0x5D, 77: 0x5E, 78: 0x57, 79: 0x59, 80: 0x5A, 81: 0x5B, 82: 0x62,
                83: 0x63, 87: 0x44, 88: 0x45, 96: 0x58, 98: 0x54, 99: 0x46, 102: 0x4A, 103: 0x52,
                104: 0x4B, 105: 0x50, 106: 0x4F, 107: 0x4D, 108: 0x51, 109: 0x4E, 110: 0x49, 111: 0x4C,
                119: 0x48, 127: 0x65, **{183 + i: 0x68 + i for i in range(12)}}
# evdev modifier keycodes -> HID modifier bit
EVDEV_MODIFIERS = {29: 0x01, 42: 0x02, 56: 0x04, 125: 0x08, 97: 0x10, 54: 0x20, 100: 0x40, 126: 0x80}


def key_name(usage: int) -> str:
    return _KEY_NAMES.get(usage, f"Key 0x{usage:02X}")


def modifiers_label(mods: int) -> str:
    return "+".join(name for name, bit in MODIFIERS if mods & bit)


def _lookup(table, code, fallback):
    for name, c in table:
        if c == code:
            return name
    return fallback


@dataclass
class ButtonAction:
    kind: int
    code: int = 0
    modifiers: int = 0
    raw: bytes = b"\xff\xff\xff\xff"

    @classmethod
    def decode(cls, b: bytes) -> "ButtonAction":
        b = bytes(b)
        if b == b"\xff\xff\xff\xff":
            return cls(KIND_DEFAULT, raw=b)
        behavior = b[0] >> 4
        if behavior == 0x8:
            t = b[1]
            if t == 0x00:
                return cls(KIND_DISABLED, raw=b)
            if t == 0x01:
                return cls(KIND_MOUSE, (b[2] << 8) | b[3], raw=b)
            if t == 0x02:
                return cls(KIND_KEY, b[3], b[2], raw=b)
            if t == 0x03:
                return cls(KIND_CONSUMER, (b[2] << 8) | b[3], raw=b)
        if behavior == 0x9:
            return cls(KIND_FUNCTION, b[1], raw=b)
        return cls(KIND_RAW, raw=b)

    def encode(self) -> bytes:
        if self.kind == KIND_DEFAULT:
            return b"\xff\xff\xff\xff"
        if self.kind == KIND_DISABLED:
            return bytes([0x80, 0x00, 0xFF, 0xFF])
        if self.kind == KIND_MOUSE:
            return bytes([0x80, 0x01, self.code >> 8, self.code & 0xFF])
        if self.kind == KIND_KEY:
            return bytes([0x80, 0x02, self.modifiers & 0xFF, self.code & 0xFF])
        if self.kind == KIND_CONSUMER:
            return bytes([0x80, 0x03, self.code >> 8, self.code & 0xFF])
        if self.kind == KIND_FUNCTION:
            return bytes([0x90, self.code & 0xFF, 0xFF, 0x00])
        return bytes(self.raw)

    def describe(self, slot: int | None = None) -> str:
        if self.kind == KIND_DEFAULT:
            return "Default" + (f" ({_lookup(MOUSE_BUTTONS, FACTORY_MASKS[slot], '')})"
                                if slot is not None and slot < len(FACTORY_MASKS) else "")
        if self.kind == KIND_DISABLED:
            return "Disabled"
        if self.kind == KIND_MOUSE:
            return _lookup(MOUSE_BUTTONS, self.code, f"Mouse buttons 0x{self.code:04X}")
        if self.kind == KIND_KEY:
            mods = modifiers_label(self.modifiers)
            return (mods + "+" if mods else "") + key_name(self.code)
        if self.kind == KIND_CONSUMER:
            return _lookup(CONSUMER_KEYS, self.code, f"Media 0x{self.code:04X}")
        if self.kind == KIND_FUNCTION:
            return _lookup(FUNCTIONS, self.code, f"Function 0x{self.code:02X}")
        return "Macro / custom (" + self.raw.hex(" ") + ")"

    @classmethod
    def mouse(cls, mask: int) -> "ButtonAction":
        return cls.decode(bytes([0x80, 0x01, mask >> 8, mask & 0xFF]))

    @classmethod
    def factory(cls, slot: int) -> "ButtonAction":
        return cls.mouse(FACTORY_MASKS[slot])
