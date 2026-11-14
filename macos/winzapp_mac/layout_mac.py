"""Keep the messages list on screen when the conversation shows more controls.

The messages list is the only stretchable item in the conversation panel's
sizer. Playing or recording a voice message, quoting a message, the message
action buttons and the composer all show extra controls and then call only
``self.conversation_panel.Layout()``: the inner panel keeps its size, so the
list gives up every pixel those controls take. A read-only AX walk of the
running app found it at 90 px while audio played (Chats list: 310 px), and
it reaches 0 px. VoiceOver drops a zero-height scroll area from the window,
so the whole messages table vanishes after replying with or playing a voice
message.

Two changes, no control touched beyond its size:

* the messages list and the Chats list keep a minimum height of a few rows,
  so the inner panel's minimum grows with every control shown beside it and
  neither list can be squeezed to nothing in exchange;
* the conversation panel's ``Layout()`` also lays out ConversationsPanel,
  whose sizer then gives the conversation panel that larger minimum and
  takes the space from the Chats list instead.

The second is an instance attribute on ``conversation_panel``: only
WinZapp's Python calls see it, never wx's own C++ resize handling. The
inner layout stays synchronous, as WinZapp expects; the outer one is
deferred to the next event-loop turn and coalesced, because a single arrow
key in the messages list can call the inner ``Layout()`` five times
(``on_message_selected`` toggling the action buttons, read-more, the media
slot...) and laying out the whole panel each time is wasted work.
"""

import logging

import wx

from .listctrl import row_height

MIN_ROWS = 4


def min_list_height(control, rows=MIN_ROWS):
    """Minimum height in px of *control* showing *rows* rows, plus the
    scroll view's border."""
    return rows * row_height(control) + 4


def keep_lists_tall(panel):
    """Give the Chats list and every messages-list control (classic and
    listbox, only one of them shown) a minimum height of MIN_ROWS rows."""
    controls = list(getattr(panel, "_message_list_controls", {}).values())
    if not controls:
        # Renamed upstream: say so instead of silently losing the fix.
        logging.debug("[layout_mac] no _message_list_controls; messages list min height not set")
    chats = getattr(panel, "conversations_list", None)
    if chats is not None:
        controls.append(chats)
    else:
        logging.debug("[layout_mac] no conversations_list; Chats list min height not set")
    for control in controls:
        control.SetMinSize((-1, min_list_height(control)))


def chain_layout_to_outer(panel):
    """Make ``panel.conversation_panel.Layout()`` also lay out *panel*, at
    most once per event-loop turn."""
    inner = getattr(panel, "conversation_panel", None)
    if inner is None:
        # Renamed upstream: the lists still keep their minimum height, and a
        # missing chain must never stop WinZapp from starting.
        logging.debug("[layout_mac] no conversation_panel; outer layout not chained")
        return
    inner_layout = inner.Layout     # wx's own bound method
    pending = []                    # non-empty from scheduling until the outer layout ends

    def outer_layout():
        try:
            panel.Layout()
        except Exception:
            # e.g. the panel was destroyed before this event-loop turn.
            logging.debug("[layout_mac] outer layout failed", exc_info=True)
        finally:
            pending.clear()

    def layout():
        result = inner_layout()
        if not pending:
            pending.append(True)
            wx.CallAfter(outer_layout)
        return result

    inner.Layout = layout


def install():
    from ui import conversations
    cls = conversations.ConversationsPanel
    orig_init_ui = cls.init_UI

    def init_ui(self, *a, **k):
        result = orig_init_ui(self, *a, **k)
        keep_lists_tall(self)
        chain_layout_to_outer(self)
        return result

    cls.init_UI = init_ui
