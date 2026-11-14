"""The error of the pairing-code request, in the format the client reads.

The client (websocket_client.on_wpp_phone_code_error) shows `name: message` and
decides whether WhatsApp refused because of the quota with `rateLimited` (or by
reading "rate-overlimit" in the text). The quota is per phone number and
outlives the process: repeating a request refused because of it is what keeps
it alive (docs/traps/pairing-flow.md). Pure functions, tested in test_pairing.py.

`phone_candidates` covers the Brazilian 9th digit. The code is asked for the
account's own number exactly as WhatsApp keys it (whatsmeow sends the digits
as the `jid` of link_code_companion_reg, and so does WhatsApp Web; neither
normalizes), and a Brazilian mobile may be keyed with or without its 9th
digit. Reported: on Neonize a user's number only paired once she left the 9
out. Both forms are tried, the likelier one first.
"""
import re

_QUOTA = re.compile(r"rate-?overlimit|\b429\b", re.IGNORECASE)
_LONG_NUMBERS = re.compile(r"\d{7,}")
MESSAGE_LIMIT = 200


def code_error(error) -> dict:
    """The `phoneCodeError` payload for the exception `error`. The text never
    carries a phone number: sequences of 7 or more digits become `<n>`."""
    name = type(error).__name__
    text = _LONG_NUMBERS.sub("<n>", str(error))
    return {
        "name": "LinkCodeError",
        "message": f"{name}: {text}"[:MESSAGE_LIMIT] if text else name,
        "rateLimited": bool(_QUOTA.search(f"{name} {text}")),
    }


#: Brazilian area codes whose mobiles WhatsApp usually keys WITH the 9th digit
#: (where the digit came first, 2012-2013); elsewhere the account is usually
#: keyed without it. Only an order: the other form is tried too.
_NINE_FIRST_AREAS = range(11, 29)


def phone_candidates(digits: str) -> list:
    """The numbers to ask a pairing code for, in order: a Brazilian mobile in
    both its forms (with and without the 9th digit), the likelier one first;
    any other number as it is."""
    digits = "".join(ch for ch in str(digits or "") if ch.isdigit())
    if not digits.startswith("55") or len(digits) not in (12, 13):
        return [digits]
    area = int(digits[2:4])
    if len(digits) == 13 and digits[4] == "9":
        with_nine, without = digits, digits[:4] + digits[5:]
    elif len(digits) == 12 and digits[4] in "6789":    # landlines start with 2-5
        with_nine, without = digits[:4] + "9" + digits[4:], digits
    else:
        return [digits]
    return [with_nine, without] if area in _NINE_FIRST_AREAS else [without, with_nine]
