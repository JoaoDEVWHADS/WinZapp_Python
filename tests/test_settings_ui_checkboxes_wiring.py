"""Configurações > Interface do usuário: every plain on/off checkbox is wired to
one settings key, the same way, end to end.

Each of these checkboxes is hand-wired in four separate places of
settings_dialog.py — created on the tab, loaded from
settings["user_interface"][key] with a fallback default, written back to that
key in _apply_values(), and relabelled in _refresh_dialog_labels() when Apply
changes the language. Nothing ties the four together, so a copy-paste slip in
any one of them fails silently:

- loaded from one key and saved to another — the option looks like it works
  and resets itself every time Settings is saved;
- a fallback default different from DEFAULT_SETTINGS — the box shows a state
  the app is not actually in, on any install missing the key;
- a relabel with the wrong string, or none — the box keeps the previous
  language after Apply. This is how "show yesterday's messages with the date
  omitted" shipped, and this file is what found it.

This reads the dialog's source, so it runs everywhere without opening a
window. tests/test_settings_ui_checkboxes_roundtrip.py drives the real dialog
through the same checkboxes, in CI only.
"""

import ast
from pathlib import Path

import pytest

from core.utils import DEFAULT_SETTINGS

SETTINGS_DIALOG = (
    Path(__file__).resolve().parent.parent / "client" / "ui" / "dialogs" / "settings_dialog.py"
)
SECTION = "user_interface"


def _self_attr(node):
    """'_foo_cb' for `self._foo_cb`, else None."""
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    ):
        return node.attr
    return None


def _i18n_key(node):
    """'some_key' for `i18n.t("some_key")`, else None."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "t"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ):
        return node.args[0].value
    return None


def _is_section_get(node):
    """`<...>.get("user_interface", {})` or `.setdefault("user_interface", {})`."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("get", "setdefault")
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == SECTION
    )


def _is_getvalue_of(node, attrs):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "GetValue"
        and _self_attr(node.func.value) in attrs
    )


def _class_node():
    tree = ast.parse(SETTINGS_DIALOG.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog":
            return node
    raise AssertionError("SettingsDialog not found")


def _parse():
    """Returns (ui_page_boxes, section_loaded_boxes).

    ui_page_boxes: {attr: {"label", "loads": [(key, default)], "saves": [key],
    "relabels": [key]}} for every wx.CheckBox created on self._ui_page.

    section_loaded_boxes: every wx.CheckBox, whatever its parent, whose value
    is loaded from settings["user_interface"] — the cross-check that catches a
    checkbox added to the tab inside a StaticBox or a sub-panel.
    """
    cls = _class_node()
    all_boxes = {}
    ui_page = set()

    for node in ast.walk(cls):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        attr = _self_attr(node.targets[0])
        call = node.value
        if not (
            attr
            and isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "CheckBox"
        ):
            continue
        label = next((_i18n_key(k.value) for k in call.keywords if k.arg == "label"), None)
        all_boxes[attr] = {"label": label, "loads": [], "saves": [], "relabels": []}
        if call.args and _self_attr(call.args[0]) == "_ui_page":
            ui_page.add(attr)

    for func in (n for n in cls.body if isinstance(n, ast.FunctionDef)):
        loaded = {}          # var -> (key, default), from .get("user_interface", {}).get(key, default)
        section_names = set()  # names bound to the section dict itself
        value_names = {}     # var -> checkbox attr, from var = self._x.GetValue()
        for node in ast.walk(func):
            if not (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                continue
            name, value = node.targets[0].id, node.value
            if _is_section_get(value):
                section_names.add(name)
            elif _is_getvalue_of(value, all_boxes):
                value_names[name] = _self_attr(value.func.value)
            elif (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Attribute)
                and value.func.attr == "get"
                and _is_section_get(value.func.value)
                and len(value.args) == 2
                and all(isinstance(a, ast.Constant) for a in value.args)
            ):
                loaded[name] = (value.args[0].value, value.args[1].value)

        for node in ast.walk(func):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("SetValue", "SetLabel")
                and _self_attr(node.func.value) in all_boxes
                and node.args
            ):
                attr = _self_attr(node.func.value)
                arg = node.args[0]
                if node.func.attr == "SetLabel":
                    all_boxes[attr]["relabels"].append(_i18n_key(arg))
                    continue
                if (
                    isinstance(arg, ast.Call)
                    and isinstance(arg.func, ast.Name)
                    and arg.func.id == "bool"
                    and arg.args
                ):
                    arg = arg.args[0]
                if isinstance(arg, ast.Name) and arg.id in loaded:
                    all_boxes[attr]["loads"].append(loaded[arg.id])

            if not (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Subscript)
                and isinstance(node.targets[0].slice, ast.Constant)
            ):
                continue
            target = node.targets[0]
            key = target.slice.value
            into_section = _is_section_get(target.value) or (
                isinstance(target.value, ast.Name) and target.value.id in section_names
            )
            if not into_section:
                continue
            # <section>[key] = self._x.GetValue()
            if _is_getvalue_of(node.value, all_boxes):
                all_boxes[_self_attr(node.value.func.value)]["saves"].append(key)
            # <section>[key] = var, where var = self._x.GetValue()
            elif isinstance(node.value, ast.Name) and node.value.id in value_names:
                all_boxes[value_names[node.value.id]]["saves"].append(key)

    ui_page_boxes = {attr: info for attr, info in all_boxes.items() if attr in ui_page}
    section_loaded = {attr for attr, info in all_boxes.items() if info["loads"]}
    return ui_page_boxes, section_loaded


