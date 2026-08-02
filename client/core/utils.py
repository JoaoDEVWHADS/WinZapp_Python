import os
import re
import json
import base64
import requests
from cryptography.fernet import Fernet

def generate_and_save_key(filepath):
    key = Fernet.generate_key()
    with open(filepath, 'wb') as key_file:
        key_file.write(key)
    return key

def retrieve_key(filepath):
    with open(filepath, 'rb') as key_file:
        key = key_file.read()
    return key

def encrypt(data, key):
    fernet = Fernet(key)
    #Encode only if data is string
    if isinstance(data, str):
        data = data.encode()
    encrypted_data = fernet.encrypt(data)
    return encrypted_data

def decrypt(encrypted_data, key):
    fernet = Fernet(key)
    decrypted_data = fernet.decrypt(encrypted_data)
    return decrypted_data.decode()

def decrypt_bytes(encrypted_data, key):
    fernet = Fernet(key)
    return fernet.decrypt(encrypted_data)

def _sanitize_for_json(obj):
    """Recursively convert bytes values to base64 strings so json.dumps never raises."""
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in list(obj.items())}
    if isinstance(obj, list):
        return [_sanitize_for_json(item) for item in list(obj)]
    return obj

def encrypt_json(data, key):
    fernet = Fernet(key)
    json_data = json.dumps(_sanitize_for_json(data)).encode()
    encrypted_data = fernet.encrypt(json_data)
    return encrypted_data

def decrypt_json(encrypted_data, key):
    fernet = Fernet(key)
    decrypted_data = fernet.decrypt(encrypted_data)
    data = json.loads(decrypted_data.decode())
    return data

def is_phone_like(name: str) -> bool:
    """Return True if name looks like a phone number rather than a display name.

    Also rejects purely-numeric strings of any length (e.g. "0") — those are
    WPPConnect API fallbacks from contact.id.split('@')[0] when no real name is
    available, not actual display names.
    """
    if not name:
        return False
    stripped = name.strip()
    if stripped.isdigit():
        return True  # "0", "123", "5511999999999" — never a real name
    digit_count = sum(1 for c in stripped if c.isdigit())
    return digit_count >= 7 and digit_count >= len(stripped) * 0.7

def looks_like_binary_blob(value) -> bool:
    """Return True if value looks like base64 image/thumbnail data, not a name.

    Business accounts and some vCards leak a ``jpegThumbnail`` (or other binary
    blob) into name fields, which then surfaced in the chat list as garbage like
    ``+0 /9j/4AAQSkZJRg...``. Such values must never be treated as display names.
    """
    if not value or not isinstance(value, str):
        return False
    s = value.strip()
    if not s:
        return False
    # Common base64 image/data signatures (JPEG, PNG, GIF, SVG, data URIs).
    if s.startswith(("/9j/", "iVBORw0", "R0lGOD", "data:image", "PHN2Zy", "JVBER")):
        return True
    # A long, spaceless string drawn entirely from the base64 alphabet is
    # overwhelmingly binary data rather than a human name.
    if len(s) > 64 and " " not in s and re.fullmatch(r"[A-Za-z0-9+/=_-]+", s):
        return True
    return False

def _slim_quoted_message(quoted):
    """Reduce a quoted-message dict to only what the reply preview needs.

    WPPConnect embeds the *entire* quoted message under
    ``contextInfo.quotedMessage`` — including the base64 thumbnail, mediaKey,
    directPath, deprecatedMms3Url, file hashes, etc. None of that is read by the
    UI (the preview only shows a short text or a type label), yet it dominated
    messages.dat and slowed every conversation that had replies. This keeps just
    a capped text preview plus a type marker.
    """
    if not isinstance(quoted, dict):
        return quoted
    text = (
        quoted.get("conversation")
        or quoted.get("caption")
        or quoted.get("body")
        or (quoted.get("extendedTextMessage") or {}).get("text")
        or ""
    )
    if not isinstance(text, str) or looks_like_binary_blob(text):
        text = ""
    text = text[:300]  # a long pasted message must not be duplicated into replies

    qtype = quoted.get("type")
    slim: dict = {}
    if qtype and qtype not in ("chat", "text"):
        slim["type"] = qtype
        if text:
            slim["caption"] = text
    elif text:
        slim["conversation"] = text
    else:
        # No usable text — preserve a media type marker so the preview can still
        # render a localized label ("Photo", "Audio", …).
        for k in ("imageMessage", "videoMessage", "audioMessage",
                  "documentMessage", "stickerMessage", "contactMessage"):
            if k in quoted:
                slim[k] = {}
                break
    return slim


