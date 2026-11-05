"""Keyboard lighting over HID++: RGB effects (0x8071), per-key (0x8081), brightness (0x8040).

Verified read-only on a G515 LS TKL (fw MPK): one Primary cluster with slots
0 Off, 1 Static, 2 Breathe(0x0A), 3 Cycle(0x15), 4 Wave(0x16), 5 Ripple(0x17);
95 per-key zones; brightness 0..100 in 5 steps. Write layouts follow Solaar and
OpenRGB (both built from G HUB captures); see docs/PROTOCOL.md.

Software-controlled lighting is volatile: it is lost on reconnect / power cycle,
so the app re-applies it (the tray keeps it alive) and releases control on quit.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .mouse import Mouse
from .transport import HidppError

F_RGB_EFFECTS = 0x8071
F_PER_KEY = 0x8081
F_BRIGHTNESS = 0x8040
F_PROFILE_MGMT = 0x8101
F_ONBOARD = 0x8100

EFFECT_NAMES = {0x0000: "Off", 0x0001: "Static", 0x0002: "Pulse", 0x0003: "Color cycle", 0x0004: "Wave",
                0x000A: "Breathing", 0x000B: "Ripple", 0x0015: "Color cycle", 0x0016: "Color wave",
                0x0017: "Ripple"}
# Wave directions (G515 blocks 4 "in" and 5 "out")
DIRECTIONS = [("Left → right", 1), ("Right → left", 6), ("Top → bottom", 2), ("Bottom → top", 7),
              ("Center out", 3), ("Edges in", 8)]


def zone_for_usage(usage: int) -> int | None:
    """Logitech per-key zone id from a USB HID keyboard usage."""
    if 0x04 <= usage <= 0x66:
        return usage - 3
    if 0xE0 <= usage <= 0xE7:
        return usage - 0x88
    return None


@dataclass
class EffectSlot:
    cluster: int
    slot: int
    effect_id: int
    caps: int
    default_period: int

    @property
    def name(self) -> str:
        return EFFECT_NAMES.get(self.effect_id, f"Effect 0x{self.effect_id:04X}")


@dataclass
class LightingInfo:
    clusters: int = 0
    effects: list[EffectSlot] = field(default_factory=list)
    zones: list[int] = field(default_factory=list)
    brightness_max: int = 100
    brightness_steps: int = 5
    brightness: int | None = None

    def slot_for(self, effect_ids) -> EffectSlot | None:
        for e in self.effects:
            if e.cluster == 0 and e.effect_id in effect_ids:
                return e
        return None


class Lighting:
    def __init__(self, dev: Mouse):
        self.dev = dev
        self.info = LightingInfo()
        self.claimed = False
        self.primed = False

    # ---------- discovery (read-only)
    def probe(self) -> LightingInfo:
        d, info = self.dev, LightingInfo()
        if d.has(F_RGB_EFFECTS):
            info.clusters = d.call(F_RGB_EFFECTS, 0, bytes([0xFF, 0xFF, 0x00]))[2]
            for c in range(info.clusters):
                n = d.call(F_RGB_EFFECTS, 0, bytes([c, 0xFF, 0x00]))[4]
                for s in range(n):
                    e = d.call(F_RGB_EFFECTS, 0, bytes([c, s, 0x00]))
                    info.effects.append(EffectSlot(c, s, (e[2] << 8) | e[3], (e[4] << 8) | e[5], (e[6] << 8) | e[7]))
        if d.has(F_PER_KEY):
            for page in range(3):
                b = d.call(F_PER_KEY, 0, bytes([0x00, page, 0x00]))
                for bi, byte in enumerate(b[2:16]):
                    for bit in range(8):
                        z = page * 112 + bi * 8 + bit
                        if byte >> bit & 1 and 0 < z < 255:
                            info.zones.append(z)
        if d.has(F_BRIGHTNESS):
            r = d.call(F_BRIGHTNESS, 0)
            info.brightness_max = ((r[0] << 8) | r[1]) or 100
            info.brightness_steps = (r[2] & 0x0F) or 5
            info.brightness = int.from_bytes(d.call(F_BRIGHTNESS, 1)[:2], "big")
        self.info = info
        return info

    def sw_control_mode(self) -> int:
        return self.dev.call(F_RGB_EFFECTS, 5, bytes([0x00]))[1]

    # ---------- control
    def claim(self):
        if self.dev.has(F_PROFILE_MGMT):
            self.dev.call(F_PROFILE_MGMT, 6, bytes([0x05]))
        elif self.dev.has(F_ONBOARD):
            self.dev.call(F_ONBOARD, 1, bytes([0x02]))
        self.dev.call(F_RGB_EFFECTS, 5, bytes([0x01, 0x03, 0x04]))
        self.claimed, self.primed = True, False

    def release(self):
        try:
            self.dev.call(F_RGB_EFFECTS, 5, bytes([0x01, 0x00, 0x00]))
        finally:
            if self.dev.has(F_PROFILE_MGMT):
                self.dev.call(F_PROFILE_MGMT, 6, bytes([0x03]))
            elif self.dev.has(F_ONBOARD):
                self.dev.call(F_ONBOARD, 1, bytes([0x01]))
            self.claimed = self.primed = False

    def _effect(self, slot: EffectSlot, params: bytes):
        payload = bytes([slot.cluster, slot.slot]) + params.ljust(10, b"\x00")[:10] + b"\x01"
        self._busy_retry(lambda: self.dev.call(F_RGB_EFFECTS, 1, payload))

    @staticmethod
    def _busy_retry(fn, tries=12):
        for i in range(tries):
            try:
                return fn()
            except HidppError as exc:
                if exc.code != 0x08 or i == tries - 1:
                    raise
                time.sleep(0.008)

    # ---------- effects
    def off(self):
        slot = self.info.slot_for((0x0000,))
        if slot:
            self._effect(slot, b"")
        else:
            self.static((0, 0, 0))

    def static(self, rgb):
        self._effect(self.info.slot_for((0x0001,)), bytes([*rgb, 0x02 if any(rgb) else 0x00]))

    def breathe(self, rgb, period_ms: int, intensity: int = 100):
        p = max(500, min(20000, period_ms))
        self._effect(self.info.slot_for((0x000A, 0x0002)), bytes([*rgb, p >> 8, p & 0xFF, 0, intensity]))

    def cycle(self, period_ms: int, intensity: int = 100):
        p = max(500, min(30000, period_ms))
        self._effect(self.info.slot_for((0x0015, 0x0003)), bytes([0, 0xFF, 0, 0, 0, 0, p >> 8, p & 0xFF, intensity]))

    def wave(self, period_ms: int, direction: int = 1, intensity: int = 100):
        p = max(100, min(30000, period_ms))
        self._effect(self.info.slot_for((0x0016,)),
                     bytes([0, 0xFF, 0, 0, 0, 0, p >> 8, p & 0xFF, intensity, direction]))

    def ripple(self, rgb, period: int = 50):
        p = max(2, min(200, period))
        self._effect(self.info.slot_for((0x0017, 0x000B)), bytes([*rgb, 0xFF, 0, 0, p >> 8, p & 0xFF]))

    # ---------- per-key
    def per_key(self, colors: dict[int, tuple[int, int, int]], base=(0, 0, 0), repeat_first=True):
        """colors: {zone: (r,g,b)}. Zones not given get `base`. Requires Static mode (primed)."""
        if not self.primed:
            self.static((0, 0, 0))  # static pass-through primer: per-key buffer becomes visible
            time.sleep(0.02)
        frame = {z: base for z in self.info.zones}
        frame.update({z: tuple(c) for z, c in colors.items() if z in frame})
        buckets: dict[tuple, list[int]] = {}
        for z, c in frame.items():
            buckets.setdefault(tuple(c), []).append(z)
        times = 2 if (repeat_first and not self.primed) else 1
        for _ in range(times):
            singles = []
            for rgb, zones in buckets.items():
                if len(zones) > 3:
                    for i in range(0, len(zones), 13):
                        chunk = zones[i:i + 13]
                        self._busy_retry(lambda c=chunk, rgb=rgb: self.dev.call(F_PER_KEY, 6, bytes([*rgb, *c])))
                else:
                    singles += [(z, rgb) for z in zones]
            for i in range(0, len(singles), 4):
                payload = b"".join(bytes([z, *rgb]) for z, rgb in singles[i:i + 4])
                self._busy_retry(lambda p=payload: self.dev.call(F_PER_KEY, 1, p))
            self._busy_retry(lambda: self.dev.call(F_PER_KEY, 7, bytes(16)), tries=60)
        self.primed = True

    # ---------- brightness
    def set_brightness(self, value: int):
        v = max(0, min(self.info.brightness_max, value))
        self.dev.call(F_BRIGHTNESS, 2, bytes([v >> 8, v & 0xFF]))
        self.info.brightness = v
