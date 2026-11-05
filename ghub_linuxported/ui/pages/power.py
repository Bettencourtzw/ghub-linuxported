from __future__ import annotations

from gi.repository import Adw, Gtk

from .base import Page
from ... import storage


def _fmt(s):
    if s < 60:
        return f"{s} s"
    m, sec = divmod(s, 60)
    return f"{m} min" + (f" {sec} s" if sec else "")


class PowerPage(Page):
    key, title, icon = "power", "Power & battery", "battery-level-50-symbolic"
    subtitle = "Sleep timers and battery alerts"

    def build(self):
        cfg = self.win.config
        timers = self.group("Sleep timers", "Stored in the profile. Longer timers wake faster, shorter ones "
                                            "save battery. Values are in seconds.")
        self.psave = Adw.SpinRow.new_with_range(10, 3600, 10)
        self.psave.set_title("Low-power mode after")
        self.poff = Adw.SpinRow.new_with_range(60, 36000, 30)
        self.poff.set_title("Deep sleep after")
        for r in (self.psave, self.poff):
            r.connect("notify::value", lambda *_: self._timers())
            timers.add(r)

        bat = self.group("Battery")
        self.level = Adw.ActionRow(title="Level", css_classes=["property"])
        self.state = Adw.ActionRow(title="State", css_classes=["property"])
        self.bar = Gtk.LevelBar(min_value=0, max_value=100, valign=Gtk.Align.CENTER, width_request=200)
        self.bar.add_offset_value("low", 15)
        self.bar.add_offset_value("high", 30)
        self.level.add_suffix(self.bar)
        bat.add(self.level)
        bat.add(self.state)

        notes = self.group("Notifications", "Sent by the tray helper (ghub-linuxported-tray), which also shows "
                                            "battery and quick DPI/profile switching in your bar.")
        self.low_switch = Adw.SwitchRow(title="Low battery alert", active=cfg["notify_low_battery"])
        self.low_level = Adw.SpinRow.new_with_range(5, 50, 5)
        self.low_level.set_title("Alert below (%)")
        self.low_level.set_value(cfg["low_battery_percent"])
        self.charged = Adw.SwitchRow(title="Notify when fully charged", active=cfg["notify_charged"])
        self.reapply = Adw.SwitchRow(title="Re-apply live settings on reconnect",
                                     subtitle="Surface mode, and everything in host mode",
                                     active=cfg["reapply_on_connect"])
        for w, k in ((self.low_switch, "notify_low_battery"), (self.charged, "notify_charged"),
                     (self.reapply, "reapply_on_connect")):
            w.connect("notify::active", lambda row, _p, k=k: self._cfg(k, row.get_active()))
            notes.add(w)
        self.low_level.connect("notify::value", lambda row, _p: self._cfg("low_battery_percent",
                                                                          int(row.get_value())))
        notes.add(self.low_level)
        return self.prefs_page(timers, bat, notes)

    def _cfg(self, key, value):
        self.win.config[key] = value
        storage.save_config(self.win.config)

    def _timers(self):
        e = self.win.edit
        self.psave.set_subtitle(_fmt(int(self.psave.get_value())))
        self.poff.set_subtitle(_fmt(int(self.poff.get_value())))
        if self.loading or not e:
            return
        e.power_save_s = int(self.psave.get_value())
        e.power_off_s = int(self.poff.get_value())
        self.win.changed()

    def on_battery(self, b):
        if not b:
            return
        self.level.set_subtitle(f"{b.percent}%")
        self.bar.set_value(b.percent)
        self.state.set_subtitle(b.label + (" · external power" if b.external_power else ""))

    def fill(self, snap, edit):
        if edit:
            self.psave.set_value(edit.power_save_s)
            self.poff.set_value(edit.power_off_s)
            self._timers()
        self.on_battery(snap.battery)
