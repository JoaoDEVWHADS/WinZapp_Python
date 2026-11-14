"""Read every OCR page in order; incomplete/malformed documents are failures.

The OCR endpoint answers in Markdown meant for a renderer: links to the images
it cut out of the page, HTML entities and ``<br>`` line breaks. A screen reader
reads those literally, so they are turned into the plain text the other
providers' PDF answers already are. Headings, lists and tables are kept.
"""
import html
import re

from .errors import DescriptionError

#: ``![img-0.jpeg](img-0.jpeg)``: an image cut out of the page. Its pixels are
#: never requested (include_image_base64=false), so the link leads nowhere.
_IMAGE = re.compile(r"[ \t]*!\[[^\]\n]*\]\([^)\n]*\)")
_BREAK = re.compile(r"[ \t]*(?:<br\s*/?>(?:[ \t]*</br>)?|</br>)[ \t]*", re.IGNORECASE)
# Only an entity closed by ";": html.unescape on the whole text also expands
# legacy names written without one, turning "&notice" into "¬ice".
_ENTITY = re.compile(r"&(?:#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")


def readable_text(markdown):
    """OCR Markdown as text a screen reader reads well; the words are kept."""
    lines = []
    for line in markdown.split("\n"):
        # A table row must stay on one line or its cells fall apart.
        separator = " " if line.lstrip().startswith("|") else "\n"
        lines.append(_BREAK.sub(separator, _IMAGE.sub("", line)))
    text = _ENTITY.sub(lambda match: html.unescape(match.group()), "\n".join(lines))
    text = re.sub(r"(?m)^[ \t]+$", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_document(body):
    if not isinstance(body, dict) or not isinstance(body.get("pages"), list) or not body["pages"]:
        raise DescriptionError("response")
    pages = body["pages"]
    usage = body.get("usage_info")
    reported = usage.get("pages_processed") if isinstance(usage, dict) else None
    if reported is not None and (type(reported) is not int or reported != len(pages)):
        raise DescriptionError("response")
    by_index = {}
    for page in pages:
        if not isinstance(page, dict) or type(page.get("index")) is not int \
                or not isinstance(page.get("markdown"), str) or page["index"] in by_index:
            raise DescriptionError("response")
        by_index[page["index"]] = page["markdown"]
    if set(by_index) != set(range(len(pages))):
        raise DescriptionError("response")
    return readable_text("\n\n".join(by_index[index] for index in range(len(pages))))
