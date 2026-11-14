"""Split of client/status_panel.py (StatusPanel, the Alt+5 tab) into
client/status_tab/. Run on refactor/split-god-files at 10799e58."""

SRC = "client/status_panel.py"
CLASS = "StatusPanel"
PKG = "status_tab"
PKG_DIR = "client/status_tab"
IMPORT_PREFIX = "status_tab."

REEXPORT_COMMENT = (
    "# StatusPanel is assembled from the mixins in status_tab/ (one module per\n"
    "# responsibility — see status_tab/__init__.py for the map). The helpers and\n"
    "# the two status dialogs are re-exported here because tests and callers\n"
    "# reach them as status_panel.<name>; new code should import them from their\n"
    "# module."
)

ANCHORS = [
    ("__init__", "KEEP"),
    ("_load_statuses", "status_loading"),
    ("_set_list_loading", "status_list"),
    ("_open_my_status_dialog", "status_viewer"),
    ("_is_status_liked", "status_interactions"),
    ("_on_video_frame_size_known", "status_media"),
    ("_on_reply_field_text_changed", "status_interactions"),
    ("_on_add_status", "status_composer"),
    ("_on_ctrl_r_shortcut", "status_voice"),
    ("_on_send_text_status", "status_composer"),
    ("refresh_labels", "KEEP"),
]

MODULE_DEFS = {
    "_post_was_rejected": "status_rules",
    "_download_status_media": "status_rules",
    "_status_content_label": "status_rules",
    "_STATUS_MIME_SUBTYPE_TO_EXT": "status_rules",
    "_status_media_extension": "status_rules",
    "_status_media_save_info": "status_rules",
    "StatusReactionsDialog": "status_dialogs",
    "MyStatusDialog": "status_dialogs",
}

HELPER_DOCS = {
    "status_rules": "Pure helpers of the Status tab: post-result checks, the status content\nlabel, media download and the save-as extension table.\n\nMoved verbatim out of status_panel.py, which re-exports every name.\n",
    "status_dialogs": "The Status tab's two dialogs: who reacted to a status, and my own status.\n\nMoved verbatim out of status_panel.py, which re-exports both.\n",
}

MIXIN_NAMES = {
    "status_loading": "StatusLoadingMixin",
    "status_list": "StatusListMixin",
    "status_viewer": "StatusViewerMixin",
    "status_interactions": "StatusInteractionsMixin",
    "status_media": "StatusMediaMixin",
    "status_composer": "StatusComposerMixin",
    "status_voice": "StatusVoiceMixin",
}
MIXIN_ORDER = list(MIXIN_NAMES)

MIXIN_DOCS = {
    "status_loading": "Loading statuses: the API fetch, parsing, merging with the local cache and my-status reconciliation.",
    "status_list": "The contacts-with-status list: populating it, row text, key handling, selection and activation.",
    "status_viewer": "Viewing statuses: my-status dialog, the media viewer, the legacy viewer, previous/next and viewed marks.",
    "status_interactions": "Liking and replying to a status.",
    "status_media": "A status's media: video playback, copying the text and saving the file.",
    "status_composer": "Posting a status: the composer panels and sending text and media statuses.",
    "status_voice": "Recording, previewing and posting a voice status.",
}

MIXIN_FILE_DOCS = {m: f"{MIXIN_NAMES[m]} — part of StatusPanel (see status_tab/__init__.py).\n\nMoved verbatim out of status_panel.py. Methods run with ``self`` bound to\nthe StatusPanel instance, so every attribute set in StatusPanel.__init__/\ninit_UI is available here.\n" for m in MIXIN_NAMES}

FILE_FIX = {}
POST = {}
