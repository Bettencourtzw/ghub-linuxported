"""HID++ 2.0 over Linux /dev/hidraw.

Frames:
  short  0x10: [0x10][dev][feat][fn<<4|swid][3 params]          7 bytes
  long   0x11: [0x11][dev][feat][fn<<4|swid][16 params]         20 bytes
  error      : [rid][dev][0xFF][feat][fn<<4|swid][code] (HID++ 2.0)
               [rid][dev][0x8F][feat][fn<<4|swid][code] (HID++ 1.0 / receiver)

Each process uses its own software id (swid) so replies never cross between the
GUI, the tray helper and the CLI, which may all have the same node open.
"""
from __future__ import annotations

import errno
import os
import select
import threading
import time
from dataclasses import dataclass

REPORT_SHORT = 0x10
REPORT_LONG = 0x11
REPORT_VERY_LONG = 0x12
SHORT_LEN = 7
LONG_LEN = 20
HIDPP_REPORT_IDS = (REPORT_SHORT, REPORT_LONG, REPORT_VERY_LONG)

VENDOR_LOGITECH = 0x046D
# Superstrike product ids: wireless child node (via LIGHTSPEED receiver), wired.
PID_WIRELESS = 0x40BD
PID_WIRED = 0xC0A8
PID_RECEIVER = 0xC54D

ERROR_NAMES = {
    0x00: "no error", 0x01: "unknown", 0x02: "invalid argument",
    0x03: "out of range", 0x04: "hardware error", 0x05: "logitech internal",
    0x06: "invalid feature index", 0x07: "invalid function", 0x08: "busy",
    0x09: "unsupported",
}

SWID_GUI = 0x0A
SWID_TRAY = 0x0B
SWID_CLI = 0x0C


class HidppError(Exception):
    """The device answered with an error frame."""

    def __init__(self, feature_index: int, function: int, code: int, raw: bytes):
        self.feature_index, self.function, self.code, self.raw = feature_index, function, code, raw
        super().__init__(
            f"device error 0x{code:02x} ({ERROR_NAMES.get(code, 'unrecognised')}) "
            f"on feature index 0x{feature_index:02x} fn {function}")


class HidppTimeout(Exception):
    """No matching reply arrived in time (mouse asleep, out of range, busy)."""


class DeviceGone(Exception):
    """The hidraw node vanished or became unusable."""


def build_request(dev_index: int, feature_index: int, function: int, swid: int,
                  params: bytes = b"") -> bytes:
    if len(params) > 16:
        raise ValueError("HID++ long reports carry at most 16 parameter bytes")
    header = bytes([dev_index & 0xFF, feature_index & 0xFF, ((function & 0x0F) << 4) | (swid & 0x0F)])
    if len(params) <= 3:
        return bytes([REPORT_SHORT]) + header + params.ljust(3, b"\x00")
    return bytes([REPORT_LONG]) + header + params.ljust(16, b"\x00")


def match_reply(report: bytes, feature_index: int, function: int, swid: int):
    """Classify an incoming report against an outstanding request.

    Returns ("ok", params) / ("error", HidppError) / (None, None) for unrelated traffic.
    """
    if len(report) < 4 or report[0] not in HIDPP_REPORT_IDS:
        return None, None
    if report[2] in (0xFF, 0x8F) and len(report) >= 6:
        if report[3] == feature_index and (report[4] & 0x0F) == swid:
            return "error", HidppError(feature_index, function, report[5], bytes(report))
        return None, None
    # Match on feature index + swid only: some setters echo the function nibble
    # inconsistently, and we drain stale traffic before every request anyway.
    if report[2] == feature_index and (report[3] & 0x0F) == swid:
        return "ok", bytes(report[4:])
    return None, None


