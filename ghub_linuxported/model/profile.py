"""Onboard profile sector (format 8, 255-byte sectors) for the PRO X2 SUPERSTRIKE.

The model keeps the raw sector and only patches the fields it understands, so
unknown bytes (lighting placeholders, counters, reserved areas) round-trip
untouched. Layout verified against a factory dump (tests/fixtures) — see
docs/PROTOCOL.md for the field map and sources.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..hidpp.mouse import HitsButton, RATE_HZ
from .buttons import ButtonAction

OFF_RATE_WIRELESS = 0x00
OFF_RATE_WIRED = 0x01
OFF_DEFAULT_STAGE = 0x02
OFF_SHIFT_STAGE = 0x03
OFF_STAGES = 0x04          # 5 x [Xlo Xhi Ylo Yhi LOD]
STAGE_COUNT = 5
OFF_POWER_MODE = 0x21
OFF_ANGLE_SNAP = 0x22
OFF_BHOP = 0x25            # window in 10 ms units, 0 = off
OFF_HITS = 0x26            # 2 x [act<<2][rt<<2|en][hap<<2]
OFF_POWER_SAVE = 0x2C      # u16 LE seconds
OFF_POWER_OFF = 0x2E       # u16 LE seconds
OFF_BUTTONS = 0x30         # 4 bytes per slot
OFF_SHIFT_BUTTONS = 0x70
OFF_NAME = 0xA0            # UTF-16LE, 48 bytes
NAME_BYTES = 48
BUTTON_COUNT = 5           # physical: L, R, Middle, Back, Forward

LOD_NAMES = {1: "Low", 2: "Medium", 3: "High"}


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, no xorout."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def crc_ok(sector: bytes) -> bool:
    return crc16_ccitt(sector[:-2]) == ((sector[-2] << 8) | sector[-1])


def with_crc(sector: bytes) -> bytes:
    crc = crc16_ccitt(sector[:-2])
    return bytes(sector[:-2]) + bytes([crc >> 8, crc & 0xFF])


@dataclass
class DpiStage:
    x: int
    y: int
    lod: int  # 0 = stage disabled, 1 low, 2 medium, 3 high

    @property
    def enabled(self) -> bool:
        return self.lod != 0


@dataclass
class Profile:
    sector: int
    raw: bytes
    rate_wireless_hz: int = 1000
    rate_wired_hz: int = 1000
    default_stage: int = 0
    shift_stage: int = 0
    stages: list[DpiStage] = field(default_factory=list)
    angle_snapping: bool = False
    bhop_ms: int = 0
    hits: list[HitsButton] = field(default_factory=list)
    power_save_s: int = 60
    power_off_s: int = 300
    buttons: list[ButtonAction] = field(default_factory=list)
    shift_buttons: list[ButtonAction] = field(default_factory=list)
    name: str = ""

    @classmethod
    def parse(cls, sector: int, raw: bytes) -> "Profile":
        if len(raw) < 0xFF:
            raise ValueError(f"profile sector too short ({len(raw)} bytes)")

        def rate(b):
            return RATE_HZ[b] if b < len(RATE_HZ) else 1000

        stages = []
        for n in range(STAGE_COUNT):
            o = OFF_STAGES + 5 * n
            stages.append(DpiStage(raw[o] | raw[o + 1] << 8, raw[o + 2] | raw[o + 3] << 8, raw[o + 4]))
        name_bytes = raw[OFF_NAME:OFF_NAME + NAME_BYTES]
        name = name_bytes.decode("utf-16-le", "replace").split("\x00")[0]
        if name.strip("￿") == "":
            name = ""
        return cls(
            sector=sector, raw=bytes(raw),
            rate_wireless_hz=rate(raw[OFF_RATE_WIRELESS]), rate_wired_hz=rate(raw[OFF_RATE_WIRED]),
            default_stage=raw[OFF_DEFAULT_STAGE] if raw[OFF_DEFAULT_STAGE] < STAGE_COUNT else 0,
            shift_stage=raw[OFF_SHIFT_STAGE] if raw[OFF_SHIFT_STAGE] < STAGE_COUNT else 0,
            stages=stages,
            angle_snapping=raw[OFF_ANGLE_SNAP] == 0x01,
            bhop_ms=raw[OFF_BHOP] * 10 if raw[OFF_BHOP] != 0xFF else 0,
            hits=[HitsButton.from_wire(raw[OFF_HITS + 3 * i:OFF_HITS + 3 * i + 3]) for i in range(2)],
            power_save_s=raw[OFF_POWER_SAVE] | raw[OFF_POWER_SAVE + 1] << 8,
            power_off_s=raw[OFF_POWER_OFF] | raw[OFF_POWER_OFF + 1] << 8,
            buttons=[ButtonAction.decode(raw[OFF_BUTTONS + 4 * i:OFF_BUTTONS + 4 * i + 4]) for i in range(BUTTON_COUNT)],
            shift_buttons=[ButtonAction.decode(raw[OFF_SHIFT_BUTTONS + 4 * i:OFF_SHIFT_BUTTONS + 4 * i + 4])
                           for i in range(BUTTON_COUNT)],
            name=name,
        )

    @property
    def display_name(self) -> str:
        if not self.name or self.name == "PROFILE_NAME_DEFAULT":
            return f"Profile {self.sector & 0xFF}"
        return self.name

    def validate(self):
        if not any(s.enabled for s in self.stages):
            raise ValueError("at least one DPI stage must be enabled")
        if not self.stages[self.default_stage].enabled:
            raise ValueError("the default DPI stage must be enabled")
        for s in self.stages:
            if not (100 <= s.x <= 44000 and 100 <= s.y <= 44000):
                raise ValueError(f"DPI {s.x}x{s.y} out of range 100..44000")
        if self.bhop_ms and not 100 <= self.bhop_ms <= 1000:
            raise ValueError("bhop window must be off or 100..1000 ms")
        if len(self.name.encode("utf-16-le")) > NAME_BYTES - 2:
            raise ValueError("profile name too long (max 23 characters)")

    def serialize(self) -> bytes:
        """Patch the known fields into a copy of the raw sector and fix the CRC."""
        self.validate()
        b = bytearray(self.raw)
        b[OFF_RATE_WIRELESS] = RATE_HZ.index(self.rate_wireless_hz)
        b[OFF_RATE_WIRED] = RATE_HZ.index(self.rate_wired_hz)
        b[OFF_DEFAULT_STAGE] = self.default_stage
        b[OFF_SHIFT_STAGE] = self.shift_stage
        for n, s in enumerate(self.stages):
            o = OFF_STAGES + 5 * n
            b[o:o + 5] = bytes([s.x & 0xFF, s.x >> 8, s.y & 0xFF, s.y >> 8, s.lod])
        # Only touch angle snapping if it was a recognised boolean before.
        if b[OFF_ANGLE_SNAP] in (0x00, 0x01):
            b[OFF_ANGLE_SNAP] = 0x01 if self.angle_snapping else 0x00
        b[OFF_BHOP] = self.bhop_ms // 10
        for i, h in enumerate(self.hits):
            b[OFF_HITS + 3 * i:OFF_HITS + 3 * i + 3] = h.to_wire()
        b[OFF_POWER_SAVE:OFF_POWER_SAVE + 2] = self.power_save_s.to_bytes(2, "little")
        b[OFF_POWER_OFF:OFF_POWER_OFF + 2] = self.power_off_s.to_bytes(2, "little")
        for i, a in enumerate(self.buttons):
            b[OFF_BUTTONS + 4 * i:OFF_BUTTONS + 4 * i + 4] = a.encode()
        for i, a in enumerate(self.shift_buttons):
            b[OFF_SHIFT_BUTTONS + 4 * i:OFF_SHIFT_BUTTONS + 4 * i + 4] = a.encode()
        if self.name:
            name = self.name.encode("utf-16-le")
            b[OFF_NAME:OFF_NAME + NAME_BYTES] = name + bytes(NAME_BYTES - len(name))
        return with_crc(bytes(b))

    def to_json(self) -> dict:
        return {
            "name": self.name, "rate_wireless_hz": self.rate_wireless_hz, "rate_wired_hz": self.rate_wired_hz,
            "default_stage": self.default_stage, "shift_stage": self.shift_stage,
            "stages": [{"x": s.x, "y": s.y, "lod": s.lod} for s in self.stages],
            "angle_snapping": self.angle_snapping, "bhop_ms": self.bhop_ms,
            "hits": [{"actuation": h.actuation, "rt_level": h.rt_level, "rt_enabled": h.rt_enabled,
                      "haptics": h.haptics} for h in self.hits],
            "power_save_s": self.power_save_s, "power_off_s": self.power_off_s,
            "buttons": [a.encode().hex() for a in self.buttons],
            "shift_buttons": [a.encode().hex() for a in self.shift_buttons],
            "raw": self.raw.hex(),
        }

    def apply_json(self, d: dict):
        """Load settings from an exported profile (keeps this sector's raw base)."""
        self.name = d.get("name", self.name)
        self.rate_wireless_hz = d.get("rate_wireless_hz", self.rate_wireless_hz)
        self.rate_wired_hz = d.get("rate_wired_hz", self.rate_wired_hz)
        self.default_stage = d.get("default_stage", self.default_stage)
        self.shift_stage = d.get("shift_stage", self.shift_stage)
        if "stages" in d:
            self.stages = [DpiStage(s["x"], s["y"], s["lod"]) for s in d["stages"]][:STAGE_COUNT]
        self.angle_snapping = d.get("angle_snapping", self.angle_snapping)
        self.bhop_ms = d.get("bhop_ms", self.bhop_ms)
        if "hits" in d:
            self.hits = [HitsButton(**h) for h in d["hits"]][:2]
        self.power_save_s = d.get("power_save_s", self.power_save_s)
        self.power_off_s = d.get("power_off_s", self.power_off_s)
        if "buttons" in d:
            self.buttons = [ButtonAction.decode(bytes.fromhex(h)) for h in d["buttons"]][:BUTTON_COUNT]
        if "shift_buttons" in d:
            self.shift_buttons = [ButtonAction.decode(bytes.fromhex(h)) for h in d["shift_buttons"]][:BUTTON_COUNT]
        self.validate()


@dataclass
class DirectoryEntry:
    sector: int
    enabled: bool


def parse_directory(raw: bytes) -> list[DirectoryEntry]:
    """Sector 0x0000: 4-byte entries [secHi][secLo][enabled][pad], terminated 0xFFFF."""
    out = []
    for o in range(0, len(raw) - 4, 4):
        sec = (raw[o] << 8) | raw[o + 1]
        if sec == 0xFFFF:
            break
        out.append(DirectoryEntry(sec, raw[o + 2] == 0x01))
    return out


def build_directory(entries: list[DirectoryEntry], size: int, base: bytes | None = None) -> bytes:
    b = bytearray(base if base and len(base) == size else b"\xff" * size)
    o = 0
    for e in entries:
        b[o:o + 4] = bytes([e.sector >> 8, e.sector & 0xFF, 1 if e.enabled else 0, b[o + 3] if base else 0xFF])
        o += 4
    b[o:o + 2] = b"\xff\xff"
    return with_crc(bytes(b))
