"""Make VoiceOver follow the focus move into the message field on a chat open.

Opening a chat from the chats table (Enter, or VO-Space on a row) moves wx
focus to the message field: navigate_to_conversation() queues
``message_field.SetFocus()`` and the log shows ``FindFocus()`` is the field
afterwards. VoiceOver's cursor does not reliably go with it and stays on
the row. Around that one focus move the same open also does three things
VoiceOver reacts to:

* the press is still being handled — accessibilityPerformPress() returns,
  the activation runs on the next event-loop turn and the focus move one
  turn after that, so the field's focus change can reach VoiceOver while it
  is still busy with the row it pressed;
* mark-as-read rewrites the opened chat's row (``_refresh_chat_row_in_list``)
  and a debounced chat-list pass may rewrite more; every MacListCtrl write
  goes through wx.ListBox, which reloads the native table under the row
  VoiceOver may still be on;
* a pinned-messages notice is announced at high priority right after.

Nothing here changes where focus goes or what is spoken. Once the open has
gone quiet — SETTLE_S after it, pushed back by every write to a list
(MacListCtrl: the chats table, or the messages table filling in) that does
not have focus, never later than MAX_SETTLE_S — and only if wx
focus is still on that chat's message field, the field's view is confirmed
as first responder and NSAccessibilityFocusedUIElementChangedNotification
is posted for it, once. Announcements requested before that are held and
posted right after it; for QUIET_S afterwards they go at medium instead of
high priority — AppKit documents the priority as what lets VoiceOver speak
"after the current speech is completed", so the field is named first.

The decisions are FocusSettle, plain logic with the clock passed in; the
wx/Cocoa side is the thin functions after it.
"""

import logging
import time

import wx

SETTLE_S = 0.2       # quiet time after the open (or the last list write) before re-asserting
MAX_SETTLE_S = 1.0   # list writes never push the re-assert later than this after the open
QUIET_S = 1.5        # after the re-assert, announcements wait for VoiceOver's current speech

HOLD = "hold"
QUEUE = "queue"          # medium priority: after VoiceOver's current speech
INTERRUPT = "interrupt"  # high priority: WinZapp's normal announcement


class FocusSettle:
    """When to re-assert the field's focus, and how to post an announcement
    meanwhile. *now* is seconds on a monotonic clock."""

    def __init__(self, settle=SETTLE_S, max_settle=MAX_SETTLE_S, quiet=QUIET_S):
        self.settle_s = settle
        self.max_settle_s = max_settle
        self.quiet_s = quiet
        self.generation = 0
        self.armed_at = None
        self.quiet_until = 0.0
        self.held = []

    @property
    def pending(self):
        return self.armed_at is not None

    def arm(self, now):
        """A chat open just queued focus to its message field. Returns the
        generation the re-assert must carry and its delay in seconds; a newer
        open makes every earlier generation stale."""
        self.generation += 1
        self.armed_at = now
        return self.generation, self.settle_s

    def delay_after_write(self, now):
        """A list without focus was rewritten. Seconds until the
        re-assert should now run, or None when no open is settling."""
        if not self.pending:
            return None
        due = min(now + self.settle_s, self.armed_at + self.max_settle_s)
        return max(0.0, due - now)

    def settle(self, generation, now):
        """The re-assert timer fired. True when it is the current open's and
        it should post; from here announcements queue for QUIET_S."""
        if generation != self.generation or not self.pending:
            return False
        self.armed_at = None
        self.quiet_until = now + self.quiet_s
        return True

    def cancel(self):
        """The user moved before the open settled: no re-assert, and nothing
        to wait for before speaking normally."""
        self.armed_at = None
        self.quiet_until = 0.0

    def route(self, now):
        """How an announcement requested at *now* is posted."""
        if self.pending:
            return HOLD
        if now < self.quiet_until:
            return QUEUE
        return INTERRUPT

    def take_held(self):
        held, self.held = self.held, []
        return held


