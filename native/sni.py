"""StatusNotifierItem tray icon for KDE (and any SNI host), over DBus via Gio.

GTK4 has no tray icon API. Plasma's tray speaks the freedesktop
StatusNotifierItem protocol plus com.canonical.dbusmenu for the menu, so we
export those two objects on the session bus ourselves and register with the
watcher. Plasma then draws the icon and the menu; we only answer method calls,
which Gio delivers on the GTK main loop -- no threads involved.

The pure parts (menu model, layout tuples, introspection XML) are module
level so they can be tested without a bus; gi is imported lazily in SniTray.
"""

from __future__ import annotations

import os

WATCHER = "org.kde.StatusNotifierWatcher"
ITEM_IFACE = "org.kde.StatusNotifierItem"
MENU_IFACE = "com.canonical.dbusmenu"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
ICON_NAME = "applications-games"   # ships with Breeze; no icon file to bundle

# (menu id, label or None for "depends on state" or "-" for separator, command)
MENU = (
    (1, "Show settings", "settings"),
    (2, None, "hide"),
    (3, "-", None),
    (4, "Quit", "quit"),
)


class TrayUnavailable(Exception):
    pass


def menu_items(overlay_hidden: bool) -> list[tuple[int, dict]]:
    """Menu rows as (id, dbusmenu property dict with plain Python values)."""
    rows = []
    for item_id, label, command in MENU:
        if label == "-":
            rows.append((item_id, {"type": "separator"}))
            continue
        if label is None:
            label = "Show overlay" if overlay_hidden else "Hide overlay"
        rows.append((item_id, {"label": label, "enabled": True, "visible": True}))
    return rows


def command_for(item_id: int) -> str | None:
    for mid, _label, command in MENU:
        if mid == item_id:
            return command
    return None


def layout(items: list[tuple[int, dict]]) -> tuple:
    """dbusmenu GetLayout body for the root: (id, props, children), values plain."""
    return (0, {"children-display": "submenu"}, [(item_id, props, []) for item_id, props in items])


ITEM_XML = f"""
<node>
  <interface name="{ITEM_IFACE}">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <method name="Activate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="ContextMenu"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Scroll"><arg name="delta" type="i" direction="in"/><arg name="orientation" type="s" direction="in"/></method>
    <signal name="NewIcon"/>
    <signal name="NewStatus"><arg type="s"/></signal>
    <signal name="NewToolTip"/>
  </interface>
</node>
"""

MENU_XML = f"""
<node>
  <interface name="{MENU_IFACE}">
    <property name="Version" type="u" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg name="parentId" type="i" direction="in"/>
      <arg name="recursionDepth" type="i" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="revision" type="u" direction="out"/>
      <arg name="layout" type="(ia{{sv}}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="properties" type="a(ia{{sv}})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg name="id" type="i" direction="in"/>
      <arg name="name" type="s" direction="in"/>
      <arg name="value" type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg name="id" type="i" direction="in"/>
      <arg name="eventId" type="s" direction="in"/>
      <arg name="data" type="v" direction="in"/>
      <arg name="timestamp" type="u" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg name="events" type="a(isvu)" direction="in"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg name="id" type="i" direction="in"/>
      <arg name="needUpdate" type="b" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="updatesNeeded" type="ai" direction="out"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{{sv}})"/><arg type="a(ias)"/>
    </signal>
    <signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
    <signal name="ItemActivationRequested"><arg type="i"/><arg type="u"/></signal>
  </interface>
</node>
"""