# Heavy media fields that arrive from the API but are never read by the client:
# media is (re)downloaded by message id via /get-media-by-message, and voice
# notes live in the voice_messages folder — so urls, encryption keys, hashes and
# waveforms are pure dead weight inside messages.dat. jpegThumbnail is kept
# because the inline-thumbnail view uses it.
_HEAVY_MEDIA_FIELDS = frozenset({
    "url", "directPath", "mediaKey", "mediaKeyTimestamp", "deprecatedMms3Url",
    "fileSha256", "fileEncSha256", "filehash", "encFilehash",
    "thumbnailDirectPath", "thumbnailSha256", "thumbnailEncSha256",
    "streamingSidecar", "waveform", "midQualityFileSha256",
    "midQualityFileEncSha256", "scansSidecar", "scanLengths",
    "firstScanSidecar", "firstScanLength", "rawMediaData", "body",
})


def prune_message_record(msg):
    """Strip stored bloat from a single message record (mutates and returns it).

    - Slims ``contextInfo.quotedMessage`` wherever it appears.
    - Removes heavy, never-read media fields (urls, mediaKey, hashes, waveform…)
      from each message sub-type so audio/image/video records stay tiny.

    Returns True if anything was changed.
    """
    if not isinstance(msg, dict):
        return False
    changed = False

    def _prune_ctx(ctx):
        nonlocal changed
        if isinstance(ctx, dict):
            q = ctx.get("quotedMessage")
            if isinstance(q, dict):
                slim = _slim_quoted_message(q)
                if slim != q:
                    ctx["quotedMessage"] = slim
                    changed = True

    _prune_ctx(msg.get("contextInfo"))
    m = msg.get("message")
    if isinstance(m, dict):
        for sub in m.values():
            if isinstance(sub, dict):
                _prune_ctx(sub.get("contextInfo"))
                for k in _HEAVY_MEDIA_FIELDS & sub.keys():
                    del sub[k]
                    changed = True
    return changed


def prune_chats_messages(chats) -> bool:
    """Prune every stored message in a chats dict in place. Returns True if any
    record changed (so the caller can persist the slimmed data once)."""
    changed = False
    if not isinstance(chats, dict):
        return False
    for chat in chats.values():
        try:
            records = (
                chat.get("messages", {}).get("messages", {}).get("records", [])
            )
        except AttributeError:
            continue
        for rec in records:
            if prune_message_record(rec):
                changed = True
    return changed


def effective_unread_count(chat) -> int:
    """A chat's unread count, suppressed only when it would open empty.

    The problem this guards against: a chat-list sync can report e.g.
    unreadCount=2 for a chat whose per-chat message fetch previously failed (or
    hasn't run yet), leaving 0 messages in the local store — showing "2 unread"
    on a conversation that opens completely empty.

    This used to return ``min(reported, local_count)``, which fixed that case
    but silently capped every count at however many messages the last fetch
    happened to bring back. WhatsApp Web's message store only holds a handful
    of messages per chat right after a pairing (measured: ~15), so a group with
    5747 unread announced "15" — badly wrong for a screen-reader user deciding
    what to open, and indistinguishable from a group with exactly 15.

    Having *some* history is enough to know the conversation is real and opens
    with content; beyond that, the server's own count is the honest number, and
    the one the app should report. Callers that need a count bounded by what is
    actually on screen (the unread separator in conversations.py) already check
    that themselves.
    """
    if not isinstance(chat, dict):
        return 0
    reported = int(chat.get("unreadCount") or 0)
    if reported <= 0:
        return 0
    try:
        local_count = len(
            chat.get("messages", {}).get("messages", {}).get("records", []) or []
        )
    except AttributeError:
        local_count = 0
    if local_count == 0:
        return 0
    return reported


_CC_SORTED: list[str] | None = None

def _known_country_codes() -> list[str]:
    """Return country codes sorted longest-first (cached). Thread-safe for reads."""
    global _CC_SORTED
    if _CC_SORTED is None:
        try:
            try:
                from client.countries import COUNTRIES
            except ImportError:
                from countries import COUNTRIES
            _CC_SORTED = sorted({code for _, code in COUNTRIES}, key=len, reverse=True)
        except Exception:
            _CC_SORTED = []
    return _CC_SORTED

