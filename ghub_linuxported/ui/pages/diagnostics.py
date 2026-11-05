from __future__ import annotations

import threading
import time

from gi.repository import Adw, Gdk, GLib, Gtk

from .base import Page
from ..widgets import MouseDiagram
from ...diagnostics import measure_report_rate
from ...hidpp.mouse import FEATURE_NAMES

# GTK button number -> diagram index (L, R, M, Back, Forward)
GTK_BUTTONS = {1: 0, 3: 1, 2: 2, 8: 3, 9: 4}
NAMES = ["Left", "Right", "Middle", "Back", "Forward"]


class ClickTester:
    def __init__(self):
        self.counts = [0] * 5
        self.down_at = [0.0] * 5
        self.hold = [0.0] * 5
        self.last_up = [0.0] * 5
        self.min_gap = [None] * 5
        self.recent: list[float] = []
        self.scroll_up = self.scroll_down = 0

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["card", "click-pad"])
        title = Gtk.Label(label="Click, hold and scroll inside this area", css_classes=["heading"], margin_top=12)
        self.box.append(title)
        inner = Gtk.Box(spacing=24, margin_start=16, margin_end=16, margin_bottom=16)
        self.diagram = MouseDiagram(selectable=False, height=220)
        self.diagram.set_hexpand(False)
        inner.append(self.diagram)
        grid = Gtk.Grid(column_spacing=18, row_spacing=6, valign=Gtk.Align.CENTER, hexpand=True)
        for c, h in enumerate(("Button", "Clicks", "Last hold", "Fastest re-click")):
            grid.attach(Gtk.Label(label=h, xalign=0, css_classes=["caption-heading", "dim-label"]), c, 0, 1, 1)
        self.cells = []
        for r, n in enumerate(NAMES):
            row = [Gtk.Label(label=n, xalign=0)] + [Gtk.Label(label="—", xalign=0, css_classes=["numeric"])
                                                   for _ in range(3)]
            for c, w in enumerate(row):
                grid.attach(w, c, r + 1, 1, 1)
            self.cells.append(row)
        self.cps = Gtk.Label(label="0 CPS", css_classes=["title-2", "numeric"], xalign=0)
        self.scroll = Gtk.Label(label="Scroll ↑0 ↓0", xalign=0, css_classes=["dim-label"])
        grid.attach(self.cps, 0, 7, 2, 1)
        grid.attach(self.scroll, 2, 7, 2, 1)
        reset = Gtk.Button(label="Reset", halign=Gtk.Align.START, css_classes=["pill"])
        reset.connect("clicked", lambda *_: self.reset())
        grid.attach(reset, 0, 8, 1, 1)
        inner.append(grid)
        self.box.append(inner)

        click = Gtk.GestureClick(button=0)
        click.connect("pressed", self._pressed)
        click.connect("released", self._released)
        self.box.add_controller(click)
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._scrolled)
        self.box.add_controller(scroll)
        GLib.timeout_add(250, self._tick)

    def reset(self):
        self.__init_counts()
        self._update()

    def __init_counts(self):
        self.counts, self.hold, self.min_gap = [0] * 5, [0.0] * 5, [None] * 5
        self.recent, self.scroll_up, self.scroll_down = [], 0, 0

    def _pressed(self, g, _n, _x, _y):
        i = GTK_BUTTONS.get(g.get_current_button())
        if i is None:
            return
        now = time.monotonic()
        if self.last_up[i]:
            gap = (now - self.last_up[i]) * 1000
            if self.min_gap[i] is None or gap < self.min_gap[i]:
                self.min_gap[i] = gap
        self.down_at[i] = now
        self.counts[i] += 1
        self.recent.append(now)
        self.diagram.flash(i, True)
        self._update()

    def _released(self, g, _n, _x, _y):
        i = GTK_BUTTONS.get(g.get_current_button())
        if i is None:
            return
        now = time.monotonic()
        self.hold[i] = (now - self.down_at[i]) * 1000
        self.last_up[i] = now
        self.diagram.flash(i, False)
        self._update()

    def _scrolled(self, _c, _dx, dy):
        if dy < 0:
            self.scroll_up += 1
        elif dy > 0:
            self.scroll_down += 1
        self.scroll.set_label(f"Scroll ↑{self.scroll_up} ↓{self.scroll_down}")
        return True

    def _tick(self):
        now = time.monotonic()
        self.recent = [t for t in self.recent if now - t < 1.0]
        self.cps.set_label(f"{len(self.recent)} CPS")
        return True

    def _update(self):
        for i, row in enumerate(self.cells):
            row[1].set_label(str(self.counts[i]))
            row[2].set_label(f"{self.hold[i]:.0f} ms" if self.hold[i] else "—")
            row[3].set_label(f"{self.min_gap[i]:.0f} ms" if self.min_gap[i] is not None else "—")


