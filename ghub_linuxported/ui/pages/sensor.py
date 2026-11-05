from __future__ import annotations

from gi.repository import Adw, Gtk

from .base import Page
from ..widgets import toggle_group, set_toggle_silent
from ...hidpp.mouse import RATE_HZ, SURFACE_MODES, snap_dpi
from ...model.profile import LOD_NAMES
from ... import storage

LODS = ["Off (stage disabled)", "Low", "Medium", "High"]


class StageRow:
    def __init__(self, page, i):
        self.page, self.i = page, i
        self.row = Adw.ExpanderRow(title=f"Stage {i + 1}")
        self.badge = Gtk.Label(css_classes=["chip", "accent"], valign=Gtk.Align.CENTER, visible=False,
                               label="default")
        self.row.add_suffix(self.badge)
        self.enabled = Adw.SwitchRow(title="Enabled", subtitle="Part of the DPI button cycle")
        self.enabled.connect("notify::active", lambda *_: page.stage_changed(i))
        self.lock = Adw.SwitchRow(title="Same DPI for X and Y", active=True)
        self.lock.connect("notify::active", lambda *_: page.stage_changed(i))
        self.x = Adw.SpinRow.new_with_range(100, 44000, 50)
        self.x.set_title("DPI (X axis)")
        self.y = Adw.SpinRow.new_with_range(100, 44000, 50)
        self.y.set_title("DPI (Y axis)")
        for s in (self.x, self.y):
            s.set_numeric(True)
            s.connect("notify::value", lambda *_: page.stage_changed(i))
        self.lod = Adw.ComboRow(title="Lift-off distance", model=Gtk.StringList.new(LODS))
        self.lod.connect("notify::selected", lambda *_: page.stage_changed(i))
        for w in (self.enabled, self.lock, self.x, self.y, self.lod):
            self.row.add_row(w)