class SniTray:
    """The live tray item. Construct on the GTK thread; raises TrayUnavailable
    when there is no StatusNotifier host to talk to."""

    def __init__(self, on_command, overlay_hidden: bool):
        from gi.repository import Gio, GLib

        self.Gio, self.GLib = Gio, GLib
        self.on_command = on_command
        self._hidden = bool(overlay_hidden)
        self._revision = 1
        self._registered = False
        self.conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        if not self._host_present():
            raise TrayUnavailable("no StatusNotifier host on the session bus")

        self._item_reg = self.conn.register_object(
            ITEM_PATH, Gio.DBusNodeInfo.new_for_xml(ITEM_XML).interfaces[0],
            self._item_call, self._item_get, None)
        self._menu_reg = self.conn.register_object(
            MENU_PATH, Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0],
            self._menu_call, self._menu_get, None)
        self.bus_name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self._owner = Gio.bus_own_name_on_connection(
            self.conn, self.bus_name, Gio.BusNameOwnerFlags.NONE,
            self._on_name_acquired, None)
        # Re-register when plasmashell / kded restarts and the watcher returns.
        self._watch = Gio.bus_watch_name_on_connection(
            self.conn, WATCHER, Gio.BusNameWatcherFlags.NONE,
            lambda *_: self._register(), lambda *_: setattr(self, "_registered", False))

    # -- watcher ------------------------------------------------------------

    def _host_present(self) -> bool:
        try:
            reply = self.conn.call_sync(
                WATCHER, "/StatusNotifierWatcher", "org.freedesktop.DBus.Properties", "Get",
                self.GLib.Variant("(ss)", (WATCHER, "IsStatusNotifierHostRegistered")),
                self.GLib.VariantType("(v)"), self.Gio.DBusCallFlags.NONE, 500, None)
        except self.GLib.Error:
            return False
        return bool(reply.unpack()[0])

    def _on_name_acquired(self, *_):
        self._register()

    def _register(self):
        if self._registered or not getattr(self, "bus_name", None):
            return
        try:
            self.conn.call_sync(
                WATCHER, "/StatusNotifierWatcher", WATCHER, "RegisterStatusNotifierItem",
                self.GLib.Variant("(s)", (self.bus_name,)), None,
                self.Gio.DBusCallFlags.NONE, 1000, None)
            self._registered = True
        except self.GLib.Error as exc:
            print(f"tray: could not register with the watcher: {exc}", flush=True)

    # -- StatusNotifierItem -------------------------------------------------

    def _item_get(self, conn, sender, path, iface, prop):
        V = self.GLib.Variant
        table = {
            "Category": V("s", "ApplicationStatus"),
            "Id": V("s", "diablo2-ocular-assist"),
            "Title": V("s", "Diablo II overlay"),
            "Status": V("s", "Active"),
            "WindowId": V("i", 0),
            "IconName": V("s", ICON_NAME),
            "IconPixmap": V("a(iiay)", []),
            "OverlayIconName": V("s", ""),
            "AttentionIconName": V("s", ""),
            "IconThemePath": V("s", ""),
            "ToolTip": V("(sa(iiay)ss)", (ICON_NAME, [], "Diablo II overlay",
                                           "Left click: settings · right click: menu")),
            "Menu": V("o", MENU_PATH),
            "ItemIsMenu": V("b", False),
        }
        return table.get(prop)

    def _item_call(self, conn, sender, path, iface, method, params, invocation):
        if method == "Activate":
            self.on_command("settings")
        elif method == "SecondaryActivate":
            self.on_command("hide")
        # ContextMenu / Scroll: Plasma renders the dbusmenu itself; nothing to do.
        invocation.return_value(None)

    # -- com.canonical.dbusmenu ---------------------------------------------

    def _menu_get(self, conn, sender, path, iface, prop):
        V = self.GLib.Variant
        return {
            "Version": V("u", 3),
            "Status": V("s", "normal"),
            "TextDirection": V("s", "ltr"),
            "IconThemePath": V("as", []),
        }.get(prop)

    def _props(self, props: dict):
        V = self.GLib.Variant
        out = {}
        for key, value in props.items():
            out[key] = V("b", value) if isinstance(value, bool) else V("s", str(value))
        return out

    def _menu_call(self, conn, sender, path, iface, method, params, invocation):
        V = self.GLib.Variant
        if method == "GetLayout":
            root_id, props, children = layout(menu_items(self._hidden))
            kids = [V("(ia{sv}av)", (cid, self._props(cprops), [])) for cid, cprops, _ in children]
            invocation.return_value(
                V("(u(ia{sv}av))", (self._revision, (root_id, self._props(props), kids))))
        elif method == "GetGroupProperties":
            ids = set(params.unpack()[0])
            rows = [(item_id, self._props(props)) for item_id, props in menu_items(self._hidden)
                    if not ids or item_id in ids]
            invocation.return_value(V("(a(ia{sv}))", (rows,)))
        elif method == "GetProperty":
            item_id, name = params.unpack()
            props = dict(menu_items(self._hidden)).get(item_id, {})
            invocation.return_value(V("(v)", (self._props(props).get(name, V("s", "")),)))
        elif method == "Event":
            item_id, event, _data, _ts = params.unpack()
            if event == "clicked":
                command = command_for(item_id)
                if command:
                    self.on_command(command)
            invocation.return_value(None)
        elif method == "EventGroup":
            for item_id, event, _data, _ts in params.unpack()[0]:
                if event == "clicked" and command_for(item_id):
                    self.on_command(command_for(item_id))
            invocation.return_value(V("(ai)", ([],)))
        elif method == "AboutToShow":
            invocation.return_value(V("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(V("(aiai)", ([], [])))
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    # -- interface used by the Session ----------------------------------------

    def set_overlay_hidden(self, hidden: bool):
        if bool(hidden) == self._hidden:
            return
        self._hidden = bool(hidden)
        self._revision += 1
        try:
            self.conn.emit_signal(None, MENU_PATH, MENU_IFACE, "LayoutUpdated",
                                  self.GLib.Variant("(ui)", (self._revision, 0)))
        except self.GLib.Error:
            pass

    def close(self):
        Gio = self.Gio
        if self._watch:
            Gio.bus_unwatch_name(self._watch)
            self._watch = 0
        if self._owner:
            Gio.bus_unown_name(self._owner)
            self._owner = 0
        for reg in (self._item_reg, self._menu_reg):
            if reg:
                self.conn.unregister_object(reg)
        self._item_reg = self._menu_reg = 0
