"""Feature-level API for the PRO X2 SUPERSTRIKE (and close HID++ 2.0 relatives).

Feature indexes are always resolved at runtime through Root (0x0000); nothing
here hardcodes an index. Protocol facts come from the community notes listed
in docs/PROTOCOL.md and were re-checked against a live unit where noted.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .transport import (HidppError, HidppTimeout, HidrawTransport, DeviceGone,
                        list_logitech_nodes, PID_WIRELESS, PID_WIRED, PID_RECEIVER,
                        SWID_GUI)

F_ROOT = 0x0000
F_FEATURE_SET = 0x0001
F_DEVICE_INFO = 0x0003
F_DEVICE_NAME = 0x0005
F_CONFIG_CHANGE = 0x0020
F_UNIFIED_BATTERY = 0x1004
F_ANALOG_BUTTONS = 0x1B0C
F_WIRELESS_STATUS = 0x1D4B
F_EXT_DPI = 0x2202
F_EXT_REPORT_RATE = 0x8061
F_MODE_STATUS = 0x8090
F_BUNNY_HOP = 0x80E0
F_ONBOARD_PROFILES = 0x8100
F_BUTTON_SPY = 0x8110

FEATURE_NAMES = {
    0x0000: "Root", 0x0001: "Feature set", 0x0003: "Device info", 0x0005: "Device name",
    0x0020: "Config change", 0x1004: "Unified battery", 0x1500: "Force pairing",
    0x1B0C: "Analog buttons (HITS)", 0x1D4B: "Wireless status", 0x1E00: "Hidden features",
    0x2202: "Extended DPI", 0x2250: "XY stats", 0x2251: "Wheel stats",
    0x8061: "Extended report rate", 0x8090: "Mode status (surface)",
    0x80E0: "Bunny hop (scroll filter)", 0x8100: "Onboard profiles", 0x8110: "Mouse button spy",
    0x1802: "Device reset", 0x1803: "GPIO access", 0x1805: "OOB state", 0x1806: "Config device props",
    0x1830: "Power modes", 0x1890: "RF test", 0x1801: "Manufacturing mode", 0x1817: "Lightspeed prepairing",
}

RATE_HZ = [125, 250, 500, 1000, 2000, 4000, 8000]  # index i == 125 << i
CHARGING = {0: "Discharging", 1: "Charging", 2: "Charging (slow)", 3: "Fully charged", 4: "Charge error"}
SURFACE_MODES = ["Auto", "On", "Off"]
ONBOARD_MODE, HOST_MODE = 0x01, 0x02


class FeatureMissing(Exception):
    pass


@dataclass
class Battery:
    percent: int
    charging_state: int
    external_power: bool

    @property
    def charging(self) -> bool:
        return self.charging_state in (1, 2)

    @property
    def label(self) -> str:
        return CHARGING.get(self.charging_state, f"State {self.charging_state}")


@dataclass
class Identity:
    name: str = "PRO X2 SUPERSTRIKE"
    unit_id: str = ""
    model_id: str = ""
    model_string: str = ""
    firmware: list[str] = field(default_factory=list)
    protocol: str = ""
    connection: str = ""
    node: str = ""


@dataclass
class OnboardInfo:
    memory_model: int
    profile_format: int
    macro_format: int
    profile_count: int
    oob_count: int
    button_count: int
    sector_count: int
    sector_size: int


@dataclass
class HitsButton:
    """One analog main button (logical values).

    actuation  1..10   (1 = shallowest / fastest)
    rt_level   1..5    rapid-trigger reset sensitivity
    rt_enabled bool    rapid trigger on/off (wire: bit0 of the RT byte)
    haptics    0..5    click-haptics strength, 0 = off
    """
    actuation: int = 2
    rt_level: int = 2
    rt_enabled: bool = False
    haptics: int = 3

    @property
    def rapid_trigger(self) -> int:
        return self.rt_level if self.rt_enabled else 0

    def to_wire(self) -> bytes:
        return bytes([self.actuation << 2, (self.rt_level << 2) | int(self.rt_enabled), self.haptics << 2])

    @classmethod
    def from_wire(cls, b: bytes) -> "HitsButton":
        return cls(actuation=min(10, max(1, b[0] >> 2)), rt_level=min(5, max(1, b[1] >> 2)),
                   rt_enabled=bool(b[1] & 0x01), haptics=min(5, b[2] >> 2))


def decode_dpi_list(stream: list[int]) -> list[tuple[int, int, int]]:
    """Decode the 0x2202 DPI list into (start, end, step) ranges."""
    ranges: list[tuple[int, int, int]] = []
    last = None
    i = 0
    while i < len(stream):
        v = stream[i]
        if v == 0:
            break
        if v >> 13 == 0b111:
            step = v & 0x1FFF
            end = stream[i + 1] if i + 1 < len(stream) else last
            if last is not None and end:
                ranges.append((last + step, end, step))
                last = end
            i += 2
            continue
        ranges.append((v, v, 1))
        last = v
        i += 1
    return ranges


def snap_dpi(value: int, ranges: list[tuple[int, int, int]]) -> int:
    """Clamp/snap a DPI to the nearest value the sensor accepts."""
    if not ranges:
        return max(100, min(44000, value))
    best = None
    for start, end, step in ranges:
        if value < start:
            cand = start
        elif value > end:
            cand = end
        else:
            cand = start + round((value - start) / step) * step
            cand = min(cand, end)
        if best is None or abs(cand - value) < abs(best - value):
            best = cand
    return best


class Mouse:
    def __init__(self, transport: HidrawTransport, connection: str):
        self.t = transport
        self.connection = connection
        self._index_cache: dict[int, int] = {}
        self.features: list[tuple[int, int, int, int]] = []  # (index, fid, flags, version)
        self.onboard: OnboardInfo | None = None
        self.protocol = ""
        self.node = None

    # ---------- discovery ----------
    @classmethod
    def open(cls, swid: int = SWID_GUI, node: str | None = None, dev_index: int | None = None,
             expected_pid: int | None = None, expected_unit: str | None = None) -> "Mouse":
        """Find the Superstrike (or open the given hidraw node). Raises PermissionError if
        nodes exist but are not accessible, FileNotFoundError if no candidate answers."""
        nodes = list_logitech_nodes()
        if node:
            ordered = [n for n in nodes if (n.path == node or expected_unit) and
                       (expected_pid is None or n.product == expected_pid)]
        else:
            ordered = ([n for n in nodes if n.product == PID_WIRED] +
                       [n for n in nodes if n.product == PID_WIRELESS] +
                       [n for n in nodes if n.product == PID_RECEIVER])
        perm_denied = False
        for node in ordered:
            indexes = [0xFF, 0x01] if node.product != PID_RECEIVER else [0x01, 0x02, 0x03, 0x04, 0x05, 0x06]
            if dev_index is not None:
                indexes = [dev_index]
            for idx in indexes:
                try:
                    t = HidrawTransport(node.path, idx, swid)
                except PermissionError:
                    perm_denied = True
                    break
                except DeviceGone:
                    break
                try:
                    proto = cls._ping(t)
                except (HidppTimeout, HidppError, DeviceGone):
                    t.close()
                    continue
                m = cls(t, "Wired USB" if node.product == PID_WIRED or node.name.endswith("Wired") else
                        "LIGHTSPEED wireless")
                m.protocol = proto
                m.node = node
                try:
                    if m.feature_index(F_ANALOG_BUTTONS, required=False) is None and node.product == PID_RECEIVER:
                        t.close()
                        continue
                except (HidppTimeout, HidppError):
                    pass
                if expected_unit is not None:
                    try:
                        if not expected_unit or m.identity().unit_id != expected_unit:
                            t.close()
                            continue
                    except Exception:
                        t.close()
                        raise
                return m
        if perm_denied:
            raise PermissionError("Logitech hidraw nodes are not accessible (udev rule missing?)")
        raise FileNotFoundError("PRO X2 SUPERSTRIKE not found (asleep, unpaired or unplugged)")

    @staticmethod
    def _ping(t: HidrawTransport) -> str:
        r = t.call(0x00, 1, bytes([0, 0, 0x5A]), timeout=0.4, retries=1)
        return f"{r[0]}.{r[1]}"

    def ping(self) -> bool:
        try:
            self._ping(self.t)
            return True
        except (HidppTimeout, HidppError):
            return False

    def close(self):
        self.t.close()

    def feature_index(self, fid: int, required: bool = True) -> int | None:
        if fid in self._index_cache:
            idx = self._index_cache[fid]
        else:
            r = self.t.call(0x00, 0, bytes([fid >> 8, fid & 0xFF]))
            idx = r[0] if r[0] != 0 or fid == 0 else None
            self._index_cache[fid] = idx
        if idx is None and required:
            raise FeatureMissing(f"feature 0x{fid:04x} not supported by this device")
        return idx

    def has(self, fid: int) -> bool:
        try:
            return self.feature_index(fid, required=False) is not None
        except (HidppTimeout, HidppError):
            return False

    def call(self, fid: int, fn: int, params: bytes = b"", **kw) -> bytes:
        return self.t.call(self.feature_index(fid), fn, params, **kw)

    def list_features(self) -> list[tuple[int, int, int, int]]:
        fs = self.feature_index(F_FEATURE_SET)
        count = self.t.call(fs, 0)[0]
        out = [(0, 0x0000, 0, 0)]
        for i in range(1, count + 1):
            r = self.t.call(fs, 1, bytes([i]))
            out.append((i, (r[0] << 8) | r[1], r[2], r[3]))
            self._index_cache[(r[0] << 8) | r[1]] = i
        self.features = out
        return out

    # ---------- identity / battery ----------
    def identity(self) -> Identity:
        ident = Identity(protocol=self.protocol, connection=self.connection,
                         node=self.node.path if self.node else "")
        try:
            idx = self.feature_index(F_DEVICE_NAME)
            length = self.t.call(idx, 0)[0]
            name = b""
            while len(name) < length:
                name += self.t.call(idx, 1, bytes([len(name)]))[: length - len(name)]
            ident.name = name.split(b"\x00")[0].decode("ascii", "replace").strip() or ident.name
        except (FeatureMissing, HidppError, HidppTimeout):
            pass
        try:
            idx = self.feature_index(F_DEVICE_INFO)
            r = self.t.call(idx, 0)
            entities = r[0]
            ident.unit_id = r[1:5].hex("-")
            ident.model_id = r[7:13].hex().upper()
            for e in range(entities):
                fw = self.t.call(idx, 1, bytes([e]))
                prefix = bytes(fw[1:4]).decode("ascii", "replace")
                kind = {0: "Main", 1: "Bootloader", 2: "Hardware", 5: "Sensor"}.get(fw[0], f"Type {fw[0]}")
                ident.firmware.append(f"{kind}: {prefix} {fw[4]:02x}.{fw[5]:02x}.B{(fw[6] << 8) | fw[7]:04x}")
            try:
                s = self.t.call(idx, 2)
                ident.model_string = bytes(s).split(b"\x00")[0].decode("ascii", "replace")
            except (HidppError, HidppTimeout):
                pass
        except (FeatureMissing, HidppError, HidppTimeout):
            pass
        return ident

    def battery(self) -> Battery:
        r = self.call(F_UNIFIED_BATTERY, 1)
        return Battery(percent=r[0], charging_state=r[2], external_power=bool(r[3]))

    # ---------- HITS analog buttons (0x1B0C) ----------
    def hits_caps(self) -> dict:
        r = self.call(F_ANALOG_BUTTONS, 0)
        return {"buttons": r[1], "actuation_max": r[2] >> 2, "rt_max": r[3] >> 2, "haptics_max": r[4] >> 2}

    def hits_get(self, button: int) -> HitsButton:
        r = self.call(F_ANALOG_BUTTONS, 2, bytes([button]))
        return HitsButton.from_wire(r[1:4])

    def hits_set(self, button: int, cfg: HitsButton):
        self.call(F_ANALOG_BUTTONS, 1, bytes([button]) + cfg.to_wire() + bytes(12))

    # ---------- DPI (0x2202) ----------
    def dpi_ranges(self) -> list[tuple[int, int, int]]:
        stream: list[int] = []
        for page in range(8):
            r = self.call(F_EXT_DPI, 2, bytes([0, 0, page]))
            data = r[3:]
            words = [(data[i] << 8) | data[i + 1] for i in range(0, len(data) - 1, 2)]
            stream.extend(words)
            if 0 in words:
                break
        return decode_dpi_list(stream)

    def dpi_get(self) -> tuple[int, int, int]:
        r = self.call(F_EXT_DPI, 5, bytes([0]))
        return (r[1] << 8) | r[2], (r[5] << 8) | r[6], r[9] if len(r) > 9 else 0

    def dpi_set_live(self, x: int, y: int, lod: int):
        self.call(F_EXT_DPI, 6, bytes([0, x >> 8, x & 0xFF, y >> 8, y & 0xFF, lod]))

    # ---------- report rate (0x8061) ----------
    def rate_supported(self) -> list[int]:
        r = self.call(F_EXT_REPORT_RATE, 1)
        mask = (r[0] << 8) | r[1]
        return [hz for i, hz in enumerate(RATE_HZ) if mask & (1 << i)]

    def rate_get(self) -> int:
        idx = self.call(F_EXT_REPORT_RATE, 2)[0]
        return RATE_HZ[idx] if idx < len(RATE_HZ) else 0

    def rate_set_live(self, hz: int):
        self.call(F_EXT_REPORT_RATE, 3, bytes([RATE_HZ.index(hz)]))

    # ---------- surface mode (0x8090) ----------
    def surface_get(self) -> int:
        r = self.call(F_MODE_STATUS, 0)
        return (r[1] >> 1) & 0x03

    def surface_set(self, mode: int):
        self.call(F_MODE_STATUS, 1, bytes([0x00, (mode & 3) << 1, 0x00, 0x06]))

    # ---------- bunny-hop scroll filter (0x80E0) ----------
    # fn1 = get, fn2 = SET. Never call fn2 as a getter: it clears the window.
    def bhop_get(self) -> int:
        """Window in milliseconds; 0 = off. 0xFF = never configured (off)."""
        raw = self.call(F_BUNNY_HOP, 1)[0]
        return 0 if raw == 0xFF else raw * 10

    def bhop_set(self, ms: int):
        if ms and not 100 <= ms <= 1000:
            raise ValueError("bhop window must be 0 (off) or 100..1000 ms")
        self.call(F_BUNNY_HOP, 2, bytes([ms // 10]))

    # ---------- onboard profiles (0x8100) ----------
    def onboard_info(self) -> OnboardInfo:
        r = self.call(F_ONBOARD_PROFILES, 0)
        self.onboard = OnboardInfo(r[0], r[1], r[2], r[3], r[4], r[5], r[6], (r[7] << 8) | r[8])
        return self.onboard

    def mode_get(self) -> int:
        return self.call(F_ONBOARD_PROFILES, 2)[0]

    def mode_set(self, mode: int):
        self.call(F_ONBOARD_PROFILES, 1, bytes([mode]))

    def current_profile(self) -> int:
        r = self.call(F_ONBOARD_PROFILES, 4)
        return (r[0] << 8) | r[1]

    def set_current_profile(self, sector: int):
        last = None
        for _ in range(3):
            try:
                self.call(F_ONBOARD_PROFILES, 3, bytes([sector >> 8, sector & 0xFF]))
                return
            except HidppTimeout as exc:  # activation times out spuriously
                last = exc
                time.sleep(0.15)
        raise last

    def dpi_stage_get(self) -> int:
        return self.call(F_ONBOARD_PROFILES, 11)[0]

    def dpi_stage_set(self, stage: int):
        self.call(F_ONBOARD_PROFILES, 12, bytes([stage]))

    def read_sector(self, sector: int, size: int | None = None) -> bytes:
        size = size or (self.onboard or self.onboard_info()).sector_size
        out = bytearray()
        off = 0
        while off + 16 <= size:
            out += self._read16(sector, off)
            off += 16
        if off < size:  # reads may not cross the sector end: align the last one
            tail = self._read16(sector, size - 16)
            out += tail[16 - (size - off):]
        return bytes(out[:size])

    def _read16(self, sector: int, off: int) -> bytes:
        r = self.call(F_ONBOARD_PROFILES, 5, bytes([sector >> 8, sector & 0xFF, off >> 8, off & 0xFF]),
                      retries=4, timeout=1.0)
        return r[:16]

    def write_sector(self, sector: int, data: bytes):
        """Raw sector write. Callers must compute the CRC and verify afterwards
        (see service.save). Writing flash wears it: never call this in a loop."""
        n = len(data)
        idx = self.feature_index(F_ONBOARD_PROFILES)

        def tolerant(fn, params):
            try:
                self.t.call(idx, fn, params, timeout=0.6, retries=0)
            except HidppTimeout:
                pass  # memory-write acks are unreliable; read-back is the truth

        tolerant(6, bytes([sector >> 8, sector & 0xFF, 0, 0, n >> 8, n & 0xFF]))
        for off in range(0, n, 16):
            tolerant(7, data[off:off + 16].ljust(16, b"\x00"))
        tolerant(8, b"")