class SensorPage(Page):
    key, title, icon = "sensor", "Sensor", "power-profile-performance-symbolic"
    subtitle = "DPI, polling rate, lift-off and surface"

    def build(self):
        self.default_toggle = toggle_group(["1", "2", "3", "4", "5"], self._on_default)
        self._default_row = Adw.ActionRow(title="Default stage", subtitle="Loaded when the profile starts")
        self._default_row.add_suffix(self.default_toggle)
        self.stages_group = self.group(
            "DPI stages", "HERO 2 sensor, 100 – 44 000 DPI. The DPI button cycles through enabled stages. "
                          "Changes take effect when you save to the mouse.")
        self.stages_group.add(self._default_row)
        self.shift = Adw.ComboRow(title="DPI shift stage", subtitle="Used while a “DPI shift (hold)” button is held",
                                  model=Gtk.StringList.new([f"Stage {i}" for i in range(1, 6)]))
        self.shift.connect("notify::selected", self._on_shift)
        self.stages_group.add(self.shift)
        self.stage_rows = [StageRow(self, i) for i in range(5)]
        for r in self.stage_rows:
            self.stages_group.add(r.row)

        rate = self.group("Report rate", "How often the mouse reports to the PC. Higher is smoother and "
                                         "uses more battery. Applies instantly on the active link.")
        self.rate_wireless = toggle_group([f"{hz:g}" if hz < 1000 else f"{hz // 1000}K" for hz in RATE_HZ],
                                          self._on_rate_wireless)
        rw = Adw.ActionRow(title="LIGHTSPEED wireless (Hz)")
        rw.add_suffix(self.rate_wireless)
        rate.add(rw)
        self.rate_wired = toggle_group(["125", "250", "500", "1K"], self._on_rate_wired)
        rwd = Adw.ActionRow(title="Wired USB (Hz)", subtitle="The cable is limited to 1000 Hz")
        rwd.add_suffix(self.rate_wired)
        rate.add(rwd)

        tracking = self.group("Tracking")
        self.surface = toggle_group(SURFACE_MODES, self._on_surface)
        sr = Adw.ActionRow(title="Gaming surface mode",
                           subtitle="Tunes tracking to your mouse pad. Live setting, re-applied by the tray helper.")
        sr.add_suffix(self.surface)
        tracking.add(sr)
        self.angle = Adw.SwitchRow(title="Angle snapping", subtitle="Straightens near-horizontal movements "
                                                                    "(stored in the profile)")
        self.angle.connect("notify::active", self._on_angle)
        tracking.add(self.angle)

        return self.prefs_page(self.stages_group, rate, tracking)

    # --- handlers
    def _edit(self):
        return None if self.loading else self.win.edit

    def stage_changed(self, i):
        e = self._edit()
        if not e:
            return
        r = self.stage_rows[i]
        s = e.stages[i]
        ranges = self.win.snapshot.dpi_ranges
        x = snap_dpi(int(r.x.get_value()), ranges)
        y = x if r.lock.get_active() else snap_dpi(int(r.y.get_value()), ranges)
        lod = r.lod.get_selected()
        if not r.enabled.get_active():
            lod = 0
        elif lod == 0:
            lod = s.lod or 2
        s.x, s.y, s.lod = x, y, lod
        self.loading = True
        r.y.set_sensitive(not r.lock.get_active())
        if r.lock.get_active():
            r.y.set_value(x)
        r.lod.set_selected(lod)
        r.enabled.set_active(lod != 0)
        self._subtitle(i)
        self.loading = False
        self.win.changed()

    def _subtitle(self, i):
        s = self.win.edit.stages[i]
        r = self.stage_rows[i]
        dpi = f"{s.x}" if s.x == s.y else f"{s.x} × {s.y}"
        r.row.set_subtitle(f"{dpi} DPI · LOD {LOD_NAMES.get(s.lod, '—')}" if s.enabled else "Disabled")
        r.badge.set_visible(i == self.win.edit.default_stage)
        t = self.default_toggle.get_toggle(i)
        t.set_enabled(s.enabled)

    def _on_default(self, i):
        e = self._edit()
        if not e:
            return
        if not e.stages[i].enabled:
            self.win.toast("Enable that stage first")
            set_toggle_silent(self.default_toggle, e.default_stage)
            return
        e.default_stage = i
        for k in range(5):
            self._subtitle(k)
        self.win.changed()

    def _on_shift(self, row, _p):
        e = self._edit()
        if e:
            e.shift_stage = row.get_selected()
            self.win.changed()

    def _on_rate_wireless(self, i):
        e = self._edit()
        if not e:
            return
        hz = RATE_HZ[i]
        e.rate_wireless_hz = hz
        if not self.win.snapshot.wired:
            self.win.live(lambda s: s.apply_rate(hz))
        self.win.changed()

    def _on_rate_wired(self, i):
        e = self._edit()
        if not e:
            return
        hz = RATE_HZ[i]
        e.rate_wired_hz = hz
        if self.win.snapshot.wired:
            self.win.live(lambda s: s.apply_rate(hz))
        self.win.changed()

    def _on_surface(self, i):
        if self.loading:
            return
        self.win.config.setdefault("live", {})["surface"] = i
        storage.save_config(self.win.config)
        self.win.run(lambda s: s.apply_surface(i), lambda _r: self.win.toast(f"Surface mode: {SURFACE_MODES[i]}"))

    def _on_angle(self, row, _p):
        e = self._edit()
        if e:
            e.angle_snapping = row.get_active()
            self.win.changed()

    def fill(self, snap, edit):
        if not edit:
            return
        for i, s in enumerate(edit.stages):
            r = self.stage_rows[i]
            r.enabled.set_active(s.enabled)
            r.lock.set_active(s.x == s.y)
            r.x.set_value(s.x)
            r.y.set_value(s.y)
            r.y.set_sensitive(s.x != s.y)
            r.lod.set_selected(min(3, s.lod))
            self._subtitle(i)
        set_toggle_silent(self.default_toggle, edit.default_stage)
        self.shift.set_selected(edit.shift_stage)
        supported = snap.rate_supported or RATE_HZ
        for i, hz in enumerate(RATE_HZ):
            self.rate_wireless.get_toggle(i).set_enabled(snap.wired or hz in supported)
        set_toggle_silent(self.rate_wireless, RATE_HZ.index(edit.rate_wireless_hz))
        set_toggle_silent(self.rate_wired, min(3, RATE_HZ.index(edit.rate_wired_hz)))
        if snap.surface is not None:
            set_toggle_silent(self.surface, snap.surface)
        self.angle.set_active(edit.angle_snapping)
