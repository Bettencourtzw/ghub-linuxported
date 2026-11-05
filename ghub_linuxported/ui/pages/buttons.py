from __future__ import annotations

from gi.repository import Adw, Gdk, Gtk

from .base import Page
from ..widgets import MouseDiagram, toggle_group
from ...model.buttons import (ButtonAction, PHYSICAL_BUTTONS, MOUSE_BUTTONS, CONSUMER_KEYS, FUNCTIONS,
                              KIND_DEFAULT, KIND_DISABLED, KIND_MOUSE, KIND_KEY, KIND_CONSUMER, KIND_FUNCTION,
                              KIND_RAW, EVDEV_TO_HID, modifiers_label, key_name)

KINDS = [(KIND_DEFAULT, "Default (factory)"), (KIND_DISABLED, "Disabled"), (KIND_MOUSE, "Mouse button"),
         (KIND_KEY, "Keyboard key / shortcut"), (KIND_CONSUMER, "Media key"), (KIND_FUNCTION, "Mouse function")]
GDK_MODS = [(Gdk.ModifierType.CONTROL_MASK, 0x01), (Gdk.ModifierType.SHIFT_MASK, 0x02),
            (Gdk.ModifierType.ALT_MASK, 0x04), (Gdk.ModifierType.SUPER_MASK, 0x08)]


