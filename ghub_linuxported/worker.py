"""DeviceWorker: one background thread per device that owns all HID++ traffic.

Subclasses implement open_device() (returns a connected device object or raises),
refresh() (full re-read, device thread) and optionally poll() (periodic, e.g. battery).
The UI submits jobs; results come back through `dispatch` (GLib.idle_add in GTK).
"""
from __future__ import annotations

import queue
import threading
import time
import traceback

from .hidpp.transport import HidppError, HidppTimeout, DeviceGone


class DeviceWorker:
    noun = "device"

    def __init__(self, dispatch=None, poll_s: float = 30.0):
        self.dispatch = dispatch or (lambda fn, *a: fn(*a))
        self.poll_s = poll_s
        self.dev = None
        self.status = "searching"  # searching | permission | connected | asleep
        self.status_detail = ""
        self._jobs: queue.Queue = queue.Queue()
        self._listeners: dict[str, list] = {}
        self._stop = threading.Event()
        self._queue_lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name=f"ghub-{self.noun}", daemon=False)

    # ---------- to override ----------
    def open_device(self):
        raise NotImplementedError

    def refresh(self):
        raise NotImplementedError

    def poll(self):
        pass

    def on_stop(self):
        """Device thread, before the device is closed on stop() (e.g. release control)."""

    # ---------- events ----------
    def on(self, event: str, cb):
        self._listeners.setdefault(event, []).append(cb)
        return cb

    def off(self, event: str, cb):
        try:
            self._listeners.get(event, []).remove(cb)
        except ValueError:
            pass

    def _emit(self, event: str, *args):
        for cb in self._listeners.get(event, []):
            self.dispatch(cb, *args)

    def start(self):
        self._thread.start()

    def stop(self, wait: float | None = None):
        with self._queue_lock:
            if not self._stop.is_set():
                self._stop.set()
                self._jobs.put(None)
        if wait != 0 and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(wait)

    def submit(self, fn, on_done=None, on_error=None):
        """Run fn(worker) on the device thread."""
        with self._queue_lock:
            closing = self._stop.is_set()
            if not closing:
                self._jobs.put((fn, on_done, on_error))
        if closing and on_error:
            self.dispatch(on_error, ConnectionError("The device is closing"))

    # ---------- loop ----------
    def _set_status(self, status: str, detail: str = ""):
        if (status, detail) != (self.status, self.status_detail):
            self.status, self.status_detail = status, detail
            self._emit("status", status, detail)

    def _run(self):
        try:
            next_poll = 0.0
            while True:
                if self.dev is None:
                    if not self._stop.is_set():
                        self._try_connect()
                    if self.dev is None:
                        if self._drain_jobs_disconnected(timeout=2.0):
                            break
                        continue
                    next_poll = time.monotonic() + self.poll_s
                try:
                    job = self._jobs.get(timeout=max(0.1, next_poll - time.monotonic()))
                except queue.Empty:
                    job = "poll"
                if job is None:
                    break
                if job == "poll":
                    next_poll = time.monotonic() + self.poll_s
                    self._safe(self.poll)
                    continue
                fn, on_done, on_error = job
                try:
                    result = fn(self)
                    if on_done:
                        self.dispatch(on_done, result)
                except (HidppTimeout, DeviceGone) as exc:
                    self._lost(exc)
                    if on_error:
                        self.dispatch(on_error, exc)
                except Exception as exc:  # report every failure to the UI
                    traceback.print_exc()
                    if on_error:
                        self.dispatch(on_error, exc)
        finally:
            if self.dev:
                try:
                    self.on_stop()
                except Exception:  # noqa: BLE001 - best effort on shutdown
                    traceback.print_exc()
                self.dev.close()

    def _drain_jobs_disconnected(self, timeout: float):
        try:
            job = self._jobs.get(timeout=timeout)
        except queue.Empty:
            return
        if job is None:
            return True
        if job == "poll":
            return
        _fn, _done, on_error = job
        if on_error:
            self.dispatch(on_error, ConnectionError(f"The {self.noun} is not connected"))

    def _safe(self, fn):
        try:
            fn()
        except (HidppTimeout, DeviceGone) as exc:
            self._lost(exc)
        except Exception:
            traceback.print_exc()

    def _lost(self, exc):
        if self.dev and isinstance(exc, HidppTimeout):
            try:
                if self.dev.ping():
                    return  # transient timeout, link still fine
            except (DeviceGone, HidppError, OSError):
                pass
        if self.dev:
            self.dev.close()
        self.dev = None
        self._set_status("asleep", f"The {self.noun} stopped answering. Use it to wake it up.")

    def _try_connect(self):
        try:
            d = self.open_device()
        except PermissionError as exc:
            self._set_status("permission", str(exc))
            return
        except Exception as exc:
            if self.status != "asleep":
                self._set_status("searching", str(exc))
            return
        if self._listeners.get("trace"):
            d.t.trace = lambda direction, b: self._emit("trace", direction, b)
        self.dev = d
        try:
            self.refresh()
            self._set_status("connected", getattr(d, "connection", ""))
        except Exception as exc:
            traceback.print_exc()
            d.close()
            self.dev = None
            self._set_status("asleep", f"Connected, but the {self.noun} did not answer ({exc}). "
                                       f"Use it to wake it.")
