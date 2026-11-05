"""StatusNotifierItem over Gio; the context menu is served by libdbusmenu-glib
(the same library tray hosts such as Waybar use to parse it).
"""
from __future__ import annotations

import os

import gi

gi.require_version("Dbusmenu", "0.4")
from gi.repository import Dbusmenu, Gio, GLib  # noqa: E402

SNI_XML = """
<node>
 <interface name="org.kde.StatusNotifierItem">
  <property name="Category" type="s" access="read"/>
  <property name="Id" type="s" access="read"/>
  <property name="Title" type="s" access="read"/>
  <property name="Status" type="s" access="read"/>
  <property name="IconName" type="s" access="read"/>
  <property name="IconThemePath" type="s" access="read"/>
  <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
  <property name="ItemIsMenu" type="b" access="read"/>
  <property name="Menu" type="o" access="read"/>
  <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
  <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
  <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
  <method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
  <signal name="NewIcon"/><signal name="NewToolTip"/><signal name="NewStatus"><arg type="s"/></signal>
  <signal name="NewTitle"/>
 </interface>
</node>"""

class MenuItem:
    def __init__(self, label="", callback=None, enabled=True, separator=False, children=None,
                 radio=None, icon=None):
        self.label, self.callback, self.enabled = label, callback, enabled
        self.separator, self.children, self.radio, self.icon = separator, children or [], radio, icon
        self.id = 0

    def build(self) -> "Dbusmenu.Menuitem":
        mi = Dbusmenu.Menuitem.new()
        if self.separator:
            mi.property_set(Dbusmenu.MENUITEM_PROP_TYPE, Dbusmenu.CLIENT_TYPES_SEPARATOR)
            return mi
        mi.property_set(Dbusmenu.MENUITEM_PROP_LABEL, self.label)
        mi.property_set_bool(Dbusmenu.MENUITEM_PROP_ENABLED, self.enabled)
        if self.icon:
            mi.property_set(Dbusmenu.MENUITEM_PROP_ICON_NAME, self.icon)
        if self.radio is not None:
            mi.property_set(Dbusmenu.MENUITEM_PROP_TOGGLE_TYPE, Dbusmenu.MENUITEM_TOGGLE_RADIO)
            mi.property_set_int(Dbusmenu.MENUITEM_PROP_TOGGLE_STATE,
                                Dbusmenu.MENUITEM_TOGGLE_STATE_CHECKED if self.radio
                                else Dbusmenu.MENUITEM_TOGGLE_STATE_UNCHECKED)
        if self.children:
            mi.property_set(Dbusmenu.MENUITEM_PROP_CHILD_DISPLAY, Dbusmenu.MENUITEM_CHILD_DISPLAY_SUBMENU)
            for c in self.children:
                mi.child_append(c.build())
        if self.callback:
            cb = self.callback
            mi.connect("item-activated", lambda *_: GLib.idle_add(lambda: cb() and False))
        return mi


class StatusNotifierItem:
    def __init__(self, app_id: str, title: str, on_activate=None, on_scroll=None, on_menu_open=None):
        self.app_id, self.title = app_id, title
        self.icon = "input-mouse-symbolic"
        self.tooltip = (title, "")
        self.status = "Active"
        self.on_activate, self.on_scroll, self.on_menu_open = on_activate, on_scroll, on_menu_open
        self.menu_server = Dbusmenu.Server.new("/MenuBar")
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        sni = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
        self.bus.register_object("/StatusNotifierItem", sni, self._sni_call, self._sni_get, None)
        Gio.bus_own_name_on_connection(self.bus, self.name, Gio.BusNameOwnerFlags.NONE, None, None)
        self._watch = Gio.bus_watch_name_on_connection(self.bus, "org.kde.StatusNotifierWatcher",
                                                       Gio.BusNameWatcherFlags.NONE, self._register, None)

    def _register(self, *_):
        try:
            self.bus.call_sync("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher",
                               "org.kde.StatusNotifierWatcher", "RegisterStatusNotifierItem",
                               GLib.Variant("(s)", (self.name,)), None, Gio.DBusCallFlags.NONE, 2000, None)
        except GLib.Error as exc:
            print("tray: could not register with the StatusNotifierWatcher:", exc.message)

    # ---------------- public API
    def set_icon(self, icon: str):
        if icon != self.icon:
            self.icon = icon
            self._emit("/StatusNotifierItem", "org.kde.StatusNotifierItem", "NewIcon")

    def set_tooltip(self, title: str, body: str):
        self.tooltip = (title, body)
        self._emit("/StatusNotifierItem", "org.kde.StatusNotifierItem", "NewToolTip")

    def set_status(self, status: str):
        if status != self.status:
            self.status = status
            self._emit("/StatusNotifierItem", "org.kde.StatusNotifierItem", "NewStatus",
                       GLib.Variant("(s)", (status,)))

    def set_menu(self, items: list[MenuItem]):
        root = Dbusmenu.Menuitem.new()
        for it in items:
            root.child_append(it.build())
        root.connect("about-to-show", lambda *_: self.on_menu_open and self.on_menu_open() or False)
        self.menu_server.set_root(root)

    # ---------------- D-Bus plumbing
    def _emit(self, path, iface, signal, params=None):
        try:
            self.bus.emit_signal(None, path, iface, signal, params)
        except GLib.Error:
            pass

    def _sni_get(self, _conn, _sender, _path, _iface, prop):
        return {
            "Category": GLib.Variant("s", "Hardware"), "Id": GLib.Variant("s", self.app_id),
            "Title": GLib.Variant("s", self.title), "Status": GLib.Variant("s", self.status),
            "IconName": GLib.Variant("s", self.icon), "IconThemePath": GLib.Variant("s", ""),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", ("", [], self.tooltip[0], self.tooltip[1])),
            "ItemIsMenu": GLib.Variant("b", False), "Menu": GLib.Variant("o", "/MenuBar"),
        }.get(prop)

    def _sni_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method in ("Activate", "SecondaryActivate") and self.on_activate:
            self.on_activate()
        elif method == "Scroll" and self.on_scroll:
            delta, orientation = params.unpack()
            if orientation == "vertical":
                self.on_scroll(1 if delta < 0 else -1)
        invocation.return_value(None)


def notify(summary: str, body: str = "", icon: str = "input-mouse-symbolic", urgency: int = 1,
           replaces_id: int = 0) -> int:
    """Desktop notification via org.freedesktop.Notifications (mako, dunst, swaync...)."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        r = bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                          "org.freedesktop.Notifications", "Notify",
                          GLib.Variant("(susssasa{sv}i)", ("G HUB Linux Ported", replaces_id, icon, summary, body, [],
                                                           {"urgency": GLib.Variant("y", urgency)}, -1)),
                          GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 2000, None)
        return r.unpack()[0]
    except GLib.Error as exc:
        print("notify failed:", exc.message)
        return 0