BOXES, SECTION_LOADED = _parse()


def checkbox_keys():
    """[(attr, settings key)] for the round-trip test, from the same parse."""
    return sorted(
        (attr, info["saves"][0])
        for attr, info in BOXES.items()
        if len(info["saves"]) == 1
    )


def _only(items, attr, what, fix):
    assert len(items) == 1, f"{attr}: expected exactly one {what}, found {items!r} — {fix}"
    return items[0]


def test_the_parse_actually_finds_the_tab_checkboxes():
    """Guards the guard: a refactor that changes the wiring's shape must fail
    here loudly, not make every test below pass on an empty list."""
    assert len(BOXES) >= 11
    for expected in (
        "_confirm_mark_all_read_cb",
        "_bulk_action_shortcuts_cb",
        "_show_delivery_status_cb",
        "_show_listbox_count_cb",
        "_forwarded_prefix_cb",
        "_status_media_viewer_dialog_cb",
    ):
        assert expected in BOXES


def test_no_user_interface_checkbox_escapes_the_list():
    """A checkbox loaded from settings["user_interface"] but created under
    another parent (a StaticBox, a sub-panel) would otherwise never be
    checked by anything in this file."""
    escaped = sorted(SECTION_LOADED - set(BOXES))
    assert escaped == [], (
        f"{escaped} load from settings[{SECTION!r}] but are not created with "
        f"self._ui_page as parent; extend _parse() so they are covered"
    )


@pytest.mark.parametrize("attr", sorted(BOXES))
class TestEachInterfaceCheckbox:
    def test_loads_and_saves_the_same_key(self, attr):
        info = BOXES[attr]
        loaded_key, _ = _only(
            info["loads"], attr, "load in _load_values()",
            f"read it with settings.get({SECTION!r}, {{}}).get(key, default) and SetValue() it",
        )
        saved_key = _only(
            info["saves"], attr, "save in _apply_values()",
            f"write settings.setdefault({SECTION!r}, {{}})[key] = self.{attr}.GetValue()",
        )
        assert loaded_key == saved_key, (
            f"{attr} is loaded from {loaded_key!r} but saved to {saved_key!r}: "
            f"the option would reset itself every time Settings is saved"
        )

    def test_its_fallback_matches_the_shipped_default(self, attr):
        info = BOXES[attr]
        if len(info["loads"]) != 1:
            pytest.skip("covered by test_loads_and_saves_the_same_key")
        (key, fallback), = info["loads"]
        assert key in DEFAULT_SETTINGS[SECTION], (
            f"{attr} uses {SECTION}.{key}, which is not in core/utils.py DEFAULT_SETTINGS "
            f"(nor, then, in data/settings_default.json)"
        )
        assert fallback == DEFAULT_SETTINGS[SECTION][key], (
            f"{attr} falls back to {fallback!r} in _load_values(), but DEFAULT_SETTINGS "
            f"ships {SECTION}.{key} = {DEFAULT_SETTINGS[SECTION][key]!r}; make them agree"
        )

    def test_is_relabelled_with_its_own_string(self, attr):
        label = BOXES[attr]["label"]
        assert label, f"{attr} is created without an i18n.t(...) label"
        assert BOXES[attr]["relabels"] == [label], (
            f"{attr}: add self.{attr}.SetLabel(i18n.t({label!r})) to "
            f"_refresh_dialog_labels(), or it keeps the old language after Apply "
            f"(found {BOXES[attr]['relabels']!r})"
        )