class DiagnosticsPage(Page):
    key, title, icon = "diagnostics", "Diagnostics", "utilities-terminal-symbolic"
    subtitle = "Polling rate, click tester, raw HID++"

    def build(self):
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=1000, margin_top=24, margin_bottom=24, margin_start=16, margin_end=16)
        scroller.set_child(clamp)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        clamp.set_child(col)

        rate = Adw.PreferencesGroup(title="Real polling rate",
                                    description="Counts the reports the mouse actually sends. The firmware's own "
                                                "rate value can be stale, so this is the number to trust. "
                                                "Keep moving the mouse while it measures.")
        card = Gtk.Box(spacing=24, css_classes=["card"])
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_start=20, margin_top=16,
                       margin_bottom=16, hexpand=True)
        self.rate_value = Gtk.Label(label="— Hz", xalign=0, css_classes=["display", "numeric"])
        self.rate_detail = Gtk.Label(label="Press Measure, then move the mouse in circles.", xalign=0,
                                     css_classes=["dim-label"], wrap=True)
        self.rate_progress = Gtk.ProgressBar(visible=False, margin_top=6)
        left.append(self.rate_value)
        left.append(self.rate_detail)
        left.append(self.rate_progress)
        card.append(left)
        self.measure_btn = Gtk.Button(label="Measure", css_classes=["suggested-action", "pill"],
                                      valign=Gtk.Align.CENTER, margin_end=20)
        self.measure_btn.connect("clicked", self._measure)
        card.append(self.measure_btn)
        rate.add(card)
        col.append(rate)

        clicks = Adw.PreferencesGroup(title="Click tester",
                                      description="Feel your HITS settings: hold time and fastest re-click show "
                                                  "the effect of actuation and rapid trigger.")
        self.tester = ClickTester()
        clicks.add(self.tester.box)
        col.append(clicks)

        self.features_group = Adw.PreferencesGroup(title="HID++ features")
        self.features_row = Adw.ExpanderRow(title="Feature table", subtitle="Resolved at connect")
        self.features_group.add(self.features_row)
        self._feature_rows = []
        col.append(self.features_group)

        console = Adw.PreferencesGroup(title="Advanced")
        self.console_row = Adw.ExpanderRow(
            title="Raw HID++ console",
            subtitle="Send a single request to the device. For protocol research only.")
        self.console_row.add_prefix(Gtk.Image(icon_name="utilities-terminal-symbolic"))
        console.add(self.console_row)
        warn = Adw.ActionRow(title="Careful", subtitle="Setter functions change the device immediately. "
                                                       "Never use onboard-profile write functions (0x8100 fn 6–8).")
        warn.add_prefix(Gtk.Image(icon_name="dialog-warning-symbolic"))
        self.console_row.add_row(warn)
        self.c_feature = Adw.ComboRow(title="Feature")
        self.console_row.add_row(self.c_feature)
        self.c_fn = Adw.SpinRow.new_with_range(0, 15, 1)
        self.c_fn.set_title("Function")
        self.console_row.add_row(self.c_fn)
        self.c_params = Adw.EntryRow(title="Parameters (hex, e.g. 00 01)")
        self.c_params.connect("entry-activated", self._send)
        self.console_row.add_row(self.c_params)
        send = Adw.ButtonRow(title="Send request", start_icon_name="mail-send-symbolic")
        send.connect("activated", self._send)
        self.console_row.add_row(send)

        self.log_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, visible=False, margin_top=12)
        head = Gtk.Box()
        head.append(Gtk.Label(label="Responses", xalign=0, hexpand=True, css_classes=["heading"]))
        clear = Gtk.Button(label="Clear", css_classes=["flat"])
        clear.connect("clicked", lambda *_: (self.log.get_buffer().set_text(""), self.log_box.set_visible(False)))
        head.append(clear)
        self.log_box.append(head)
        self.log = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.CHAR, cursor_visible=False,
                                css_classes=["card", "console"], top_margin=10, bottom_margin=10,
                                left_margin=12, right_margin=12)
        self.log.set_size_request(-1, 120)
        self.log_box.append(self.log)
        console.add(self.log_box)
        col.append(console)
        self._feature_choices = []
        return scroller

    # ---- rate
    def _measure(self, *_):
        ident = self.win.snapshot.identity
        if not ident or not ident.node:
            self.win.toast("Mouse not connected")
            return
        self.measure_btn.set_sensitive(False)
        self.rate_progress.set_visible(True)
        self.rate_value.set_label("…")
        node = ident.node

        def progress(frac, n):
            GLib.idle_add(lambda: (self.rate_progress.set_fraction(frac),
                                   self.rate_detail.set_label(f"{n} reports received…")) and False)

        def work():
            try:
                res = measure_report_rate(node, 3.0, progress)
                GLib.idle_add(self._rate_done, res, None)
            except OSError as exc:
                GLib.idle_add(self._rate_done, None, exc)
        threading.Thread(target=work, daemon=True).start()

    def _rate_done(self, res, exc):
        self.measure_btn.set_sensitive(True)
        self.rate_progress.set_visible(False)
        if exc or not res or not res.hz:
            self.rate_value.set_label("— Hz")
            self.rate_detail.set_label(str(exc) if exc else "Not enough movement. Keep the mouse moving and retry.")
            return False
        snap = self.win.snapshot
        p = snap.active_profile
        configured = (p.rate_wired_hz if snap.wired else p.rate_wireless_hz) if p else None
        self.rate_value.set_label(f"{res.nominal:,} Hz")
        self.rate_detail.set_label(
            f"{res.hz:,.0f} Hz measured from {res.reports:,} reports · jitter {res.jitter_us:.0f} µs"
            + (f" · profile setting {configured:,} Hz" if configured else ""))
        return False

    # ---- console
    def _send(self, *_):
        i = self.c_feature.get_selected()
        if i >= len(self._feature_choices):
            self.win.toast("Pick a feature first")
            return
        idx, fid = self._feature_choices[i]
        fn = int(self.c_fn.get_value())
        try:
            params = bytes.fromhex(self.c_params.get_text().replace(",", " ").replace("0x", ""))
            if len(params) > 16:
                raise ValueError("at most 16 bytes")
        except ValueError as exc:
            self.win.toast(f"Parameters: {exc}")
            return
        self._log(f"→ 0x{fid:04X} {FEATURE_NAMES.get(fid, '')} · fn {fn} · [{params.hex(' ') or '—'}]")
        self.win.run(lambda s: s.raw_call(idx, fn, params), lambda r: self._log(f"← {r.hex(' ')}"),
                     error=lambda e: self._log(f"✕ {e}"))

    def _log(self, line):
        self.log_box.set_visible(True)
        buf = self.log.get_buffer()
        buf.insert(buf.get_end_iter(), line + "\n")
        self.log.scroll_to_iter(buf.get_end_iter(), 0, False, 0, 0)

    def fill(self, snap, edit):
        for r in self._feature_rows:
            self.features_row.remove(r)
        self._feature_rows = []
        for idx, fid, flags, ver in snap.features:
            r = Adw.ActionRow(title=f"0x{fid:04X}  {FEATURE_NAMES.get(fid, 'Unknown / internal')}",
                              subtitle=f"index 0x{idx:02X} · version {ver}" + (" · hidden" if flags & 0x40 else ""))
            self.features_row.add_row(r)
            self._feature_rows.append(r)
        self._feature_choices = [(idx, fid) for idx, fid, *_ in snap.features]
        self.c_feature.set_model(Gtk.StringList.new(
            [f"0x{fid:04X}  {FEATURE_NAMES.get(fid, 'Unknown')}" for _i, fid in self._feature_choices]))
        self.features_row.set_subtitle(f"{len(snap.features)} features")
