"""Discovery of Logitech HID++ devices for the landing page.

Every non-receiver Logitech hidraw node (receiver child nodes created by
hid-logitech-dj, or wired devices) is pinged; responsive ones are identified
by name, type, battery and lighting features. Asleep devices are still listed
(from their USB name) so the grid doesn't flicker.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .hidpp.mouse import Mouse, F_DEVICE_NAME, F_UNIFIED_BATTERY, Battery
from .hidpp.transport import (HidrawTransport, HidppError, HidppTimeout, DeviceGone, list_logitech_nodes,
                              PID_WIRELESS, PID_WIRED)

SWID_SCAN = 0x0D
F_RGB_EFFECTS = 0x8071
F_PER_KEY = 0x8081
F_BRIGHTNESS = 0x8040

DEVICE_TYPES = {0: "keyboard", 1: "remote", 2: "numpad", 3: "mouse", 4: "touchpad", 5: "trackball",
                6: "presenter", 7: "receiver", 8: "headset", 9: "webcam", 10: "steering wheel",
                11: "joystick", 12: "gamepad", 13: "dock", 14: "speaker", 15: "microphone"}
KEYBOARD_PIDS = {0x40B4: "G515 LS TKL"}


@dataclass
class FoundDevice:
    path: str
    pid: int
    usb_name: str
    dev_index: int | None = None
    name: str = ""
    kind: str = "other"          # mouse / keyboard / headset / ...
    model: str = "generic"       # superstrike / keyboard / generic
    awake: bool = False
    battery: Battery | None = None
    connection: str = ""
    features: set = field(default_factory=set)

    @property
    def key(self) -> str:
        return f"{self.path}:{self.pid:04x}"

    @property
    def title(self) -> str:
        n = self.name or self.usb_name.replace("Logitech ", "")
        return n


def _is_receiver(node) -> bool:
    return "Receiver" in node.name or node.product in (0xC547, 0xC54D, 0xC539, 0xC53A, 0xC541, 0xC545, 0xC52B,
                                                       0xC548, 0xC534)


def _classify(d: FoundDevice):
    if d.pid in (PID_WIRELESS, PID_WIRED) or "SUPERSTRIKE" in (d.name + d.usb_name).upper():
        d.model, d.kind = "superstrike", "mouse"
    elif d.kind == "keyboard" or d.pid in KEYBOARD_PIDS:
        d.kind = "keyboard"
        d.model = ("keyboard" if d.pid in KEYBOARD_PIDS and
                   {F_RGB_EFFECTS, F_PER_KEY, F_BRIGHTNESS} <= d.features else "generic")
    else:
        d.model = "generic"


def probe(node, previous: FoundDevice | None = None) -> FoundDevice:
    d = FoundDevice(node.path, node.product, node.name)
    wired = node.name.endswith("Wired") or node.product == PID_WIRED
    d.connection = "Wired USB" if wired else "LIGHTSPEED wireless"
    for idx in ([0xFF, 0x01] if wired else [0x01, 0xFF]):
        if previous and previous.dev_index not in (None, idx):
            continue
        try:
            t = HidrawTransport(node.path, idx, SWID_SCAN)
        except (DeviceGone, PermissionError):
            raise
        try:
            Mouse._ping(t)
        except (HidppTimeout, HidppError, DeviceGone):
            t.close()
            continue
        m = Mouse(t, d.connection)
        try:
            d.dev_index, d.awake = idx, True
            if previous and previous.awake and previous.name:
                d.name, d.kind, d.features = previous.name, previous.kind, previous.features
            else:
                for fid in (F_DEVICE_NAME, F_UNIFIED_BATTERY, F_RGB_EFFECTS, F_PER_KEY, F_BRIGHTNESS, 0x1B0C):
                    if m.feature_index(fid, required=False) is not None:
                        d.features.add(fid)
                if F_DEVICE_NAME in d.features:
                    d.name = m.identity().name
                    try:
                        d.kind = DEVICE_TYPES.get(m.call(F_DEVICE_NAME, 2)[0], "other")
                    except (HidppError, HidppTimeout):
                        pass
            if F_UNIFIED_BATTERY in d.features:
                try:
                    d.battery = m.battery()
                except (HidppError, HidppTimeout):
                    pass
        finally:
            t.close()
        break
    if not d.awake and previous:
        d.name, d.kind, d.features, d.dev_index = previous.name, previous.kind, previous.features, previous.dev_index
    _classify(d)
    return d


def scan(previous: dict[str, FoundDevice] | None = None) -> tuple[list[FoundDevice], bool]:
    """Returns (devices, permission_denied)."""
    previous = previous or {}
    out, denied = [], False
    for node in list_logitech_nodes():
        if _is_receiver(node):
            continue
        prev = previous.get(f"{node.path}:{node.product:04x}")
        try:
            out.append(probe(node, prev))
        except PermissionError:
            denied = True
        except (DeviceGone, OSError, HidppTimeout, HidppError):
            if prev:
                from dataclasses import replace
                out.append(replace(prev, awake=False))
            continue
    order = {"mouse": 0, "keyboard": 1, "headset": 2}
    out.sort(key=lambda d: (order.get(d.kind, 9), d.title))
    return out, denied
