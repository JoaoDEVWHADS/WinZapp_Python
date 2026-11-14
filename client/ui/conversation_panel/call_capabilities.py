"""Use the call dispatch policy for controls, without probing the engine."""
from core.call_logic import engine_refuses_call
from core.conversation_view import conversation_in_view


def can_place_call(main_window, *, is_video=False, is_group=False):
    return not engine_refuses_call(
        getattr(main_window, "_uses_neonize", lambda: False)(),
        getattr(main_window, "_neonize_calls", False),
        placing=True, is_video=is_video, is_group=is_group,
        bridge_has_video=getattr(main_window, "_neonize_video_calls", False),
        bridge_has_group_calls=getattr(main_window, "_neonize_group_calls", False),
    )


def can_relocate_call_focus(panel):
    """A late capability/discovery reply must not focus a hidden conversation."""
    main = panel.main_window
    try:
        return (not getattr(main, "_shutting_down", False)
                and conversation_in_view(panel)
                and getattr(main, "_allow_ui_focus_changes", lambda: False)())
    except RuntimeError:  # Native controls already destroyed.
        return False


def refresh_call_controls(main_window):
    """UI-thread callback: recompute the current chat, never a captured one.

    Reuse the cached discovery result; no request, timer or watch is started.
    A missing panel is normal during startup, and queued replies can outlive
    the native window during shutdown.
    """
    if getattr(main_window, "_shutting_down", False):
        return
    panel = getattr(main_window, "conversations_panel", None)
    if panel is None:
        return
    try:
        panel._show_ongoing_group_call(getattr(panel, "_ongoing_group_call", None))
    except RuntimeError:  # wx object already destroyed.
        return
