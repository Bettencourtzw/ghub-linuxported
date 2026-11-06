"""DeviceService: owns the mouse connection on a worker thread.

All HID++ traffic happens on one thread, in order. The UI submits jobs and gets
results back through `dispatch` (GLib.idle_add in the GTK app), so it never
blocks on the radio. The service also implements the flash-safe save path:
fresh read -> backup -> write -> byte-exact read-back -> profile reload.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field

from .hidpp.mouse import (Mouse, Battery, Identity, OnboardInfo, HitsButton, FeatureMissing,
                          F_ANALOG_BUTTONS, F_BUNNY_HOP, F_MODE_STATUS, F_EXT_REPORT_RATE,
                          ONBOARD_MODE, HOST_MODE)
from .hidpp.transport import HidppError, HidppTimeout, DeviceGone, SWID_GUI
from .model.profile import Profile, DirectoryEntry, parse_directory, build_directory, crc_ok, with_crc
from . import storage
from .worker import DeviceWorker

ROM_FACTORY_PROFILE = 0x0101


class SaveError(Exception):
    pass


@dataclass
class Snapshot:
    """Everything the UI shows, read from the device."""
    identity: Identity | None = None
    battery: Battery | None = None
    onboard: OnboardInfo | None = None
    mode: int = ONBOARD_MODE
    active_sector: int = 0
    directory: list[DirectoryEntry] = field(default_factory=list)
    directory_raw: bytes = b""
    profiles: dict[int, Profile] = field(default_factory=dict)
    live_hits: list[HitsButton] = field(default_factory=list)
    hits_caps: dict = field(default_factory=dict)
    bhop_ms: int | None = None
    surface: int | None = None
    rate_supported: list[int] = field(default_factory=list)
    rate_live_hz: int = 0
    dpi_live: tuple[int, int, int] = (0, 0, 0)
    dpi_ranges: list = field(default_factory=list)
    dpi_stage: int = 0
    features: list = field(default_factory=list)

    @property
    def active_profile(self) -> Profile | None:
        return self.profiles.get(self.active_sector)

    @property
    def wired(self) -> bool:
        return bool(self.identity and self.identity.connection.startswith("Wired"))


class DeviceService(DeviceWorker):
    """Worker for the PRO X2 SUPERSTRIKE (or close relatives)."""
    noun = "mouse"

    def __init__(self, dispatch=None, swid: int = SWID_GUI, poll_battery_s: float = 30.0,
                 node: str | None = None, dev_index: int | None = None):
        super().__init__(dispatch, poll_battery_s)
        self.swid = swid
        self.node, self.dev_index = node, dev_index
        self.snapshot = Snapshot()

    @property
    def mouse(self) -> Mouse | None:
        return self.dev

    @mouse.setter
    def mouse(self, value):
        self.dev = value

    def open_device(self):
        return Mouse.open(self.swid, node=self.node, dev_index=self.dev_index)

    def poll(self):
        self.snapshot.battery = self.mouse.battery()
        self._emit("battery", self.snapshot.battery)

    # ---------- reading ----------
    def refresh(self):
        """Full re-read of the device into a new snapshot (device thread only)."""
        m = self.mouse
        s = Snapshot()
        s.identity = m.identity()
        s.features = m.list_features()
        s.battery = m.battery()
        if m.has(F_ANALOG_BUTTONS):
            s.hits_caps = m.hits_caps()
            s.live_hits = [m.hits_get(0), m.hits_get(1)]
        if m.has(F_BUNNY_HOP):
            s.bhop_ms = m.bhop_get()
        if m.has(F_MODE_STATUS):
            s.surface = m.surface_get()
        if m.has(F_EXT_REPORT_RATE):
            s.rate_supported = m.rate_supported()
            s.rate_live_hz = m.rate_get()
        s.dpi_ranges = m.dpi_ranges()
        s.dpi_live = m.dpi_get()
        s.onboard = m.onboard_info()
        s.mode = m.mode_get()
        s.active_sector = m.current_profile()
        try:
            s.dpi_stage = m.dpi_stage_get()
        except (HidppError, HidppTimeout):
            s.dpi_stage = 0
        s.directory_raw = self._read_checked(0x0000, allow_blank=True)
        s.directory = parse_directory(s.directory_raw) if crc_ok(s.directory_raw) else []
        sectors = [e.sector for e in s.directory]
        if s.active_sector not in sectors:
            sectors.insert(0, s.active_sector)
        for sec in sectors:
            try:
                raw = self._read_checked(sec, allow_blank=sec >= 0x0100)
                s.profiles[sec] = Profile.parse(sec, raw)
            except (ValueError, HidppError) as exc:
                print(f"profile sector 0x{sec:04x} unreadable: {exc}")
        self.snapshot = s
        self._emit("snapshot", s)
        self._emit("battery", s.battery)
        return s

    def _read_checked(self, sector: int, allow_blank=False) -> bytes:
        raw = b""
        for _ in range(3):
            raw = self.mouse.read_sector(sector)
            if crc_ok(raw) or allow_blank:
                return raw
        raise HidppError(0, 5, 0x05, b"CRC mismatch reading sector")

    # ---------- live (volatile) settings ----------
    def apply_hits(self, button: int, cfg: HitsButton):
        self.mouse.hits_set(button, cfg)
        self.snapshot.live_hits[button] = cfg

    def apply_bhop(self, ms: int):
        self.mouse.bhop_set(ms)
        self.snapshot.bhop_ms = ms

    def apply_surface(self, mode: int):
        self.mouse.surface_set(mode)
        self.snapshot.surface = mode

    def apply_rate(self, hz: int):
        # The firmware rejects live rate changes in onboard mode (INVALID_ARGUMENT);
        # there the rate comes from the profile and applies on save/reload.
        if self.snapshot.mode != HOST_MODE:
            return
        self.mouse.rate_set_live(hz)
        self.snapshot.rate_live_hz = hz

    def apply_stage(self, stage: int):
        self.mouse.dpi_stage_set(stage)
        self.snapshot.dpi_stage = stage

    def apply_dpi_live(self, x: int, y: int, lod: int):
        self.mouse.dpi_set_live(x, y, lod)

    def set_mode(self, mode: int):
        self.mouse.mode_set(mode)
        self.snapshot.mode = mode

    def reapply_live(self, live: dict):
        """Used by the tray helper after a reconnect (host mode / live-only settings)."""
        m = self.mouse
        if "surface" in live and m.has(F_MODE_STATUS):
            m.surface_set(live["surface"])
        if self.snapshot.mode == HOST_MODE:
            for i, h in enumerate(live.get("hits", [])):
                m.hits_set(i, HitsButton(**h))
            if "bhop_ms" in live:
                m.bhop_set(live["bhop_ms"])
            if "rate_hz" in live:
                m.rate_set_live(live["rate_hz"])
            if "dpi" in live:
                m.dpi_set_live(*live["dpi"])

    # ---------- persistent (flash) writes ----------
    def _write_verified(self, sector: int, data: bytes, reason: str) -> str:
        """Backup current contents, write, verify byte-for-byte. Returns backup path."""
        m = self.mouse
        size = m.onboard.sector_size
        if len(data) != size:
            raise SaveError(f"sector image is {len(data)} bytes, device expects {size}")
        if not crc_ok(data):
            raise SaveError("refusing to write a sector with a bad CRC")
        try:
            current = m.read_sector(sector)
        except HidppError as exc:
            raise SaveError("Cannot read the current settings; nothing was written") from exc
        if len(current) != size:
            raise SaveError("Cannot back up an incomplete sector; nothing was written")
        if current == data:
            return ""
        unit = self.snapshot.identity.unit_id if self.snapshot.identity else ""
        backup = str(storage.backup_sector(unit, sector, current, reason)) if current else ""
        m.write_sector(sector, data)
        time.sleep(0.05)
        for attempt in range(3):
            got = m.read_sector(sector)
            if got == data:
                return backup
            time.sleep(0.15)
        raise SaveError(f"write to sector 0x{sector:04x} could not be verified. "
                        f"The previous contents are saved in {backup or 'no backup (sector was unreadable)'}.")

    def _reload(self, sector: int):
        """Make the firmware re-load a profile we just wrote."""
        m = self.mouse
        others = [e.sector for e in self.snapshot.directory if e.enabled and e.sector != sector]
        if self.snapshot.mode != ONBOARD_MODE:
            m.mode_set(ONBOARD_MODE)
        if others:
            m.set_current_profile(others[0])
            time.sleep(0.15)
        else:
            m.mode_set(HOST_MODE)
            time.sleep(0.1)
            m.mode_set(ONBOARD_MODE)
            time.sleep(0.1)
        m.set_current_profile(sector)
        if self.snapshot.mode == HOST_MODE:
            m.mode_set(HOST_MODE)

    def _ensure_ram_profile(self, sector: int) -> int:
        """A pristine mouse runs its ROM factory profile. Clone it to RAM slot 1 and
        create a directory so it becomes editable. Returns the writable sector."""
        if sector < 0x0100:
            return sector
        target = sector & 0xFF if 1 <= (sector & 0xFF) <= self.mouse.onboard.profile_count else 1
        raw = self.mouse.read_sector(sector)
        self._write_verified(target, with_crc(raw), "clone factory profile to RAM")
        size = self.mouse.onboard.sector_size
        entries = [DirectoryEntry(target, True)] + [
            DirectoryEntry(n, False) for n in range(1, self.mouse.onboard.profile_count + 1) if n != target]
        self._write_verified(0x0000, build_directory(entries, size), "create profile directory")
        return target

    def save_profile(self, edited: Profile, activate: bool = True) -> Profile:
        """Write an edited profile to flash (device thread)."""
        m = self.mouse
        sector = self._ensure_ram_profile(edited.sector)
        fresh = self._read_checked(sector)
        work = copy.deepcopy(edited)
        work.sector = sector
        work.raw = fresh
        data = work.serialize()
        self._write_verified(sector, data, f"save profile '{work.display_name}'")
        if activate and (sector == self.snapshot.active_sector or edited.sector >= 0x0100):
            self._reload(sector)
        self.refresh()
        return self.snapshot.profiles.get(sector, work)

    def write_raw_profile(self, sector: int, raw: bytes, reason: str):
        """Restore a backup / factory image into a RAM profile sector."""
        if sector >= 0x0100:
            raise SaveError("ROM sectors are read-only")
        data = with_crc(raw)
        Profile.parse(sector, data).validate()
        self._write_verified(sector, data, reason)
        if sector == self.snapshot.active_sector:
            self._reload(sector)
        self.refresh()

    def restore_backup(self, sector: int, raw: bytes):
        if len(raw) != self.mouse.onboard.sector_size:
            raise SaveError("backup does not match this mouse's sector size")
        if sector == 0x0000:
            data = with_crc(raw)
            parse_directory(data)
            self._write_verified(0x0000, data, "restore directory backup")
            self.refresh()
        else:
            self.write_raw_profile(sector, raw, "restore backup")

    def rename_profile(self, sector: int, name: str):
        prof = copy.deepcopy(self.snapshot.profiles[sector])
        prof.name = name
        self.save_profile(prof, activate=False)

    def factory_reset_profile(self, sector: int):
        rom = self.mouse.read_sector(ROM_FACTORY_PROFILE)
        self.write_raw_profile(sector, rom, "factory reset")

    def set_profile_enabled(self, sector: int, enabled: bool):
        entries = [DirectoryEntry(e.sector, enabled if e.sector == sector else e.enabled)
                   for e in self.snapshot.directory]
        if not any(e.enabled for e in entries):
            raise SaveError("at least one profile must stay enabled")
        data = build_directory(entries, self.mouse.onboard.sector_size, self.snapshot.directory_raw)
        self._write_verified(0x0000, data, "change enabled profiles")
        self.refresh()

    def activate_profile(self, sector: int):
        if self.snapshot.mode != ONBOARD_MODE:
            self.mouse.mode_set(ONBOARD_MODE)
        self.mouse.set_current_profile(sector)
        if self.snapshot.mode == HOST_MODE:
            self.mouse.mode_set(HOST_MODE)
        self.refresh()

    def copy_profile(self, src: int, dst: int):
        raw = self.snapshot.profiles[src].raw
        self.write_raw_profile(dst, raw, f"copy profile 0x{src:04x} to 0x{dst:04x}")

    # ---------- raw console ----------
    def raw_call(self, feature_index: int, function: int, params: bytes) -> bytes:
        return self.mouse.t.call(feature_index, function, params, retries=0)
