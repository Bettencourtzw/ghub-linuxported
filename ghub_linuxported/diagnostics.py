"""Measure the real report (polling) rate.

The rate getter is stale on this firmware, so we count actual input reports:
hidraw broadcasts every report to every reader, so a second read-only handle on
the mouse node sees the motion reports. Rate = 1 / median(interval) while the
mouse moves.
"""
from __future__ import annotations

import os
import select
import statistics
import time
from dataclasses import dataclass

from .hidpp.transport import HIDPP_REPORT_IDS


@dataclass
class RateResult:
    hz: float
    reports: int
    seconds: float
    jitter_us: float

    @property
    def nominal(self) -> int:
        for hz in (125, 250, 500, 1000, 2000, 4000, 8000):
            if abs(self.hz - hz) / hz < 0.15:
                return hz
        return int(round(self.hz))


def measure_report_rate(path: str, seconds: float = 2.0, progress=None, stop=None) -> RateResult:
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    stamps: list[int] = []
    t0 = time.monotonic()
    try:
        while time.monotonic() - t0 < seconds:
            if stop and stop():
                break
            r, _, _ = select.select([fd], [], [], 0.05)
            if not r:
                continue
            while True:
                try:
                    data = os.read(fd, 64)
                except BlockingIOError:
                    break
                if data and data[0] not in HIDPP_REPORT_IDS:
                    stamps.append(time.monotonic_ns())
            if progress:
                progress(min(1.0, (time.monotonic() - t0) / seconds), len(stamps))
    finally:
        os.close(fd)
    # Gaps over 10 ms are pauses in movement (the mouse sends nothing while still).
    # Use count / active time rather than the median gap: at 4-8 kHz userspace
    # receives reports in bursts, so individual gaps are meaningless.
    core = [b - a for a, b in zip(stamps, stamps[1:]) if 0 <= b - a < 10_000_000]
    if len(core) < 20 or sum(core) == 0:
        return RateResult(0.0, len(stamps), seconds, 0.0)
    jitter = statistics.pstdev(core) / 1000 if len(core) > 1 else 0.0
    return RateResult(len(core) * 1e9 / sum(core), len(stamps), seconds, jitter)
