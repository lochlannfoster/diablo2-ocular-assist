"""The pure parts of the tray icon: menu model, layout shape, introspection."""

import xml.etree.ElementTree as ET

from native import sni


def test_menu_labels_follow_overlay_state():
    shown = dict(sni.menu_items(False))
    hidden = dict(sni.menu_items(True))
    assert shown[2]["label"] == "Hide overlay" and hidden[2]["label"] == "Show overlay"
    assert shown[3] == {"type": "separator"}
    assert sorted(shown) == [1, 2, 3, 4]


def test_commands():
    assert sni.command_for(1) == "settings" and sni.command_for(2) == "hide"
    assert sni.command_for(3) is None and sni.command_for(4) == "quit"
    assert sni.command_for(99) is None


def test_layout_shape():
    root_id, props, children = sni.layout(sni.menu_items(False))
    assert root_id == 0 and props == {"children-display": "submenu"}
    assert [c[0] for c in children] == [1, 2, 3, 4]
    assert all(c[2] == [] for c in children)
    assert all("label" in c[1] for c in children if c[1].get("type") != "separator")


def test_introspection_xml_parses_and_names_what_plasma_calls():
    item = ET.fromstring(sni.ITEM_XML)
    menu = ET.fromstring(sni.MENU_XML)
    item_methods = {m.get("name") for m in item.iter("method")}
    menu_methods = {m.get("name") for m in menu.iter("method")}
    assert {"Activate", "SecondaryActivate", "ContextMenu"} <= item_methods
    assert {"GetLayout", "GetGroupProperties", "Event", "AboutToShow"} <= menu_methods
    assert {p.get("name") for p in item.iter("property")} >= {"IconName", "Menu", "Status"}
