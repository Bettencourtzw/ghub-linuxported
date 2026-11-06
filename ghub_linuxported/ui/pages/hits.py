from __future__ import annotations

import copy

from gi.repository import Adw, Gtk

from .base import Page
from ..widgets import toggle_group, set_toggle_silent, Debouncer
from ...hidpp.mouse import HitsButton
from ...model import hits_codes
from ... import storage

SIDES = ("Left click", "Right click")


class ButtonCard:
    def __init__(self, page, index):
        self.page, self.index = page, index
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, css_classes=["card", "hits-card"],
                           hexpand=True)
        head = Gtk.Box(spacing=8)
        head.append(Gtk.Image(icon_name="input-mouse-symbolic", pixel_size=20))
        head.append(Gtk.Label(label=SIDES[index], css_classes=["title-3"], xalign=0, hexpand=True))
        self.code_label = Gtk.Label(css_classes=["caption", "dim-label", "monospace"])
        head.append(self.code_label)
        self.box.append(head)

        self.box.append(self._caption("Actuation point", "Where along the travel the click fires"))
        self.act = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 10, 1)
        self.act.set_round_digits(0)
        self.act.set_draw_value(True)
        self.act.set_value_pos(Gtk.PositionType.RIGHT)
        for v in range(1, 11):
            self.act.add_mark(v, Gtk.PositionType.BOTTOM, None)
        self.act.connect("value-changed", lambda *_: self.page.changed(self.index))
        self.box.append(self.act)
        ends = Gtk.Box()
        ends.append(Gtk.Label(label="Shallow · fastest", css_classes=["caption", "dim-label"], hexpand=True, xalign=0))
        ends.append(Gtk.Label(label="Deep · fewer misclicks", css_classes=["caption", "dim-label"], xalign=1,
                              margin_end=40))
        self.box.append(ends)

        self.box.append(self._caption("Rapid trigger", "Re-arms the click as soon as you start lifting"))
        self.rt = toggle_group(["Off", "1", "2", "3", "4", "5"], lambda _i: self.page.changed(self.index))
        self.box.append(self.rt)

        self.box.append(self._caption("Click haptics", "Strength of the simulated click feel"))
        self.hap = toggle_group(["Off", "1", "2", "3", "4", "5"], lambda _i: self.page.changed(self.index))
        self.box.append(self.hap)

    @staticmethod
    def _caption(title, sub):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=4)
        b.append(Gtk.Label(label=title, xalign=0, css_classes=["heading"]))
        b.append(Gtk.Label(label=sub, xalign=0, css_classes=["caption", "dim-label"]))
        return b

    def get(self, base: HitsButton) -> HitsButton:
        rt = self.rt.get_active()
        return HitsButton(actuation=int(round(self.act.get_value())),
                          rt_level=rt if rt else base.rt_level, rt_enabled=rt > 0,
                          haptics=self.hap.get_active())

    def set(self, h: HitsButton):
        self.act.set_value(h.actuation)
        set_toggle_silent(self.rt, h.rapid_trigger)
        set_toggle_silent(self.hap, h.haptics)


class HitsPage(Page):
    key, title, icon = "hits", "HITS switches", "input-touchpad-symbolic"
    subtitle = "Actuation, rapid trigger and haptics"

    def build(self):
        self.debounce = [Debouncer(150), Debouncer(150)]
        cfg = self.win.config
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=1000, margin_top=24, margin_bottom=24, margin_start=16, margin_end=16)
        scroller.set_child(clamp)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        clamp.set_child(col)

        top = Adw.PreferencesGroup(
            title="Haptic Inductive Trigger System",
            description="Changes apply to the mouse instantly so you can feel them. "
                        "Use “Save to mouse” to keep them in the onboard profile.")
        self.link = Adw.SwitchRow(title="Same settings for both buttons", active=cfg.get("link_hits_buttons", True))
        self.link.connect("notify::active", self._on_link)
        top.add(self.link)
        col.append(top)

        cards = Gtk.Box(spacing=16, homogeneous=True)
        self.win.responsive(cards, "orientation", Gtk.Orientation.VERTICAL)
        self.cards = [ButtonCard(self, 0), ButtonCard(self, 1)]
        for c in self.cards:
            cards.append(c.box)
        col.append(cards)

        codes = Adw.PreferencesGroup(title="HITS code",
                                     description="Import or share settings as a G HUB compatible HITS code.")
        self.code_row = Adw.ActionRow(title="Current code", subtitle_selectable=True)
        copyb = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                           tooltip_text="Copy")
        copyb.connect("clicked", lambda *_: (self.win.get_clipboard().set(self.code_row.get_subtitle()),
                                             self.win.toast("HITS code copied")))
        self.code_row.add_suffix(copyb)
        codes.add(self.code_row)
        self.import_row = Adw.EntryRow(title="Paste a HITS code to import", show_apply_button=True)
        self.import_row.connect("apply", self._on_import)
        codes.add(self.import_row)
        col.append(codes)

        presets = Adw.PreferencesGroup(title="Pro presets",
                                       description="Published by Logitech G (pro players' HITS codes).")
        for player, game, code in hits_codes.PRO_PRESETS:
            left, right = hits_codes.decode(code)
            row = Adw.ActionRow(title=f"{player}", subtitle=f"{game} · {self._summary(left, right)}")
            btn = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER, css_classes=["pill"])
            btn.connect("clicked", lambda _b, c=code, p=player: self._apply_code(c, p))
            row.add_suffix(btn)
            presets.add(row)
        col.append(presets)
        return scroller

    @staticmethod
    def _summary(left, right):
        def one(h):
            return f"A{h.actuation} RT{h.rt_level if h.rt_enabled else '–'} H{h.haptics}"
        return f"L {one(left)}  ·  R {one(right)}"

    def _on_link(self, row, _p):
        self.win.config["link_hits_buttons"] = row.get_active()
        storage.update_config({"link_hits_buttons": row.get_active()})

    def changed(self, index):
        edit = self.win.edit
        if self.loading or not edit:
            return
        h = self.cards[index].get(edit.hits[index])
        targets = [0, 1] if self.link.get_active() else [index]
        for t in targets:
            edit.hits[t] = copy.deepcopy(h)
            if t != index:
                self.loading = True
                self.cards[t].set(h)
                self.loading = False
            self._push(t, h)
        self._update_codes()
        self.win.changed()

    def _push(self, i, h):
        self.debounce[i](lambda: self.win.live(lambda s: s.apply_hits(i, h)))

    def _apply_code(self, code, label):
        try:
            left, right = hits_codes.decode(code)
        except hits_codes.InvalidHitsCode as exc:
            self.win.toast(str(exc))
            return
        if not self.win.edit:
            return
        self.win.edit.hits = [left, right]
        self.load(self.win.snapshot, self.win.edit)
        for i, h in enumerate((left, right)):
            self._push(i, h)
        self.win.changed()
        self.win.toast(f"Applied {label}")

    def _on_import(self, row):
        self._apply_code(row.get_text(), "imported HITS code")
        row.set_text("")

    def _update_codes(self):
        e = self.win.edit
        if not e:
            return
        code = hits_codes.encode(e.hits[0], e.hits[1])
        self.code_row.set_subtitle(code)
        for c, h in zip(self.cards, e.hits):
            c.code_label.set_label(f"A{h.actuation} · RT {h.rt_level if h.rt_enabled else 'off'} · H{h.haptics}")

    def fill(self, snap, edit):
        if not edit:
            return
        for c, h in zip(self.cards, edit.hits):
            c.set(h)
        self._update_codes()
