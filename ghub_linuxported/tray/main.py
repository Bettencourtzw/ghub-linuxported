"""Tray integration (runs inside the app process): battery in your bar, alerts,
quick DPI/profile switching, re-applying live-only settings on reconnect, and
keeping the app alive in the background when the window is closed."""
from __future__ import annotations

import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import GLib  # noqa: E402

from ..service import DeviceService  # noqa: E402
from ..hidpp.transport import SWID_TRAY  # noqa: E402
from .. import storage  # noqa: E402
from .sni import StatusNotifierItem, MenuItem, notify  # noqa: E402


def battery_icon(percent: int, charging: bool) -> str:
    level = min(100, max(0, int(round(percent / 10.0)) * 10))
    return f"battery-level-{level}{'-charging' if charging else ''}-symbolic"


def tray_host_available() -> bool:
    """True when a StatusNotifierWatcher (Waybar tray, KDE, ...) is running."""
    from gi.repository import Gio
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        r = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                          "NameHasOwner", GLib.Variant("(s)", ("org.kde.StatusNotifierWatcher",)),
                          GLib.VariantType("(b)"), Gio.DBusCallFlags.NONE, 1000, None)
        return r.unpack()[0]
    except GLib.Error:
        return False


class Tray:
    def __init__(self, on_open, on_quit):
        self._on_open, self._on_quit = on_open, on_quit
        self.extra_devices = []  # other devices from the landing-page scan (battery lines)
        self.cfg = storage.load_config()
        self.svc = DeviceService(dispatch=lambda fn, *a: GLib.idle_add(lambda: fn(*a) and False),
                                 swid=SWID_TRAY, poll_battery_s=60)
        self.item = StatusNotifierItem(storage.APP_ID, storage.APP_NAME, on_activate=self.open_app,
                                       on_scroll=self.scroll_stage, on_menu_open=self.menu_opened)
        self.low_notified = False
        self.charged_notified = False
        self.notif_id = 0
        self.svc.on("status", self.on_status)
        self.svc.on("battery", self.on_battery)
        self.svc.on("snapshot", lambda _s: self.rebuild_menu())
        self.rebuild_menu()

    # ---------------- device events
    def on_status(self, status, detail):
        if status == "connected":
            self.cfg = storage.load_config()
            if self.cfg.get("reapply_on_connect") and self.cfg.get("live"):
                live = self.cfg["live"]
                self.svc.submit(lambda s: s.reapply_live(live))
            self.item.set_status("Active")
        else:
            self.item.set_icon("input-mouse-symbolic")
            self.item.set_tooltip("PRO X2 SUPERSTRIKE", {"permission": "No access — install the udev rule",
                                                         "asleep": "Asleep — move the mouse"}.get(status,
                                                                                                 "Not connected"))
            self.item.set_status("Passive" if status != "permission" else "NeedsAttention")
        self.rebuild_menu()

    def on_battery(self, b):
        if not b:
            return
        self.cfg = storage.load_config()
        self.item.set_icon(battery_icon(b.percent, b.charging))
        snap = self.svc.snapshot
        prof = snap.active_profile
        lines = [f"Battery {b.percent}% · {b.label}"]
        if prof:
            st = prof.stages[snap.dpi_stage] if snap.dpi_stage < 5 else None
            lines.append(f"{prof.display_name} · {st.x if st else '?'} DPI")
        self.item.set_tooltip(snap.identity.name if snap.identity else "PRO X2 SUPERSTRIKE", "\n".join(lines))
        low = self.cfg.get("low_battery_percent", 15)
        if b.charging:
            self.low_notified = False
            if b.charging_state == 3 and self.cfg.get("notify_charged") and not self.charged_notified:
                self.notif_id = notify("Mouse fully charged", "PRO X2 SUPERSTRIKE is at 100%.",
                                       "battery-full-charged-symbolic", replaces_id=self.notif_id)
                self.charged_notified = True
        else:
            self.charged_notified = False
            if b.percent <= low and self.cfg.get("notify_low_battery") and not self.low_notified:
                self.notif_id = notify("Mouse battery low", f"PRO X2 SUPERSTRIKE is at {b.percent}%. "
                                       "Plug in the USB-C cable.", battery_icon(b.percent, False), urgency=2,
                                       replaces_id=self.notif_id)
                self.low_notified = True
            if b.percent > low + 5:
                self.low_notified = False
        self.item.set_status("NeedsAttention" if b.percent <= low and not b.charging else "Active")
        self.rebuild_menu()

    # ---------------- actions
    def open_app(self):
        self._on_open()

    def set_stage(self, i):
        self.svc.submit(lambda s: s.apply_stage(i), lambda _r: (self.rebuild_menu(), self.on_battery(
            self.svc.snapshot.battery)))

    def scroll_stage(self, direction):
        snap = self.svc.snapshot
        prof = snap.active_profile
        if not prof:
            return
        enabled = [i for i, s in enumerate(prof.stages) if s.enabled]
        if snap.dpi_stage in enabled:
            k = (enabled.index(snap.dpi_stage) + direction) % len(enabled)
        else:
            k = 0
        self.set_stage(enabled[k])

    def set_profile(self, sector):
        self.svc.submit(lambda s: s.activate_profile(sector))

    def menu_opened(self):
        def job(s):
            s.snapshot.dpi_stage = s.mouse.dpi_stage_get()
            s.snapshot.active_sector = s.mouse.current_profile()
        self.svc.submit(job, lambda _r: self.rebuild_menu())

    def rebuild_menu(self):
        snap = self.svc.snapshot
        items = []
        b = snap.battery
        name = snap.identity.name if snap.identity else "PRO X2 SUPERSTRIKE"
        if self.svc.status == "connected" and b:
            items.append(MenuItem(f"{name} — {b.percent}% {'(charging)' if b.charging else ''}", enabled=False,
                                  icon=battery_icon(b.percent, b.charging)))
        else:
            items.append(MenuItem(f"{name} — not connected", enabled=False))
        prof = snap.active_profile
        if self.svc.status == "connected" and prof:
            items.append(MenuItem(separator=True))
            stages = [MenuItem(f"Stage {i + 1}: {s.x} DPI", callback=lambda i=i: self.set_stage(i),
                               radio=(i == snap.dpi_stage))
                      for i, s in enumerate(prof.stages) if s.enabled]
            items.append(MenuItem("DPI stage", children=stages))
            profs = [MenuItem(snap.profiles[e.sector].display_name if e.sector in snap.profiles else f"Slot {e.sector}",
                              callback=lambda sec=e.sector: self.set_profile(sec), radio=(e.sector == snap.active_sector))
                     for e in snap.directory if e.enabled]
            if len(profs) > 1:
                items.append(MenuItem("Profile", children=profs))
        others = [d for d in self.extra_devices if d.kind != "mouse" and d.battery and d.awake]
        if others:
            items.append(MenuItem(separator=True))
            for d in others:
                items.append(MenuItem(f"{d.title} — {d.battery.percent}%", enabled=False,
                                      icon=battery_icon(d.battery.percent, d.battery.charging)))
        items.append(MenuItem(separator=True))
        items.append(MenuItem("Open G HUB", callback=self.open_app))
        items.append(MenuItem("Quit", callback=self.quit))
        self.item.set_menu(items)

    def keyboard_battery(self, dev):
        """Low-battery alert + menu update for keyboards (battery from their service)."""
        b = dev.battery
        known = {d.key: d for d in self.extra_devices}
        known[dev.key] = dev
        self.extra_devices = list(known.values())
        low = self.cfg.get("low_battery_percent", 15)
        flag = f"_low_{dev.key}"
        if b and not b.charging and b.percent <= low and self.cfg.get("notify_low_battery"):
            if not getattr(self, flag, False):
                notify(f"{dev.title} battery low", f"{b.percent}% left. Plug in the USB-C cable.",
                       battery_icon(b.percent, False), urgency=2)
                setattr(self, flag, True)
        elif b and (b.charging or b.percent > low + 5):
            setattr(self, flag, False)
        self.rebuild_menu()

    def set_devices(self, devs):
        self.extra_devices = devs
        self.rebuild_menu()

    def quit(self):
        self._on_quit()

    def start(self):
        self.svc.start()

    def stop(self):
        self.svc.stop()


def main():
    """`ghub-linuxported-tray`: start the app hidden in the tray (single instance)."""
    from ..ui.app import App
    return App().run([sys.argv[0], "--background"])
