from __future__ import annotations

from gi.repository import Adw, Gtk

from .base import Page
from ..widgets import MouseDiagram, BatteryRing, toggle_group, set_toggle_silent
from ...hidpp.mouse import SURFACE_MODES, HOST_MODE
from ...model.profile import LOD_NAMES


class OverviewPage(Page):
    key, title, icon = "overview", "Overview", "input-mouse-symbolic"
    subtitle = "Device status at a glance"

    def build(self):
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=980, margin_top=24, margin_bottom=24, margin_start=16, margin_end=16)
        scroller.set_child(clamp)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        clamp.set_child(col)

        # hero card
        hero = Gtk.Box(spacing=24, css_classes=["card", "hero"])
        self.diagram = MouseDiagram(selectable=False, height=300)
        self.diagram.set_hexpand(False)
        self.diagram.set_margin_start(24)
        self.diagram.set_margin_top(16)
        self.diagram.set_margin_bottom(16)
        hero.append(self.diagram)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER, hexpand=True)
        self.name = Gtk.Label(xalign=0, css_classes=["title-1"], wrap=True)
        self.conn = Gtk.Label(xalign=0, css_classes=["dim-label"])
        info.append(Gtk.Label(label="LOGITECH G", xalign=0, css_classes=["caption-heading", "accent"]))
        info.append(self.name)
        info.append(self.conn)
        chips = Adw.WrapBox(child_spacing=8, line_spacing=8, margin_top=12)
        self.chips = {}
        for k in ("profile", "dpi", "rate", "mode"):
            lab = Gtk.Label(css_classes=["chip"])
            self.chips[k] = lab
            chips.append(lab)
        info.append(chips)
        hero.append(info)
        self.battery = BatteryRing(size=150)
        self.battery.set_valign(Gtk.Align.CENTER)
        self.battery.set_margin_end(32)
        hero.append(self.battery)
        col.append(hero)

        # quick DPI stage switch
        self.stage_group = Adw.PreferencesGroup(title="DPI stage",
                                                description="Switch the active stage instantly (like the DPI button).")
        self.stage_toggle = toggle_group(["1", "2", "3", "4", "5"], self._on_stage)
        self.stage_toggle.set_halign(Gtk.Align.START)
        self.stage_group.add(self.stage_toggle)
        col.append(self.stage_group)

        # stat tiles
        tiles = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, min_children_per_line=2,
                            column_spacing=12, row_spacing=12, homogeneous=True)
        self.tiles = {}
        for k, title in (("left", "Left click"), ("right", "Right click"), ("bhop", "Bhop filter"),
                         ("surface", "Surface mode")):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, css_classes=["card", "tile"])
            box.append(Gtk.Label(label=title.upper(), xalign=0, css_classes=["caption-heading", "dim-label"]))
            val = Gtk.Label(xalign=0, css_classes=["title-3"], wrap=True)
            sub = Gtk.Label(xalign=0, css_classes=["caption", "dim-label"], wrap=True)
            box.append(val)
            box.append(sub)
            self.tiles[k] = (val, sub)
            tiles.append(box)
        col.append(tiles)

        dev = Adw.PreferencesGroup(title="Device")
        self.rows = {}
        for k, t in (("unit", "Unit ID"), ("model", "Model"), ("fw", "Firmware"), ("proto", "HID++ protocol"),
                     ("node", "Device node"), ("charge", "Charging state")):
            r = Adw.ActionRow(title=t, subtitle_selectable=True, css_classes=["property"])
            self.rows[k] = r
            dev.add(r)
        col.append(dev)
        return scroller

    def _on_stage(self, i):
        if self.loading:
            return
        self.win.run(lambda s: s.apply_stage(i), lambda _r: self.fill(self.win.snapshot, self.win.edit))

    def on_battery(self, b):
        if b:
            self.battery.set_value(b.percent, b.charging)
            self.rows["charge"].set_subtitle(b.label + (" · external power" if b.external_power else ""))

    def fill(self, snap, edit):
        ident = snap.identity
        if not ident:
            return
        self.name.set_label(ident.name)
        self.conn.set_label(ident.connection)
        active = snap.active_profile
        self.chips["profile"].set_label(f"● {active.display_name}" if active else "No profile")
        if active:
            stage = active.stages[snap.dpi_stage] if snap.dpi_stage < len(active.stages) else None
            dpi = f"{stage.x}" if stage and stage.x == stage.y else f"{stage.x}×{stage.y}" if stage else "?"
            self.chips["dpi"].set_label(f"{dpi} DPI")
            rate = active.rate_wired_hz if snap.wired else active.rate_wireless_hz
            self.chips["rate"].set_label(f"{rate} Hz")
            set_toggle_silent(self.stage_toggle, snap.dpi_stage)
            for i in range(5):
                t = self.stage_toggle.get_toggle(i)
                s = active.stages[i]
                t.set_label(f"{s.x}" if s.enabled else "off")
                t.set_enabled(s.enabled)
        self.chips["mode"].set_label("Host mode" if snap.mode == HOST_MODE else "Onboard memory")
        for side, h in zip(("left", "right"), snap.live_hits):
            val, sub = self.tiles[side]
            val.set_label(f"Actuation {h.actuation}")
            sub.set_label(f"Rapid trigger {h.rt_level if h.rt_enabled else 'off'} · haptics "
                          f"{h.haptics if h.haptics else 'off'}")
        val, sub = self.tiles["bhop"]
        val.set_label("Off" if not snap.bhop_ms else f"{snap.bhop_ms} ms")
        sub.set_label("Scroll wheel filter")
        val, sub = self.tiles["surface"]
        val.set_label(SURFACE_MODES[snap.surface] if snap.surface is not None else "—")
        sub.set_label("Gaming surface tuning")
        self.rows["unit"].set_subtitle(ident.unit_id or "—")
        self.rows["model"].set_subtitle(f"{ident.model_id} {ident.model_string}".strip() or "—")
        self.rows["fw"].set_subtitle("\n".join(ident.firmware) or "—")
        self.rows["proto"].set_subtitle(ident.protocol or "—")
        self.rows["node"].set_subtitle(ident.node or "—")
        self.on_battery(snap.battery)
