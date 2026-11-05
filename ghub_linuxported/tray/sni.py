"""Minimal StatusNotifierItem + com.canonical.dbusmenu over Gio (no extra libraries).

Works with Waybar's tray, KDE, and any StatusNotifierWatcher host.
"""
from __future__ import annotations

import os

from gi.repository import Gio, GLib

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

MENU_XML = """
<node>
 <interface name="com.canonical.dbusmenu">
  <property name="Version" type="u" access="read"/>
  <property name="TextDirection" type="s" access="read"/>
  <property name="Status" type="s" access="read"/>
  <property name="IconThemePath" type="as" access="read"/>
  <method name="GetLayout">
   <arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/>
   <arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/>
  </method>
  <method name="GetGroupProperties">
   <arg type="ai" direction="in"/><arg type="as" direction="in"/><arg type="a(ia{sv})" direction="out"/>
  </method>
  <method name="GetProperty">
   <arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/>
  </method>
  <method name="Event">
   <arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/>
   <arg type="u" direction="in"/>
  </method>
  <method name="EventGroup">
   <arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/>
  </method>
  <method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
  <method name="AboutToShowGroup">
   <arg type="ai" direction="in"/><arg type="ai" direction="out"/><arg type="ai" direction="out"/>
  </method>
  <signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
  <signal name="ItemsPropertiesUpdated"><arg type="a(ia{sv})"/><arg type="a(ias)"/></signal>
 </interface>
</node>"""


class MenuItem:
    def __init__(self, label="", callback=None, enabled=True, separator=False, children=None,
                 radio=None, icon=None):
        self.label, self.callback, self.enabled = label, callback, enabled
        self.separator, self.children, self.radio, self.icon = separator, children or [], radio, icon
        self.id = 0

    def props(self) -> dict:
        if self.separator:
            return {"type": GLib.Variant("s", "separator")}
        p = {"label": GLib.Variant("s", self.label), "enabled": GLib.Variant("b", self.enabled)}
        if self.icon:
            p["icon-name"] = GLib.Variant("s", self.icon)
        if self.children:
            p["children-display"] = GLib.Variant("s", "submenu")
        if self.radio is not None:
            p["toggle-type"] = GLib.Variant("s", "radio")
            p["toggle-state"] = GLib.Variant("i", 1 if self.radio else 0)
        return p


class StatusNotifierItem:
    def __init__(self, app_id: str, title: str, on_activate=None, on_scroll=None, on_menu_open=None):
        self.app_id, self.title = app_id, title
        self.icon = "input-mouse-symbolic"
        self.tooltip = (title, "")
        self.status = "Active"
        self.on_activate, self.on_scroll, self.on_menu_open = on_activate, on_scroll, on_menu_open
        self.root = MenuItem("root")
        self.items: dict[int, MenuItem] = {}
        self.revision = 1
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        sni = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
        menu = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
        self.bus.register_object("/StatusNotifierItem", sni, self._sni_call, self._sni_get, None)
        self.bus.register_object("/MenuBar", menu, self._menu_call, self._menu_get, None)
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
        self.root = MenuItem("root", children=items)
        self.items = {0: self.root}
        counter = [1]

        def number(item):
            for c in item.children:
                c.id = counter[0]
                counter[0] += 1
                self.items[c.id] = c
                number(c)
        number(self.root)
        self.revision += 1
        self._emit("/MenuBar", "com.canonical.dbusmenu", "LayoutUpdated", GLib.Variant("(ui)", (self.revision, 0)))

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

    def _menu_get(self, _conn, _sender, _path, _iface, prop):
        return {"Version": GLib.Variant("u", 3), "TextDirection": GLib.Variant("s", "ltr"),
                "Status": GLib.Variant("s", "normal"), "IconThemePath": GLib.Variant("as", [])}.get(prop)

    def _layout(self, item: MenuItem, depth: int):
        children = []
        if depth != 0:
            children = [GLib.Variant("v", self._layout(c, depth - 1)) for c in item.children]
        props = item.props() if item is not self.root else {"children-display": GLib.Variant("s", "submenu")}
        return GLib.Variant("(ia{sv}av)", (item.id, props, children))

    def _menu_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        args = params.unpack()
        if method == "GetLayout":
            parent, depth, _names = args
            item = self.items.get(parent, self.root)
            invocation.return_value(GLib.Variant.new_tuple(GLib.Variant("u", self.revision),
                                                           self._layout(item, depth)))
        elif method == "GetGroupProperties":
            ids, _names = args
            out = [(i, self.items[i].props()) for i in (ids or self.items.keys()) if i in self.items]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (out,)))
        elif method == "GetProperty":
            i, name = args
            v = self.items[i].props().get(name, GLib.Variant("s", "")) if i in self.items else GLib.Variant("s", "")
            invocation.return_value(GLib.Variant("(v)", (v,)))
        elif method == "Event":
            i, event, _data, _ts = args
            if event == "clicked" and i in self.items and self.items[i].callback:
                GLib.idle_add(lambda: self.items[i].callback() and False)
            invocation.return_value(None)
        elif method == "EventGroup":
            for i, event, _data, _ts in args[0]:
                if event == "clicked" and i in self.items and self.items[i].callback:
                    cb = self.items[i].callback
                    GLib.idle_add(lambda cb=cb: cb() and False)
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            if args[0] == 0 and self.on_menu_open:
                self.on_menu_open()
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
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
