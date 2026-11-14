"""StatusInteractionsMixin — part of StatusPanel (see status_tab/__init__.py).

Moved verbatim out of status_panel.py. Methods run with ``self`` bound to
the StatusPanel instance, so every attribute set in StatusPanel.__init__/
init_UI is available here.
"""

import logging
import threading
import wx
from core.utils import normalize_line_separators


class StatusInteractionsMixin:
    """Liking and replying to a status.
    """

    # ── Like / unlike status ─────────────────────────────────────────────────

    # Cap on how many liked-status ids settings.json keeps. Keeping the most
    # recent ones is what matters: an old status has long since expired, so
    # nobody will ever ask "was this one liked?" again anyway.
    _MAX_REMEMBERED_LIKES = 500

    def _is_status_liked(self, status_id: str) -> bool:
        """Was this status already "liked"?

        _liked_statuses only ever gets populated for likes sent THIS
        session — it starts empty on every launch, so reopening a status
        liked before restarting used to always show "Curtir" again with
        no way to tell it had already been done. Persisted in
        settings.json (settings["status_panel"]["liked_status_ids"]) so it
        survives a restart. Native status reactions are not stored as normal
        private-chat messages, so there is no message-history row to infer this
        state from after relaunching WinZapp.
        """
        if status_id in self._liked_statuses:
            return self._liked_statuses[status_id]
        remembered = self.main_window.settings.get("status_panel", {}).get("liked_status_ids", [])
        return bool(status_id) and status_id in remembered

    def _on_like_status(self, event):
        """Toggle the native heart reaction on the displayed status.

        This must go through ``react-message`` with a status@broadcast key.
        Sending a literal heart with ``send_text_message`` creates an ordinary
        private message, which is observably different from WhatsApp's Status
        Like button. The patched Node route resolves the status in the
        poster's StatusV3Model, just as the status-reply route does.
        """
        if self._selected_contact_idx < 0:
            return
        entry    = self._status_contacts[self._selected_contact_idx]
        statuses = entry.get("statuses", [])
        if not statuses:
            return
        status     = statuses[self._current_status_idx]
        status_key = status.get("key", {})
        status_id  = status_key.get("id", "")
        if not status_id:
            return

        is_liked = self._is_status_liked(status_id)

        sender_jid = (
            status_key.get("participant", "")
            or entry.get("jid", "")
        )
        if not sender_jid:
            return

        # API-normalized statuses normally already carry both fields. The
        # fallbacks keep WebSocket-cache records and older stored records just
        # as reactable without mutating the status displayed by the panel.
        reaction_key = dict(status_key)
        reaction_key["remoteJid"] = "status@broadcast"
        if not reaction_key.get("participant"):
            reaction_key["participant"] = sender_jid

        mw = self.main_window

        def _do_like():
            try:
                ok = bool(mw.send_reaction(
                    "status@broadcast", reaction_key, "" if is_liked else "❤️"
                ))
            except Exception:
                ok = False
            if ok:
                wx.CallAfter(self._on_like_sent, status_id, not is_liked)
            else:
                wx.CallAfter(
                    wx.MessageBox,
                    mw.i18n.t("status_like_error"),
                    mw.app_name,
                    wx.OK | wx.ICON_ERROR,
                )

        threading.Thread(target=_do_like, daemon=True).start()

    def _on_like_sent(self, status_id: str, liked: bool = True):
        self._liked_statuses[status_id] = liked

        mw = self.main_window
        section = mw.settings.setdefault("status_panel", {})
        remembered = section.setdefault("liked_status_ids", [])
        settings_changed = False
        if liked and status_id not in remembered:
            remembered.append(status_id)
            if len(remembered) > self._MAX_REMEMBERED_LIKES:
                del remembered[:len(remembered) - self._MAX_REMEMBERED_LIKES]
            settings_changed = True
        elif not liked and status_id in remembered:
            remembered.remove(status_id)
            settings_changed = True
        if settings_changed:
            mw.save_settings()

        # The status shown may have changed while the send was in flight
        # (Ctrl+Left/Right) — only touch the button if it's still this one.
        if (self._current_status or {}).get("key", {}).get("id") == status_id:
            self._like_btn.SetLabel(
                mw.i18n.t("status_unlike") if liked else mw.i18n.t("status_like")
            )

    # ── Reply to the currently viewed status ─────────────────────────────────

    def _on_reply_field_text_changed(self, event):
        """Send button only makes sense once there's something to send —
        hide it while the reply field is empty."""
        self._reply_send_btn.Show(bool(self._reply_field.GetValue().strip()))
        self.Layout()
        if event is not None:
            event.Skip()

    def _on_send_status_reply(self, event):
        status = self._current_status
        entry  = self._current_status_entry
        if status is None or entry is None:
            return
        if status.get("key", {}).get("fromMe"):
            return  # no reply UI for own statuses — see _show_current_status()
        text = normalize_line_separators(self._reply_field.GetValue()).strip()
        if not text:
            return
        poster_jid = entry.get("jid", "")
        if not poster_jid:
            return
        threading.Thread(
            target=self._send_status_reply_bg,
            args=(poster_jid, text, status),
            daemon=True,
        ).start()

    def _send_status_reply_bg(self, poster_jid: str, text: str, status: dict):
        mw = self.main_window
        try:
            # Status messages live in WhatsApp Web's per-poster StatusV3Model,
            # not in the ordinary chat message collection.  The patched Node
            # send-reply route resolves this serialized status key in that
            # model before sending, so keep the status as the quote target
            # here instead of degrading the reply to a normal DM.
            result = mw.send_text_message(poster_jid, text, quoted=status)
        except Exception:
            logging.exception(
                "[status-reply] send_text_message raised for %s", poster_jid)
            result = None
        # send_text_message() returns a message-id string or True on success,
        # or a dict ({"ok": False, ...}) on a definite failure.
        ok = bool(result) and not isinstance(result, dict)
        if ok:
            wx.CallAfter(self._on_status_reply_sent)
        else:
            # The dialog can only say "it failed"; this is the only place that
            # can say WHY. Reported live — "ao teclar enter deu Não foi
            # possível enviar a resposta ao status", and the same text sent
            # fine from the button seconds later — and the log held nothing at
            # all about it, so there was no way to tell a rejected JID from a
            # dropped connection from a server-side refusal. Enter and the
            # button are the same handler (see the two Bind calls in
            # _build_viewer), so the difference was never the key pressed.
            logging.warning(
                "[status-reply] failed for poster=%s (result=%r, text_len=%d)",
                poster_jid, result, len(text),
            )
            wx.CallAfter(
                wx.MessageBox,
                mw.i18n.t("status_reply_error"),
                mw.app_name,
                wx.OK | wx.ICON_ERROR,
            )

    def _on_status_reply_sent(self):
        self._reply_field.SetValue("")
        # SetValue("") above fires EVT_TEXT -> _on_reply_field_text_changed(),
        # which hides _reply_send_btn now that the field is empty again —
        # without refocusing the field itself here, keyboard focus was left
        # on that now-hidden button with nothing to land on.
        self._reply_field.SetFocus()
        self.main_window.output(self.main_window.i18n.t("status_reply_sent"))
