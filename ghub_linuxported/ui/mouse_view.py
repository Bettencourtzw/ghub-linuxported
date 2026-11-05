"""Mouse device view (PRO X2 SUPERSTRIKE): sidebar pages, editing profile + save bar."""
from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ..service import DeviceService, Snapshot  # noqa: E402
from ..model.profile import Profile  # noqa: E402
from .. import storage  # noqa: E402

UDEV_RULE = Path(__file__).resolve().parents[2] / "packaging" / "70-ghub-linuxported.rules"
UDEV_CMD = (f"sudo install -m644 '{UDEV_RULE}' /etc/udev/rules.d/ && "
            "sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=hidraw")


class MouseView(Adw.BreakpointBin):
    def __init__(self, shell, found):
        super().__init__()
        self.set_size_request(360, 420)
        self.shell = shell
        self.found = found
        service = DeviceService(dispatch=lambda fn, *a: GLib.idle_add(lambda: fn(*a) and False),
                                node=found.path, dev_index=found.dev_index)
        self.service = service
        self.config = storage.load_config()
        self.snapshot: Snapshot = service.snapshot
        self.edit: Profile | None = None       # working copy of the profile being edited
        self.editing_sector: int | None = None
        self._busy = 0

        from .pages import build_pages
        self.outer = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.set_child(self.outer)
        self.outer.add_named(self._build_status_page(), "status")

        self.split = Adw.NavigationSplitView()
        self.split.set_min_sidebar_width(230)
        self.outer.add_named(self.split, "main")

        # ---- sidebar
        self.sidebar_list = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.sidebar_list.connect("row-activated", self._on_nav)
        side_tb = Adw.ToolbarView()
        side_header = Adw.HeaderBar()
        side_header.set_title_widget(Adw.WindowTitle(title=found.title, subtitle="Mouse"))
        menu = Gio.Menu()
        menu.append("Re-read from mouse", "dev.refresh")
        menu.append("Open backups folder", "dev.backups")
        menu.append("About", "app.about")
        side_header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                            tooltip_text="Menu"))
        side_tb.add_top_bar(side_header)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(self.sidebar_list)
        side_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side_box.append(scroller)
        self.side_battery = Gtk.Label(xalign=0, css_classes=["dim-label", "caption"], margin_start=18,
                                      margin_bottom=12, margin_top=6)
        side_box.append(self.side_battery)
        side_tb.set_content(side_box)
        self.split.set_sidebar(Adw.NavigationPage(title=found.title, child=side_tb))

        # ---- content
        self.content_tb = Adw.ToolbarView()
        header = Adw.HeaderBar(show_back_button=False)
        self.page_title = Adw.WindowTitle(title="Overview")
        header.set_title_widget(self.page_title)
        self.profile_dropdown = Gtk.DropDown(tooltip_text="Profile being edited")
        self.profile_dropdown.connect("notify::selected", self._on_profile_pick)
        self._profile_sectors: list[int] = []
        header.pack_start(self.profile_dropdown)
        self.save_btn = Gtk.Button(label="Save to mouse", css_classes=["suggested-action"], sensitive=False,
                                   tooltip_text="Write changes to the mouse's onboard memory (Ctrl+S)")
        self.save_btn.connect("clicked", lambda *_: self.save())
        header.pack_end(self.save_btn)
        self.spinner = Adw.Spinner(visible=False)
        header.pack_end(self.spinner)
        self.content_tb.add_top_bar(header)
        self.banner = Adw.Banner()
        self.content_tb.add_top_bar(self.banner)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120,
                               hhomogeneous=False, vhomogeneous=False, interpolate_size=False)
        self.content_tb.set_content(self.stack)

        # unsaved-changes bar
        self.save_bar = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP)
        bar = Gtk.ActionBar()
        self.save_bar_label = Gtk.Label(label="Unsaved changes", css_classes=["heading"])
        bar.pack_start(Gtk.Image(icon_name="document-save-symbolic"))
        bar.pack_start(self.save_bar_label)
        discard = Gtk.Button(label="Discard")
        discard.connect("clicked", lambda *_: self.discard())
        save2 = Gtk.Button(label="Save to mouse", css_classes=["suggested-action"])
        save2.connect("clicked", lambda *_: self.save())
        bar.pack_end(save2)
        bar.pack_end(discard)
        self.save_bar.set_child(bar)
        self.content_tb.add_bottom_bar(self.save_bar)
        self.split.set_content(Adw.NavigationPage(title="Overview", child=self.content_tb))

        # Responsive layout. Only one breakpoint is active at a time, so the
        # "collapsed" breakpoint repeats every "narrow" setter (see responsive()).
        self._bp_narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 1150sp"))
        self._bp_collapsed = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 720sp"))
        self._bp_collapsed.add_setter(self.split, "collapsed", True)
        self._bp_collapsed.add_setter(header, "show-back-button", True)

        self.pages = build_pages(self)
        self.add_breakpoint(self._bp_narrow)
        self.add_breakpoint(self._bp_collapsed)
        for page in self.pages:
            self.stack.add_named(page.widget, page.key)
            row = Gtk.ListBoxRow()
            box = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=6)
            box.append(Gtk.Image(icon_name=page.icon))
            box.append(Gtk.Label(label=page.title, xalign=0))
            row.set_child(box)
            row.page_key = page.key
            self.sidebar_list.append(row)
        self.sidebar_list.select_row(self.sidebar_list.get_row_at_index(0))

        self._actions()
        service.on("status", self._on_status)
        service.on("snapshot", self._on_snapshot)
        service.on("battery", self._on_battery)
        self._on_status(service.status, service.status_detail)
        service.start()

    def responsive(self, obj, prop, narrow_value):
        """Set obj.prop to narrow_value when the content area is narrow."""
        self._bp_narrow.add_setter(obj, prop, narrow_value)
        self._bp_collapsed.add_setter(obj, prop, narrow_value)

    # ------------------------------------------------------------ actions
    def _actions(self):
        group = Gio.SimpleActionGroup()
        shortcuts = Gtk.ShortcutController(scope=Gtk.ShortcutScope.MANAGED)

        def add(name, cb, accel=None):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda *_: cb())
            group.add_action(a)
            if accel:
                shortcuts.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string(accel),
                                                        Gtk.NamedAction.new(f"dev.{name}")))
        add("save", self.save, "<Control>s")
        add("refresh", self.refresh, "F5")
        add("backups", lambda: (storage.BACKUP_DIR.mkdir(parents=True, exist_ok=True),
                                Gio.AppInfo.launch_default_for_uri(storage.BACKUP_DIR.as_uri(), None)))
        self.insert_action_group("dev", group)
        self.add_controller(shortcuts)

    def close(self):
        """Called when the view is popped: drop unsaved live tweaks and stop the worker."""
        if self.is_dirty() and self.editing_active and self.service.status == "connected":
            self.live_restore_from(self.snapshot.profiles.get(self.editing_sector))
        self.service.stop()

    # ------------------------------------------------------------ navigation
    def _on_nav(self, _lb, row):
        self.stack.set_visible_child_name(row.page_key)
        page = next(p for p in self.pages if p.key == row.page_key)
        self.page_title.set_title(page.title)
        self.page_title.set_subtitle(page.subtitle)
        self.split.set_show_content(True)

    def goto(self, key):
        for i, page in enumerate(self.pages):
            if page.key == key:
                self.sidebar_list.select_row(self.sidebar_list.get_row_at_index(i))
                self._on_nav(None, self.sidebar_list.get_row_at_index(i))

    # ------------------------------------------------------------ status
    def _build_status_page(self):
        self.status_page = Adw.StatusPage(icon_name="input-mouse-symbolic", title="Looking for your mouse…")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        self.status_spinner = Adw.Spinner(width_request=32, height_request=32)
        box.append(self.status_spinner)
        self.perm_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, visible=False)
        cmd = Gtk.Label(label=UDEV_CMD, selectable=True, wrap=True, max_width_chars=70,
                        css_classes=["monospace", "card"], margin_top=6)
        cmd.set_margin_start(6)
        btns = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        install = Gtk.Button(label="Install access rule", css_classes=["suggested-action", "pill"])
        install.connect("clicked", self._install_udev)
        copyb = Gtk.Button(label="Copy command", css_classes=["pill"])
        copyb.connect("clicked", lambda *_: (self.get_clipboard().set(UDEV_CMD), self.toast("Command copied")))
        btns.append(install)
        btns.append(copyb)
        self.perm_box.append(cmd)
        self.perm_box.append(btns)
        box.append(self.perm_box)
        self.status_page.set_child(box)
        return self.status_page

    def _install_udev(self, *_):
        script = (f"install -m644 '{UDEV_RULE}' /etc/udev/rules.d/ && udevadm control --reload && "
                  "udevadm trigger --subsystem-match=hidraw")
        try:
            proc = subprocess.Popen(["pkexec", "sh", "-c", script])
        except FileNotFoundError:
            self.toast("pkexec is not available — run the command in a terminal")
            return

        def check():
            if proc.poll() is None:
                return True
            self.toast("Access rule installed" if proc.returncode == 0 else "Installation cancelled or failed")
            return False
        GLib.timeout_add(300, check)

    def _on_status(self, status, detail):
        if status == "connected":
            self.outer.set_visible_child_name("main")
            self.banner.set_revealed(False)
            return
        if status == "asleep" and self.snapshot.identity:
            self.banner.set_title(detail or "The mouse is not answering. Move it to wake it.")
            self.banner.set_revealed(True)
            return
        self.outer.set_visible_child_name("status")
        self.perm_box.set_visible(status == "permission")
        self.status_spinner.set_visible(status != "permission")
        if status == "permission":
            self.status_page.set_icon_name("dialog-password-symbolic")
            self.status_page.set_title("Allow access to your mouse")
            self.status_page.set_description(
                "Linux only lets root talk to the mouse's control interface. Install the access "
                "rule once (it grants the logged-in user access to Logitech HID devices), then "
                "this window connects automatically.")
        else:
            self.status_page.set_icon_name("input-mouse-symbolic")
            self.status_page.set_title("Looking for your PRO X2 SUPERSTRIKE…")
            self.status_page.set_description(
                "Plug in the LIGHTSPEED receiver or the USB cable, switch the mouse on and move it to wake it.")

    def _on_battery(self, b):
        if b:
            self.side_battery.set_label(f"{self.snapshot.identity.name if self.snapshot.identity else 'Mouse'}"
                                        f" · {b.percent}% {'⚡' if b.charging else ''}")
        for p in self.pages:
            if hasattr(p, "on_battery"):
                p.on_battery(b)

    def _on_snapshot(self, snap: Snapshot):
        self.snapshot = snap
        # profile dropdown
        self._profile_sectors = list(snap.profiles.keys())
        names = []
        for sec in self._profile_sectors:
            p = snap.profiles[sec]
            tag = " (active)" if sec == snap.active_sector else ""
            names.append(p.display_name + (" — factory" if sec >= 0x100 else "") + tag)
        if self.editing_sector not in snap.profiles or not self.is_dirty():
            if self.editing_sector not in snap.profiles:
                self.editing_sector = snap.active_sector
            self.edit = copy.deepcopy(snap.profiles.get(self.editing_sector))
        self._silent_dropdown = True
        self.profile_dropdown.set_model(Gtk.StringList.new(names))
        if self.editing_sector in self._profile_sectors:
            self.profile_dropdown.set_selected(self._profile_sectors.index(self.editing_sector))
        self._silent_dropdown = False
        self.reload_pages()
        self._update_dirty()

    def _on_profile_pick(self, dd, _p):
        if getattr(self, "_silent_dropdown", False):
            return
        i = dd.get_selected()
        if i >= len(self._profile_sectors):
            return
        sec = self._profile_sectors[i]
        if sec == self.editing_sector:
            return
        if self.is_dirty():
            self.toast("Save or discard your changes before switching profile")
            self._silent_dropdown = True
            dd.set_selected(self._profile_sectors.index(self.editing_sector))
            self._silent_dropdown = False
            return
        self.editing_sector = sec
        self.edit = copy.deepcopy(self.snapshot.profiles[sec])
        self.reload_pages()

    def reload_pages(self):
        for p in self.pages:
            try:
                p.load(self.snapshot, self.edit)
            except Exception as exc:  # keep the UI alive if one page fails
                import traceback
                traceback.print_exc()
                self.toast(f"{p.title}: {exc}")

    # ------------------------------------------------------------ editing
    @property
    def editing_active(self) -> bool:
        return self.editing_sector == self.snapshot.active_sector

    def is_dirty(self) -> bool:
        if not self.edit:
            return False
        base = self.snapshot.profiles.get(self.editing_sector)
        try:
            return base is None or self.edit.serialize()[:-2] != base.raw[:-2]
        except ValueError:
            return True

    def changed(self):
        """Pages call this after editing self.edit."""
        self._update_dirty()

    def _update_dirty(self):
        dirty = self.is_dirty()
        self.save_btn.set_sensitive(dirty and self.service.status == "connected")
        self.save_bar.set_reveal_child(dirty)
        if dirty and self.edit:
            try:
                self.edit.validate()
                self.save_bar_label.set_label(f"Unsaved changes to “{self.edit.display_name}”")
            except ValueError as exc:
                self.save_bar_label.set_label(f"Fix before saving: {exc}")

    def discard(self):
        base = self.snapshot.profiles.get(self.editing_sector)
        self.edit = copy.deepcopy(base)
        self.reload_pages()
        self._update_dirty()
        if self.editing_active:
            self.live_restore_from(base)

    def live_restore_from(self, prof: Profile):
        """Put the live (volatile) HITS / bhop values back to the stored profile."""
        def job(s):
            for i, h in enumerate(prof.hits):
                s.apply_hits(i, h)
            if s.snapshot.bhop_ms is not None:
                s.apply_bhop(prof.bhop_ms)
        self.run(job)

    def save(self):
        if not self.is_dirty() or not self.edit:
            return
        try:
            self.edit.validate()
        except ValueError as exc:
            self.toast(f"Cannot save: {exc}")
            return
        edit = copy.deepcopy(self.edit)

        def done(saved):
            self.editing_sector = saved.sector
            self.edit = copy.deepcopy(self.snapshot.profiles.get(saved.sector, saved))
            self.reload_pages()
            self._update_dirty()
            self.toast(f"Saved “{saved.display_name}” to the mouse (verified)")
        self.run(lambda s: s.save_profile(edit), done, busy="Writing to onboard memory…")

    def refresh(self):
        if self.is_dirty():
            self.toast("Save or discard your changes first")
            return
        self.run(lambda s: s.refresh(), lambda _r: self.toast("Re-read from the mouse"))

    # ------------------------------------------------------------ jobs
    def run(self, job, done=None, busy=None, error=None):
        self._busy += 1
        self.spinner.set_visible(True)

        def finish():
            self._busy -= 1
            self.spinner.set_visible(self._busy > 0)

        def ok(result):
            finish()
            if done:
                done(result)

        def fail(exc):
            finish()
            if error:
                error(exc)
            else:
                self.toast(f"{type(exc).__name__}: {exc}", timeout=6)
        self.service.submit(job, ok, fail)

    def live(self, job):
        """Apply a volatile setting now, but only when editing the active profile."""
        if self.editing_active and self.service.status == "connected":
            self.run(job)

    def toast(self, text, timeout=3):
        self.shell.toast(text, timeout)
