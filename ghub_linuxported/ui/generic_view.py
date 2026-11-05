"""Fallback view for Logitech HID++ devices without a dedicated page."""
from __future__ import annotations

from gi.repository import Adw, GLib, Gtk

from ..worker import DeviceWorker
from ..hidpp.mouse import Mouse, FEATURE_NAMES, F_UNIFIED_BATTERY


class GenericWorker(DeviceWorker):
    def __init__(self, dispatch, found):
        super().__init__(dispatch, poll_s=60)
        self.found = found
        self.info = {}

    def open_device(self):
        return Mouse.open(0x0A, node=self.found.path, dev_index=self.found.dev_index)

    def refresh(self):
        m = self.dev
        self.info = {"identity": m.identity(), "features": m.list_features(),
                     "battery": m.battery() if m.has(F_UNIFIED_BATTERY) else None}
        self._emit("info", self.info)


class GenericView(Adw.BreakpointBin):
    def __init__(self, shell, found):
        super().__init__()
        self.set_size_request(360, 420)
        self.shell = shell
        tb = Adw.ToolbarView()
        tb.add_top_bar(Adw.HeaderBar(title_widget=Adw.WindowTitle(title=found.title, subtitle=found.kind.title())))
        self.page = Adw.PreferencesPage()
        tb.set_content(self.page)
        self.set_child(tb)
        self.info_group = Adw.PreferencesGroup(title="Device")
        self.page.add(self.info_group)
        self.feat_group = Adw.PreferencesGroup(title="HID++ features",
                                               description="This device has no dedicated settings page yet.")
        self.page.add(self.feat_group)
        self.worker = GenericWorker(lambda fn, *a: GLib.idle_add(lambda: fn(*a) and False), found)
        self.worker.on("info", self._fill)
        self.worker.start()

    def _fill(self, info):
        ident = info["identity"]
        rows = [("Name", ident.name), ("Connection", ident.connection), ("Unit ID", ident.unit_id or "—"),
                ("Model", f"{ident.model_id} {ident.model_string}".strip() or "—"),
                ("Firmware", "\n".join(ident.firmware) or "—"), ("HID++", ident.protocol)]
        if info["battery"]:
            rows.insert(1, ("Battery", f"{info['battery'].percent}% · {info['battery'].label}"))
        for t, v in rows:
            self.info_group.add(Adw.ActionRow(title=t, subtitle=v, css_classes=["property"], subtitle_selectable=True))
        for idx, fid, _flags, ver in info["features"]:
            self.feat_group.add(Adw.ActionRow(title=f"0x{fid:04X}  {FEATURE_NAMES.get(fid, 'Unknown / internal')}",
                                              subtitle=f"index 0x{idx:02X} · version {ver}"))

    def close(self):
        self.worker.stop()
