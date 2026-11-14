"""StatusAIMixin — part of StatusPanel (see status_tab/__init__.py).

Describe a photo or video status with the AI providers the person set up in
Settings, from the inline viewer (the Describe button, Ctrl+Shift+I) and from
the separate media viewer. Which provider answers and under which consent is
core/ai_media's business and the result window's
(ui/dialogs/ai_result_dialog.py, opened through ui/ai_media_launch.py); this
file only finds the status and downloads its original.

Methods run with ``self`` bound to the StatusPanel instance.
"""
from core.ai_media.config import MAX_SOURCE_BYTES
from core.ai_media.errors import DescriptionError
from status_tab.status_rules import _download_status_media
from ui import ai_media_launch


class StatusAIMixin:
    """AI description of the status under the viewer."""

    def _status_ai_loader(self, snapshot, kind):
        """Callable returning the status's original bytes, never keeping more
        than the kind's size limit even when its metadata understates it."""
        mw = self.main_window
        limit = MAX_SOURCE_BYTES[kind]
        info = (snapshot.get("message") or {}).get(snapshot.get("messageType")) or {}
        try:
            declared = int(info.get("fileLength", 0))
        except (TypeError, ValueError):
            declared = 0

        def loader(token):
            if declared > limit:
                raise DescriptionError("media_size")
            token.check()
            try:
                data = _download_status_media(mw, snapshot)
            except Exception:
                token.check()
                raise DescriptionError("media") from None
            token.check()
            if len(data) > limit:
                raise DescriptionError("media_size")
            return data
        return loader

    def _status_describe_label(self, status):
        """Label of the Describe button for ``status``, "" when not offered."""
        if not isinstance(status, dict):
            return ""
        return ai_media_launch.describe_label(self.main_window, status)

    def _describe_status(self, status, parent=None):
        if isinstance(status, dict):
            ai_media_launch.describe(parent or self, self.main_window, status, self._status_ai_loader)

    def _update_status_describe_button(self):
        """Show the inline Describe button under the same rule as the message
        menu: only on a status the feature offers an action for."""
        label = self._status_describe_label(getattr(self, "_current_status", None))
        if label:
            self._describe_status_btn.SetLabel(label)
        self._describe_status_btn.Show(bool(label))

    def _on_describe_status(self, event=None):
        """Describe button and Ctrl+Shift+I: act on the status being shown."""
        if self._viewer_panel.IsShown() and self._describe_status_btn.IsShown():
            self._describe_status(self._current_status)

    def _viewer_describe_label(self, item):
        return self._status_describe_label(item.get("status"))

    def _viewer_describe_status(self, item, parent):
        self._describe_status(item.get("status"), parent)
