"""Regression test for issue #104: the latest alpha crashed on startup with

    TypeError: _SilenceableVoiceButtonAccessible.__init__() missing 1
    required positional argument: 'main_window'

ui/accessible.py's AccessibleSendVoiceMessage/AccessibleDiscardVoiceMessage
were changed to require a main_window argument (the silence-while-recording
fix — blanking the button's accessible name while Settings > Conteúdo
Falado's "silence while recording" toggle is on). conversations.py's two
call sites were updated at the time; status_panel.py's two call sites
(StatusPanel's own voice-post recorder, a second, independent instance of
the same Discard/Send buttons) were missed, so pairing an account and
opening the Status tab's voice recorder crashed the whole app on startup —
main.py's __init__ chain calls status_panel.py's init_UI() unconditionally.

Rather than pinning just those two call sites (which would only catch a
regression of this exact bug, not the general class of bug), this walks
every `<widget>.SetAccessible(<SomeAccessibleClass>(...))` call across the
UI modules that construct the Accessible inline, and checks that the call's
argument count actually binds to that class's own __init__ signature — so
the next time an Accessible subclass's constructor changes, a call site
that wasn't updated fails a test instead of only surfacing as a startup
crash report from a user.
"""

import ast
import inspect
from pathlib import Path

import wx

import status_panel
import ui.accessible as accessible_module
import ui.conversations
import ui.dialogs.incoming_call
import ui.media_viewer

ROOT = Path(__file__).resolve().parents[1]

# Every UI module that wires up an Accessible via SetAccessible(SomeClass(...)).
# Paired with the already-imported module so a class defined locally (e.g.
# conversations.py's own _FocusedTransferGaugeAccessible) resolves too, not
# only classes shared from ui.accessible.
FILES = (
    ("client/ui/conversations.py", ui.conversations),
    ("client/status_panel.py", status_panel),
    ("client/ui/media_viewer.py", ui.media_viewer),
    ("client/ui/dialogs/incoming_call.py", ui.dialogs.incoming_call),
)


def _setaccessible_construction_calls(rel_path):
    """Yield (lineno, class_name, positional_arg_count, keyword_names) for
    every `X.SetAccessible(ClassName(...))` call in the file at rel_path."""
    src = (ROOT / rel_path).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=rel_path)
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "SetAccessible"
            and len(node.args) == 1
        ):
            continue
        inner = node.args[0]
        if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
            kwnames = tuple(kw.arg for kw in inner.keywords if kw.arg)
            yield node.lineno, inner.func.id, len(inner.args), kwnames


def test_every_setaccessible_construction_matches_its_class_signature():
    problems = []
    checked = 0
    for rel_path, module in FILES:
        if not (ROOT / rel_path).is_file():
            continue
        for lineno, cls_name, n_args, kwnames in _setaccessible_construction_calls(rel_path):
            cls = getattr(accessible_module, cls_name, None) or getattr(module, cls_name, None)
            if cls is None or not isinstance(cls, type):
                problems.append(
                    f"{rel_path}:{lineno}: {cls_name} is not a class in "
                    f"ui.accessible or in {module.__name__}"
                )
                continue
            checked += 1
            if cls.__init__ is wx.Accessible.__init__:
                # No Python-defined __init__ anywhere in the MRO: it takes
                # whatever bare wx.Accessible() takes, i.e. nothing.
                # wx.Accessible is a SWIG-wrapped extension type, so
                # inspect.signature() can't introspect its own __init__
                # directly (raises ValueError, not TypeError).
                if n_args or kwnames:
                    problems.append(
                        f"{rel_path}:{lineno}: {cls_name}(...) called with "
                        f"{n_args} positional arg(s) {kwnames}, but {cls_name} "
                        f"defines no __init__ of its own (expects no arguments)"
                    )
                continue
            try:
                inspect.signature(cls.__init__).bind(
                    None, *([None] * n_args), **{k: None for k in kwnames}
                )
            except TypeError as exc:
                problems.append(
                    f"{rel_path}:{lineno}: {cls_name}(...) called with "
                    f"{n_args} positional arg(s) {kwnames} does not match "
                    f"its constructor — {exc}"
                )

    assert checked > 0, "no SetAccessible(...) construction calls were found — check FILES/the AST walk"
    assert not problems, "\n".join(problems)