def format_number(string_number):
    """Format a raw digit string (or JID) as a human-readable phone number.

    Brazil (+55): +55 DD XXXXX-XXXX or +55 DD XXXX-XXXX
    All other countries: +CC local  (no area-code assumptions)
    Falls back to '+<digits>' if no known country code matches.
    """
    digits = "".join(c for c in string_number.split('@')[0] if c.isdigit())
    if not digits:
        return string_number

    # Do not format LID JIDs (which are 15-digit internal identifiers) as phone numbers
    if "@lid" in string_number or len(digits) >= 14:
        return digits

    cc = None
    for candidate in _known_country_codes():
        if digits.startswith(candidate):
            cc = candidate
            break

    if cc is None:
        return f"+{digits}"

    local = digits[len(cc):]

    if cc == "55":
        ddd = local[:2]
        rest = local[2:]
        if not ddd:
            return f"+{cc}"
        if not rest:
            return f"+{cc} {ddd}"
        if len(rest) == 9:
            return f"+{cc} {ddd} {rest[:5]}-{rest[5:]}"
        split = max(len(rest) - 4, 1)
        return f"+{cc} {ddd} {rest[:split]}-{rest[split:]}"

    # Generic international
    return f"+{cc} {local}" if local else f"+{cc}"

def parse_bool_flag(value):
    """Interpret a WPPConnect boolean-ish field, or None when it says nothing.

    Chat flags (``archive``, ``pin``) come back as real booleans, as the
    strings "true"/"false", as 0/1, or missing entirely depending on the
    endpoint and API version.  A plain ``bool(value)`` is wrong for the string
    form — ``bool("false")`` is True — and that is exactly how conversations
    the user never archived ended up in the Archived tab.  Returning None for
    "not stated" lets callers leave the local state untouched.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes"):
            return True
        if v in ("false", "0", "no", "", "none", "null"):
            return False
    return None


def check_internet_connection(test_url="https://www.google.com", timeout=10):
    try:
        response = requests.get(test_url, timeout=timeout)
        return True
    except (requests.ConnectionError, requests.Timeout):
        return False


def mute_response_accepted(http_ok: bool, body: str, is_unmute: bool) -> bool:
    """Decide whether a WPPConnect /send-mute reply means "state applied".

    Any 2xx is a success. Beyond that, an older/unpatched WPPConnect routes
    /send-mute through the legacy ``WAPI.sendMute`` shim, which answers HTTP
    500 with ``{"erro": true, "text": "This chat is already mute"}`` (or "is
    not mute to remove" when unmuting) for *any* internal non-200 — including
    the perfectly ordinary case of the chat already being in the state we
    asked for. Treating those as failures rolled the optimistic local change
    back and showed the user an error for a no-op, which is why muting looked
    completely broken. The real fix is the patched sendMute controller (which
    drives ``WPP.chat.mute``); this keeps the client correct against an API
    build that predates it.
    """
    if http_ok:
        return True
    text = (body or "").lower()
    if is_unmute:
        return "is not mute to remove" in text
    return "already mute" in text


def first_unread_index(displayable, unread_count: int) -> int:
    """Index of the first unread message in *displayable*, or -1.

    WhatsApp's ``unreadCount`` only ever counts messages you *received*. The
    naive ``len(displayable) - unread_count`` therefore lands in the wrong place
    whenever any of your own messages sit at the tail of the conversation —
    typically because you replied from your phone or another linked device. The
    unread separator was then drawn above your own messages, announcing them as
    unread, which is what "minhas próprias mensagens contam como não lidas"
    describes.

    Walk backwards instead, counting only incoming (``key.fromMe`` falsy)
    messages, and stop on the *unread_count*-th one. Returns -1 when the loaded
    history doesn't hold that many incoming messages (nothing sensible to
    anchor the separator to).
    """
    if unread_count <= 0:
        return -1
    seen = 0
    for idx in range(len(displayable) - 1, -1, -1):
        msg = displayable[idx]
        if not isinstance(msg, dict):
            continue
        if (msg.get("key") or {}).get("fromMe"):
            continue
        seen += 1
        if seen == unread_count:
            return idx
    return -1
