from __future__ import annotations

import json
import time
from pathlib import Path

from gi.repository import Adw, Gio, GLib, Gtk

from .base import Page
from ..widgets import toggle_group, set_toggle_silent
from ...hidpp.mouse import ONBOARD_MODE, HOST_MODE
from ...model import hits_codes
from ... import storage


class ProfilesPage(Page):
    key, title, icon = "profiles", "Profiles", "user-bookmarks-symbolic"
    subtitle = "Onboard memory, import/export, backups"

    def build(self):
        mode = self.group("Control mode")
        self.mode_toggle = toggle_group(["Onboard", "Host"], self._on_mode)
        mr = Adw.ActionRow(title="Who controls the settings",
                           subtitle="Onboard: the mouse runs its stored profiles anywhere. Host: settings are "
                                    "applied live by this app and the tray helper; stored profiles are bypassed.")
        mr.add_suffix(self.mode_toggle)
        mode.add(mr)

        self.list_group = self.group("Onboard profiles",
                                     "Enabled profiles are part of the on-mouse profile cycle.")
        self.pristine = Adw.ActionRow(title="Factory profile in use", visible=False,
                                      subtitle="Your mouse runs its read-only factory profile. The first save "
                                               "creates editable profile 1 from it.")
        self.pristine.add_prefix(Gtk.Image(icon_name="dialog-information-symbolic"))
        self.list_group.add(self.pristine)
        self.rows = []

        io = self.group("Import / export", "Profiles are saved as JSON (settings + HITS code).")
        exp = Adw.ButtonRow(title="Export the edited profile…", start_icon_name="document-save-as-symbolic")
        exp.connect("activated", lambda *_: self._export())
        imp = Adw.ButtonRow(title="Import into the edited profile…", start_icon_name="document-open-symbolic")
        imp.connect("activated", lambda *_: self._import())
        io.add(exp)
        io.add(imp)

        self.backup_group = self.group("Backups", "Taken automatically before every write to the mouse.")
        self.backup_rows = []
        openb = Gtk.Button(icon_name="folder-open-symbolic", css_classes=["flat"], tooltip_text="Open folder")
        openb.connect("clicked", lambda *_: self.win.activate_action("dev.backups", None))
        self.backup_group.set_header_suffix(openb)
        self.page = self.prefs_page(mode, self.list_group, io, self.backup_group)
        return self.page

    # ---------------- mode
    def _on_mode(self, i):
        if self.loading:
            return
        mode = HOST_MODE if i == 1 else ONBOARD_MODE
        snap = self.win.snapshot
        if mode == HOST_MODE and snap.active_profile:
            p = snap.active_profile
            st = p.stages[snap.dpi_stage] if snap.dpi_stage < 5 else p.stages[p.default_stage]
            self.win.config["live"].update({
                "hits": [vars(h) for h in snap.live_hits], "bhop_ms": snap.bhop_ms or 0,
                "rate_hz": p.rate_wired_hz if snap.wired else p.rate_wireless_hz,
                "dpi": [st.x, st.y, st.lod or 2]})
            storage.update_config({"live": {key: self.win.config["live"][key]
                                                   for key in ("hits", "bhop_ms", "rate_hz", "dpi")}})

        def job(s):
            s.set_mode(mode)
            if mode == HOST_MODE:
                s.reapply_live(self.win.config["live"])
            s.refresh()
        self.win.run(job, lambda _r: self.win.toast("Host mode: settings are live" if mode == HOST_MODE
                                                    else "Onboard memory in control"))

    # ---------------- rows
    def _clear_rows(self):
        for r in self.rows:
            self.list_group.remove(r)
        self.rows = []
        for r in self.backup_rows:
            self.backup_group.remove(r)
        self.backup_rows = []

    def _profile_row(self, snap, entry):
        prof = snap.profiles.get(entry.sector)
        title = prof.display_name if prof else f"Slot {entry.sector}"
        row = Adw.ActionRow(title=GLib.markup_escape_text(title))
        active = entry.sector == snap.active_sector
        bits = [f"Slot {entry.sector}"]
        if prof:
            stage = prof.stages[prof.default_stage]
            bits.append(f"{stage.x} DPI · {prof.rate_wireless_hz} Hz · {hits_codes.encode(*prof.hits)}")
        row.set_subtitle(GLib.markup_escape_text("  ·  ".join(bits)))
        icon = Gtk.Image(icon_name="starred-symbolic" if active else "non-starred-symbolic",
                         tooltip_text="Active profile" if active else "")
        if active:
            icon.add_css_class("accent")
        row.add_prefix(icon)
        sw = Gtk.Switch(active=entry.enabled, valign=Gtk.Align.CENTER, tooltip_text="Enabled in the profile cycle")
        sw.connect("state-set", lambda _s, state, sec=entry.sector: self._enable(sec, state))
        row.add_suffix(sw)

        menu = Gio.Menu()
        group = Gio.SimpleActionGroup()

        def act(name, label, cb):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda *_: cb())
            group.add_action(a)
            menu.append(label, f"p.{name}")
        sec = entry.sector
        if not active:
            act("activate", "Activate", lambda: self.win.run(lambda s: s.activate_profile(sec),
                                                            lambda _r: self.win.toast("Profile activated")))
        act("edit", "Edit", lambda: self._edit(sec))
        act("rename", "Rename…", lambda: self._rename(sec))
        copy_menu = Gio.Menu()
        for other in snap.directory:
            if other.sector != sec:
                name = f"copy{other.sector}"
                a = Gio.SimpleAction.new(name, None)
                a.connect("activate", lambda *_a, dst=other.sector: self._copy(sec, dst))
                group.add_action(a)
                copy_menu.append(f"Slot {other.sector}", f"p.{name}")
        menu.append_submenu("Copy to", copy_menu)
        act("reset", "Reset to factory…", lambda: self._confirm(
            "Reset profile to factory?", "This replaces the profile with the factory default (a backup is kept).",
            "Reset", lambda: self.win.run(lambda s: s.factory_reset_profile(sec),
                                          lambda _r: self.win.toast("Profile reset"))))
        mb = Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu, valign=Gtk.Align.CENTER,
                            css_classes=["flat"])
        mb.insert_action_group("p", group)
        row.add_suffix(mb)
        return row

    def _enable(self, sector, state):
        if self.loading:
            return False
        self.win.run(lambda s: s.set_profile_enabled(sector, state),
                     error=lambda exc: (self.win.toast(str(exc)), self.load(self.win.snapshot, self.win.edit)))
        return False

    def _edit(self, sector):
        if self.win.is_dirty():
            self.win.toast("Save or discard your changes first")
            return
        sectors = self.win._profile_sectors
        if sector in sectors:
            self.win.profile_dropdown.set_selected(sectors.index(sector))
            self.win.goto("sensor")

    def _copy(self, src, dst):
        self._confirm(f"Overwrite slot {dst}?", f"Slot {dst} will become a copy of slot {src} (a backup is kept).",
                      "Overwrite", lambda: self.win.run(lambda s: s.copy_profile(src, dst),
                                                        lambda _r: self.win.toast("Profile copied")))

    def _rename(self, sector):
        prof = self.win.snapshot.profiles.get(sector)
        dlg = Adw.AlertDialog(heading="Rename profile", body="Up to 23 characters, stored on the mouse.")
        entry = Gtk.Entry(text=prof.display_name if prof else "", max_length=23, activates_default=True)
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("ok", "Rename")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("ok")

        def resp(_d, r):
            name = entry.get_text().strip()
            if r != "ok" or not name:
                return
            if sector == self.win.editing_sector and self.win.is_dirty():
                self.win.edit.name = name
                self.win.changed()
                self.win.toast("Name changed — save to apply")
                return
            self.win.run(lambda s: s.rename_profile(sector, name), lambda _r: self.win.toast("Renamed"))
        dlg.connect("response", resp)
        dlg.present(self.win)

    def _confirm(self, heading, body, label, cb):
        dlg = Adw.AlertDialog(heading=heading, body=body)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("ok", label)
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.connect("response", lambda _d, r: cb() if r == "ok" else None)
        dlg.present(self.win)

    # ---------------- import / export
    def _export(self):
        e = self.win.edit
        if not e:
            return
        fd = Gtk.FileDialog(title="Export profile", initial_name=f"{e.display_name}.superstrike.json")

        def done(d, res):
            try:
                f = d.save_finish(res)
            except GLib.Error:
                return
            data = {"format": "ghub-linuxported/profile/1", "device": "PRO X2 SUPERSTRIKE",
                    "hits_code": hits_codes.encode(*e.hits), "exported": time.strftime("%Y-%m-%d %H:%M"),
                    "profile": e.to_json()}
            Path(f.get_path()).write_text(json.dumps(data, indent=2))
            self.win.toast(f"Exported to {f.get_basename()}")
        fd.save(self.win.get_root(), None, done)

    def _import(self):
        fd = Gtk.FileDialog(title="Import profile")
        filt = Gtk.FileFilter(name="Profiles (*.json)")
        filt.add_pattern("*.json")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(filt)
        fd.set_filters(store)

        def done(d, res):
            try:
                f = d.open_finish(res)
            except GLib.Error:
                return
            try:
                data = json.loads(Path(f.get_path()).read_text())
                if not isinstance(data, dict):
                    raise ValueError("profile must be a JSON object")
                prof = data.get("profile", data)
                self.win.edit.apply_json(prof)
            except (ValueError, KeyError, TypeError, OSError) as exc:
                self.win.toast(f"Not a valid profile file: {exc}")
                return
            self.win.reload_pages()
            self.win.changed()
            self.win.toast("Imported — review and save to the mouse")
        fd.open(self.win.get_root(), None, done)

    # ---------------- backups
    def _restore(self, b):
        sector = b["sector"]
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(b.get("time", 0)))

        def go():
            raw = bytes.fromhex(b["raw"])
            self.win.run(lambda s: s.restore_backup(sector, raw), lambda _r: self.win.toast("Backup restored"))
        what = "the profile directory" if sector == 0 else f"slot {sector}"
        self._confirm("Restore backup?", f"Writes the {when} copy back to {what}.", "Restore", go)

    def fill(self, snap, edit):
        self._clear_rows()
        set_toggle_silent(self.mode_toggle, 1 if snap.mode == HOST_MODE else 0)
        self.pristine.set_visible(not snap.directory)
        for entry in snap.directory:
            row = self._profile_row(snap, entry)
            self.list_group.add(row)
            self.rows.append(row)
        unit = snap.identity.unit_id if snap.identity else None
        backups = [b for b in storage.list_backups() if not unit or b.get("unit_id") in (unit, "")][:8]
        if not backups:
            r = Adw.ActionRow(title="No backups yet", subtitle="One is made before the first write.")
            self.backup_group.add(r)
            self.backup_rows.append(r)
        for b in backups:
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(b.get("time", 0)))
            what = "Directory" if b["sector"] == 0 else f"Slot {b['sector']}"
            r = Adw.ActionRow(title=f"{what} · {when}", subtitle=b.get("reason", ""))
            if b["sector"] < 0x100:
                btn = Gtk.Button(label="Restore", valign=Gtk.Align.CENTER, css_classes=["pill"])
                btn.connect("clicked", lambda _b, b=b: self._restore(b))
                r.add_suffix(btn)
            self.backup_group.add(r)
            self.backup_rows.append(r)