def focus_stayed(panel, field, jid):
    """The re-assert applies only while wx focus is on *field* and the chat
    opened as *jid* is still the open one: anything else means the user
    moved, and their focus is never touched."""
    if field is None or wx.Window.FindFocus() is not field:
        return False
    return ((getattr(panel, "conversation", None) or {}).get("remoteJid")) == jid


_settle = FocusSettle()
_timer = None
_target = None  # (panel, field, jid) of the open being settled


def _clock():
    return time.monotonic()


def _schedule(delay_s, generation):
    global _timer
    ms = max(1, int(round(delay_s * 1000)))
    if _timer is not None and _timer.IsRunning():
        _timer.Stop()
    _timer = wx.CallLater(ms, _fire, generation)


def begin(panel):
    """Called after navigate_to_conversation() queued focus to the field."""
    global _target
    field = getattr(panel, "message_field", None)
    if field is None:
        return
    _target = (panel, field, (getattr(panel, "conversation", None) or {}).get("remoteJid"))
    generation, delay = _settle.arm(_clock())
    _schedule(delay, generation)


def note_list_write(ctrl):
    """A MacListCtrl row was written. Only a table without focus counts: one
    with focus is where the user is, and no open is waiting on it."""
    if not _settle.pending:
        return
    try:
        if ctrl.HasFocus():
            return
    except Exception:
        return
    delay = _settle.delay_after_write(_clock())
    if delay is not None:
        _schedule(delay, _settle.generation)


def _fire(generation):
    if not _settle.pending or generation != _settle.generation:
        return
    panel, field, jid = _target or (None, None, None)
    try:
        if focus_stayed(panel, field, jid):
            _settle.settle(generation, _clock())
            _post_focus_changed(field)
        else:
            _settle.cancel()
    except Exception:
        _settle.cancel()
        logging.debug("[vo_focus] re-assert failed", exc_info=True)
    finally:
        for post in _settle.take_held():
            route_announcement(post)


def _post_focus_changed(field):
    """Point VoiceOver at *field*: make its text view first responder if
    AppKit disagrees with wx, then post the focus-changed notification.
    A multi-line wx.TextCtrl is a scroll view whose document view (an
    NSTextView) is what takes focus; makeFirstResponder on an NSTextView
    keeps its selection, unlike an NSTextField's, so the draft is untouched."""
    from AppKit import (
        NSAccessibilityFocusedUIElementChangedNotification,
        NSAccessibilityPostNotification,
    )
    from .accessibility_mac import _ns_views
    views = _ns_views(field)
    if not views:
        return
    ns_window = views[0].window()
    if ns_window is None or not ns_window.isKeyWindow():
        return  # another app is in front; VoiceOver is not in WinZapp
    responder = ns_window.firstResponder()
    if responder not in views:
        ns_window.makeFirstResponder_(views[-1])
        responder = views[-1]
    NSAccessibilityPostNotification(responder, NSAccessibilityFocusedUIElementChangedNotification)
    logging.debug("[vo_focus] VoiceOver pointed at the message field")


def route_announcement(post):
    """speech.VoiceOverAnnounce posts through here: *post(queued)* posts the
    announcement, at medium priority when *queued* is True."""
    how = _settle.route(_clock())
    if how == HOLD:
        _settle.held.append(post)
    else:
        post(how == QUEUE)


def install():
    from ui import conversations
    cls = conversations.ConversationsPanel
    orig_navigate = cls.navigate_to_conversation

    def navigate_to_conversation(self, conversation, *a, **k):
        result = orig_navigate(self, conversation, *a, **k)
        try:
            # Same rule the open used to pick its target; take_focus=False
            # (a background refresh) moves no focus, so there is nothing to follow.
            if k.get("take_focus", True) and self._open_focus_target() == "message_field":
                begin(self)
        except Exception:
            logging.debug("[vo_focus] could not arm the re-assert", exc_info=True)
        return result

    cls.navigate_to_conversation = navigate_to_conversation