class ButtonsPage(Page):
    key, title, icon = "buttons", "Buttons", "input-dialpad-symbolic"
    subtitle = "Remap buttons (stored in the profile)"

    def build(self):
        self.selected = 0
        self.layer = 0  # 0 normal, 1 G-Shift
        self._capturing = None
        outer = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=1100, margin_top=24, margin_bottom=24, margin_start=16, margin_end=16)
        outer.set_child(clamp)
        box = Gtk.Box(spacing=24)
        self.win.responsive(box, "orientation", Gtk.Orientation.VERTICAL)
        clamp.set_child(box)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["card"], hexpand=True,
                       valign=Gtk.Align.START)
        self.layer_toggle = toggle_group(["Normal", "G-Shift layer"], self._on_layer)
        self.layer_toggle.set_halign(Gtk.Align.CENTER)
        self.layer_toggle.set_margin_top(16)
        left.append(self.layer_toggle)
        self.diagram = MouseDiagram(selectable=True, labels=[""] * 5, height=430)
        self.diagram.on_select = self.select
        self.diagram.set_selected(0)
        self.diagram.set_margin_bottom(16)
        left.append(self.diagram)
        box.append(left)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24, width_request=340)
        box.append(right)
        self.list_group = Adw.PreferencesGroup(title="Assignments",
                                               description="Click a button on the mouse or in this list.")
        self.list_rows = []
        for i, name in enumerate(PHYSICAL_BUTTONS):
            r = Adw.ActionRow(title=name, activatable=True)
            r.connect("activated", lambda _r, i=i: self.select(i))
            r.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            self.list_rows.append(r)
            self.list_group.add(r)
        right.append(self.list_group)

        self.editor = Adw.PreferencesGroup(title="Left click")
        self.kind = Adw.ComboRow(title="Action", model=Gtk.StringList.new([k[1] for k in KINDS]))
        self.kind.connect("notify::selected", self._on_kind)
        self.editor.add(self.kind)
        self.mouse_row = Adw.ComboRow(title="Mouse button", model=Gtk.StringList.new([m[0] for m in MOUSE_BUTTONS]))
        self.mouse_row.connect("notify::selected", lambda *_: self._commit())
        self.media_row = Adw.ComboRow(title="Media key", model=Gtk.StringList.new([m[0] for m in CONSUMER_KEYS]))
        self.media_row.connect("notify::selected", lambda *_: self._commit())
        self.func_row = Adw.ComboRow(title="Function", model=Gtk.StringList.new([f[0] for f in FUNCTIONS]))
        self.func_row.connect("notify::selected", lambda *_: self._commit())
        self.key_row = Adw.ActionRow(title="Shortcut", subtitle="Not set")
        self.capture_btn = Gtk.Button(label="Record…", valign=Gtk.Align.CENTER, css_classes=["pill"])
        self.capture_btn.connect("clicked", self._start_capture)
        self.key_row.add_suffix(self.capture_btn)
        self.raw_row = Adw.ActionRow(title="Custom action", subtitle="")
        for w in (self.mouse_row, self.key_row, self.media_row, self.func_row, self.raw_row):
            self.editor.add(w)
        reset = Adw.ButtonRow(title="Reset this button to factory")
        reset.connect("activated", lambda *_: self._set_action(ButtonAction.factory(self.selected)))
        self.editor.add(reset)
        right.append(self.editor)
        right.append(Gtk.Label(
            label="Remapping is stored in the onboard profile and works on any computer. Save to apply.",
            wrap=True, xalign=0, css_classes=["caption", "dim-label"]))

        keyc = Gtk.EventControllerKey()
        keyc.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keyc.connect("key-pressed", self._on_key)
        self.win.add_controller(keyc)
        return outer

    # ---- model access
    def _actions(self):
        e = self.win.edit
        return (e.buttons if self.layer == 0 else e.shift_buttons) if e else None

    def _on_layer(self, i):
        self.layer = i
        self._refresh()

    def select(self, i):
        self.selected = i
        self.diagram.set_selected(i)
        self._refresh()

    def _set_action(self, action):
        acts = self._actions()
        if acts is None:
            return
        if self.layer == 0 and self.selected == 0 and action.encode() not in (b"\xff\xff\xff\xff",) \
                and not (action.kind == KIND_MOUSE and action.code & 0x0001):
            if not any(a.kind == KIND_MOUSE and a.code & 1 for a in acts[1:]):
                self.win.toast("Careful: no button sends Left click now. Keep one before saving.", timeout=6)
        acts[self.selected] = action
        self._refresh()
        self.win.changed()

    def _commit(self):
        if self.loading:
            return
        kind = KINDS[self.kind.get_selected()][0]
        if kind == KIND_MOUSE:
            self._set_action(ButtonAction.mouse(MOUSE_BUTTONS[self.mouse_row.get_selected()][1]))
        elif kind == KIND_CONSUMER:
            code = CONSUMER_KEYS[self.media_row.get_selected()][1]
            self._set_action(ButtonAction.decode(bytes([0x80, 0x03, code >> 8, code & 0xFF])))
        elif kind == KIND_FUNCTION:
            self._set_action(ButtonAction(KIND_FUNCTION, FUNCTIONS[self.func_row.get_selected()][1]))

    def _on_kind(self, row, _p):
        if self.loading:
            return
        kind = KINDS[row.get_selected()][0]
        if kind == KIND_DEFAULT:
            self._set_action(ButtonAction(KIND_DEFAULT))
        elif kind == KIND_DISABLED:
            self._set_action(ButtonAction(KIND_DISABLED))
        elif kind == KIND_KEY:
            self._show_rows(KIND_KEY)
            self._start_capture()
        else:
            self._commit()

    # ---- key capture
    def _start_capture(self, *_):
        self._capturing = True
        self.capture_btn.set_label("Press keys… (Esc cancels)")
        self.capture_btn.add_css_class("suggested-action")

    def _stop_capture(self):
        self._capturing = None
        self.capture_btn.set_label("Record…")
        self.capture_btn.remove_css_class("suggested-action")

    def _on_key(self, _c, keyval, keycode, state):
        if not self._capturing:
            return False
        evdev = keycode - 8
        if keyval == Gdk.KEY_Escape and not state & Gtk.accelerator_get_default_mod_mask():
            self._stop_capture()
            return True
        if keyval in (Gdk.KEY_Control_L, Gdk.KEY_Control_R, Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Alt_L,
                      Gdk.KEY_Alt_R, Gdk.KEY_Super_L, Gdk.KEY_Super_R, Gdk.KEY_ISO_Level3_Shift, Gdk.KEY_Meta_L):
            return True  # wait for the real key
        usage = EVDEV_TO_HID.get(evdev)
        if usage is None:
            self.win.toast("That key can't be assigned to a mouse button")
            return True
        mods = 0
        for mask, bit in GDK_MODS:
            if state & mask:
                mods |= bit
        self._stop_capture()
        self._set_action(ButtonAction(KIND_KEY, usage, mods))
        return True

    # ---- view
    def _show_rows(self, kind):
        self.mouse_row.set_visible(kind == KIND_MOUSE)
        self.key_row.set_visible(kind == KIND_KEY)
        self.media_row.set_visible(kind == KIND_CONSUMER)
        self.func_row.set_visible(kind == KIND_FUNCTION)
        self.raw_row.set_visible(kind == KIND_RAW)

    def _refresh(self):
        acts = self._actions()
        if acts is None:
            return
        self.loading = True
        try:
            labels = [a.describe(i) for i, a in enumerate(acts)]
            self.diagram.set_labels(labels)
            for r, lab in zip(self.list_rows, labels):
                r.set_subtitle(lab)
            a = acts[self.selected]
            prefix = "G-Shift · " if self.layer else ""
            self.editor.set_title(prefix + PHYSICAL_BUTTONS[self.selected])
            kinds = [k[0] for k in KINDS]
            self.kind.set_selected(kinds.index(a.kind) if a.kind in kinds else 0)
            self._show_rows(a.kind)
            if a.kind == KIND_MOUSE:
                codes = [m[1] for m in MOUSE_BUTTONS]
                if a.code in codes:
                    self.mouse_row.set_selected(codes.index(a.code))
            elif a.kind == KIND_KEY:
                mods = modifiers_label(a.modifiers)
                self.key_row.set_subtitle((mods + "+" if mods else "") + key_name(a.code))
            elif a.kind == KIND_CONSUMER:
                codes = [m[1] for m in CONSUMER_KEYS]
                if a.code in codes:
                    self.media_row.set_selected(codes.index(a.code))
            elif a.kind == KIND_FUNCTION:
                codes = [f[1] for f in FUNCTIONS]
                if a.code in codes:
                    self.func_row.set_selected(codes.index(a.code))
            elif a.kind == KIND_RAW:
                self.raw_row.set_subtitle(a.describe())
        finally:
            self.loading = False

    def fill(self, snap, edit):
        self._refresh()
