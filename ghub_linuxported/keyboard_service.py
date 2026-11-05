"""KeyboardService: owns one keyboard's lighting for as long as the app runs.

Lighting under software control is volatile, so the service re-applies the saved
state whenever the keyboard (re)connects or silently drops the claim (checked
every few seconds), and gives control back to the keyboard on stop.
"""
from __future__ import annotations

import copy
import time

from .worker import DeviceWorker
from .hidpp.mouse import Mouse, F_UNIFIED_BATTERY
from .hidpp.lighting import Lighting, zone_for_usage
from .hidpp.transport import HidppError
from . import storage

SWID_KBD = 0x0E
CHECK_CLAIM_S = 8
BATTERY_S = 60

DEFAULT_STATE = {
    "mode": "onboard",          # onboard | off | static | breathe | cycle | wave | ripple | perkey
    "color": [0, 168, 232],
    "period": 3000,             # ms (ripple uses its own 2..200 scale)
    "intensity": 100,
    "direction": 1,
    "keys": {},                 # {"<hid usage>": [r, g, b]} for per-key
    "base": [10, 12, 18],
    "brightness": None,
}


def config_key(found) -> str:
    return f"{found.pid:04x}"


def load_state(key: str) -> dict:
    cfg = storage.load_config()
    st = copy.deepcopy(DEFAULT_STATE)
    st.update(cfg.get("keyboards", {}).get(key, {}))
    return st


def save_state(key: str, state: dict):
    cfg = storage.load_config()
    cfg.setdefault("keyboards", {})[key] = state
    storage.save_config(cfg)


class KeyboardService(DeviceWorker):
    noun = "keyboard"

    def __init__(self, dispatch, found):
        super().__init__(dispatch, poll_s=CHECK_CLAIM_S)
        self.found = found
        self.key = config_key(found)
        self.state = load_state(self.key)
        self.lighting: Lighting | None = None
        self.identity = None
        self.battery = None
        self._next_battery = 0.0

    # ---------- worker hooks
    def open_device(self):
        return Mouse.open(SWID_KBD, node=self.found.path, dev_index=self.found.dev_index)

    def refresh(self):
        d = self.dev
        self.identity = d.identity()
        self.battery = d.battery() if d.has(F_UNIFIED_BATTERY) else None
        self.lighting = Lighting(d)
        self.lighting.probe()
        if self.state["brightness"] is None and self.lighting.info.brightness is not None:
            self.state["brightness"] = self.lighting.info.brightness
        self._apply_device(self.state)
        self._emit("info", self)
        if self.battery:
            self._emit("battery", self.battery)

    def poll(self):
        if time.monotonic() >= self._next_battery and self.dev.has(F_UNIFIED_BATTERY):
            self._next_battery = time.monotonic() + BATTERY_S
            self.battery = self.dev.battery()
            self._emit("battery", self.battery)
        if self.state["mode"] != "onboard" and self.lighting:
            try:
                lost = self.lighting.sw_control_mode() == 0
            except HidppError:
                lost = False
            if lost:  # keyboard power-cycled or reconnected: our claim is gone
                self.lighting.claimed = self.lighting.primed = False
                self._apply_device(self.state)

    def on_stop(self):
        if self.lighting and self.lighting.claimed:
            self.lighting.release()

    # ---------- applying
    def _apply_device(self, st: dict):
        L = self.lighting
        mode = st["mode"]
        if mode == "onboard":
            if L.claimed:
                L.release()
            return
        if not L.claimed:
            L.claim()
        if mode != "perkey":
            L.primed = False
        rgb = tuple(st["color"])
        if mode == "off":
            L.off()
        elif mode == "static":
            L.static(rgb)
        elif mode == "breathe":
            L.breathe(rgb, st["period"], st["intensity"])
        elif mode == "cycle":
            L.cycle(st["period"], st["intensity"])
        elif mode == "wave":
            L.wave(st["period"], st["direction"], st["intensity"])
        elif mode == "ripple":
            L.ripple(rgb, max(2, min(200, st["period"] // 50)))
        elif mode == "perkey":
            zones = {}
            for usage, c in st["keys"].items():
                z = zone_for_usage(int(usage))
                if z is not None:
                    zones[z] = tuple(c)
            L.per_key(zones, tuple(st["base"]))

    def apply(self, state: dict, persist=True):
        """Device thread: apply and remember a lighting state."""
        self.state = copy.deepcopy(state)
        if persist:
            save_state(self.key, self.state)
        self._apply_device(self.state)

    def set_brightness(self, value: int, persist=True):
        self.lighting.set_brightness(value)
        self.state["brightness"] = value
        if persist:
            save_state(self.key, self.state)
