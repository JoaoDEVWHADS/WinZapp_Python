"""Word wrapping for read-only text views that must still copy the original.

The message text popup (Alt+C) wraps long lines at ~100 characters so a
screen reader user navigating line by line is not handed one enormous line.
Those breaks are a *view* of the text, not part of it: copying a selection
must return the message exactly as it was written, with only its own line
breaks.

The wrap here is therefore lossless by construction: it never adds, removes
or moves a character, it only turns the single space a line is broken at into
a newline. The wrapped string is exactly as long as the original, so any
range selected in it maps to the same range of the original — which is what
``original_range()`` returns.
"""


def normalize_newlines(text: str) -> str:
    """Collapse CRLF and lone CR into ``\\n``.

    A native multiline text control stores every line break as CRLF and
    reports them back as ``\\n``; a ``\\r`` left inside the original would make
    the control's view and our string disagree on length, and with that on
    every offset after it."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def word_wrap(text: str, width: int = 100) -> str:
    """Wrap *text* at word boundaries around *width* characters.

    Never breaks mid-word, keeps the text's own line breaks, and breaks a line
    only by replacing the space at the break with ``\\n`` — so the result has
    the same length as ``normalize_newlines(text)`` and differs from it only at
    those break positions."""
    out = []
    for para in normalize_newlines(text).split("\n"):
        pieces = []
        line_len = 0
        for i, word in enumerate(para.split(" ")):
            if i == 0:
                pieces.append(word)
                line_len = len(word)
            elif line_len == 0 or line_len + 1 + len(word) <= width:
                pieces.append(" " + word)
                line_len += 1 + len(word)
            else:
                pieces.append("\n" + word)
                line_len = len(word)
        out.append("".join(pieces))
    return "\n".join(out)


def selection_offsets(get_range, get_string_selection, frm: int, to: int):
    """Turn a text control's selection into ``(start, end)`` string offsets.

    ``frm``/``to`` are the control's native positions, and on Windows a plain
    multiline edit counts every CRLF as two of them — so they cannot index
    the string that was set. ``get_range(0, frm)`` and
    ``get_string_selection()`` both come back with plain ``\\n``, so their
    lengths are the offsets into that string. ``None`` for an empty
    selection."""
    if frm == to:
        return None
    start = len(get_range(0, frm))
    return start, start + len(get_string_selection())


def original_range(original: str, start: int, end: int) -> str:
    """Return the part of *original* shown at ``[start, end)`` of its wrap.

    Offsets are Python string offsets into ``word_wrap(original)``. Because
    the wrap is length-preserving the same offsets index the (newline
    normalized) original, whose spaces are still spaces where the wrap put a
    break."""
    source = normalize_newlines(original)
    start = max(0, min(start, len(source)))
    end = max(start, min(end, len(source)))
    return source[start:end]
