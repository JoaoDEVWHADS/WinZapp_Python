import os
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