@dataclass
class HidrawNode:
    path: str
    name: str
    vendor: int
    product: int

    @property
    def kind(self) -> str:
        if self.product == PID_WIRELESS:
            return "wireless"
        if self.product == PID_WIRED:
            return "wired"
        if self.product == PID_RECEIVER:
            return "receiver"
        return "other"


def list_logitech_nodes(sys_root: str = "/sys/class/hidraw") -> list[HidrawNode]:
    nodes = []
    try:
        entries = sorted(os.listdir(sys_root), key=lambda n: int(n[6:]) if n[6:].isdigit() else 999)
    except FileNotFoundError:
        return nodes
    for entry in entries:
        try:
            with open(os.path.join(sys_root, entry, "device", "uevent")) as fh:
                info = dict(line.split("=", 1) for line in fh.read().splitlines() if "=" in line)
        except OSError:
            continue
        hid_id = info.get("HID_ID", "")
        parts = hid_id.split(":")
        if len(parts) != 3:
            continue
        vendor, product = int(parts[1], 16), int(parts[2], 16)
        if vendor != VENDOR_LOGITECH:
            continue
        nodes.append(HidrawNode("/dev/" + entry, info.get("HID_NAME", ""), vendor, product))
    return nodes


class HidrawTransport:
    """One open hidraw node, speaking HID++ with a fixed device index and swid."""

    def __init__(self, path: str, dev_index: int, swid: int = SWID_GUI):
        self.path = path
        self.dev_index = dev_index
        self.swid = swid
        self._lock = threading.RLock()
        try:
            self._fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError:
            raise
        except OSError as exc:
            raise DeviceGone(str(exc)) from exc
        self.trace = None  # optional callable(direction, bytes) for the raw console

    def close(self):
        with self._lock:
            if self._fd is not None:
                try:
                    os.close(self._fd)
                finally:
                    self._fd = None

    def _read_one(self, timeout: float) -> bytes | None:
        r, _, _ = select.select([self._fd], [], [], max(0.0, timeout))
        if not r:
            return None
        try:
            return os.read(self._fd, 64)
        except BlockingIOError:
            return b""
        except OSError as exc:
            if exc.errno in (errno.ENODEV, errno.EIO, errno.EBADF):
                raise DeviceGone(str(exc)) from exc
            raise

    def _drain(self):
        while True:
            r, _, _ = select.select([self._fd], [], [], 0)
            if not r:
                return
            try:
                os.read(self._fd, 64)
            except BlockingIOError:
                return
            except OSError as exc:
                raise DeviceGone(str(exc)) from exc

    def call(self, feature_index: int, function: int, params: bytes = b"",
             timeout: float = 1.5, retries: int = 1, expect_reply: bool = True) -> bytes:
        """Send a request and return the reply's parameter bytes (16 for long replies)."""
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return self._call_once(feature_index, function, params, timeout, expect_reply)
            except HidppTimeout as exc:
                last_exc = exc
                time.sleep(0.03 + 0.09 * attempt)
            except HidppError as exc:
                if exc.code != 0x08:  # only "busy" is worth a retry
                    raise
                last_exc = exc
                time.sleep(0.12)
        assert last_exc is not None
        raise last_exc

    def _call_once(self, feature_index, function, params, timeout, expect_reply) -> bytes:
        with self._lock:
            if self._fd is None:
                raise DeviceGone("transport closed")
            frame = build_request(self.dev_index, feature_index, function, self.swid, bytes(params))
            self._drain()
            if self.trace:
                self.trace(">", frame)
            try:
                os.write(self._fd, frame)
            except OSError as exc:
                raise DeviceGone(str(exc)) from exc
            if not expect_reply:
                return b""
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise HidppTimeout(f"no reply for feature index 0x{feature_index:02x} fn {function}")
                report = self._read_one(remaining)
                if not report:
                    continue
                kind, value = match_reply(report, feature_index, function, self.swid)
                if kind is None:
                    continue
                if self.trace:
                    self.trace("<", report)
                if kind == "error":
                    raise value
                return value
