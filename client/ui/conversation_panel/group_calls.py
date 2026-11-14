"""Discover calls only for the visible group; late replies cannot change chats."""
import logging
import threading

import wx
from core.conversation_view import conversation_in_view
from ui.conversation_panel.call_capabilities import can_place_call, can_relocate_call_focus


class GroupCallJoinPanelMixin:
    _GROUP_CALL_POLL_MS = 10_000

    def _init_group_call_join_button(self, sizer):
        self._group_call_join_btn = wx.Button(
            self.conversation_panel,
            label=self.main_window.i18n.t("group_call_join_button"),
        )
        self._group_call_join_btn.Bind(wx.EVT_BUTTON, self._on_join_ongoing_group_call)
        sizer.Add(self._group_call_join_btn, 0, wx.LEFT | wx.TOP, 5)
        self._group_call_join_btn.Hide()

    def _show_ongoing_group_call(self, call):
        self._ongoing_group_call = call
        button = self._group_call_join_btn
        changed = False
        jid = str((self.conversation or {}).get("remoteJid") or "")
        shown = (call is not None and jid.endswith("@g.us")
                 and call.get("groupJid") == jid and can_place_call(
                     self.main_window, is_video=call["isVideo"], is_group=True))
        if button.IsShown() and not shown and button.HasFocus() and can_relocate_call_focus(self):
            self.message_field.SetFocus()
        if shown:
            i18n = self.main_window.i18n
            label = (i18n.t("group_call_join_video_button") if call["isVideo"]
                     else i18n.t("group_call_join_button"))
            if button.GetLabel() != label:
                button.SetLabel(label)
                changed = True
        if button.IsShown() != shown:
            button.Show(shown)
            changed = True
        changed = self._update_call_start_buttons(jid) or changed
        # Every poll lands here; an unchanged answer must not relayout.
        if changed:
            self.conversation_panel.Layout()
            self.Layout()

    def _stop_group_call_watch(self):
        self._group_call_watch = None
        # A reply still out for the old watch is dropped by its watch check,
        # so the next chat need not wait for it before probing.
        self._group_call_probe_inflight = None
        timer = getattr(self, "_group_call_timer", None)
        if timer is not None:
            timer.Stop()
        self._group_call_timer = None
        self._show_ongoing_group_call(None)

    def _watch_group_calls(self, jid):
        conversation = self.conversation
        watch = getattr(self, "_group_call_watch", None)
        if watch is not None and watch[0] is conversation:
            return
        self._stop_group_call_watch()
        if not conversation or not jid.endswith("@g.us"):
            return
        watch = (conversation, object())
        self._group_call_watch = watch

        def current():
            return (getattr(self, "_group_call_watch", None) is watch
                    and self.conversation is conversation
                    and not getattr(self.main_window, "_shutting_down", False))

        def schedule():
            if current():
                self._group_call_timer = wx.CallLater(self._GROUP_CALL_POLL_MS, tick)

        def tick():
            if not current():
                return
            main = self.main_window
            if (not conversation_in_view(self)
                    or getattr(self, "_group_call_probe_inflight", None) is not None):
                schedule()
                return
            if (getattr(main, "_active_voice_call", None) is not None
                    or getattr(main, "_active_incoming_calls", {})):
                self._show_ongoing_group_call(None)
                schedule()
                return
            self._group_call_probe_inflight = watch

            def finish(call):
                if getattr(self, "_group_call_probe_inflight", None) is watch:
                    self._group_call_probe_inflight = None
                if not current():
                    return
                if (not conversation_in_view(self)
                        or getattr(main, "_active_voice_call", None) is not None
                        or getattr(main, "_active_incoming_calls", {})):
                    call = None
                self._show_ongoing_group_call(call)
                schedule()

            def worker():
                call = None
                try:
                    response = main._raise_for_call_response(
                        main._post_call_control("group/ongoing", {"groupJid": jid}, timeout=20),
                        "group/ongoing",
                    )
                    body = response.json()
                    if not isinstance(body, dict) or "response" not in body:
                        raise ValueError("Invalid ongoing call response")
                    call = body["response"]
                    if call is not None and (
                        not isinstance(call, dict) or not isinstance(call.get("id"), str)
                        or not call["id"] or call.get("groupJid") != jid
                        or not isinstance(call.get("isVideo"), bool)
                    ):
                        raise ValueError("Invalid ongoing call response")
                except Exception:
                    call = None
                    logging.warning("[call] ongoing group call check unavailable")
                wx.CallAfter(finish, call)

            threading.Thread(target=worker, daemon=True, name="group-ongoing-call").start()

        wx.CallAfter(tick)

    def _on_join_ongoing_group_call(self, _event=None):
        call = getattr(self, "_ongoing_group_call", None)
        conversation = self.conversation
        if not call or not conversation or not conversation_in_view(self):
            return
        jid = str(conversation.get("remoteJid") or "")
        if not jid.endswith("@g.us") or call["groupJid"] != jid:
            return
        name = self.conversation_name or conversation.get("name") or ""
        self.main_window._start_call(jid, name, is_group=True,
                                     is_video=call["isVideo"], join_call_id=call["id"])
