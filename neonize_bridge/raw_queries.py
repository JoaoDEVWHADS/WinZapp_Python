"""Raw info queries (IQ) and MEX (GraphQL) queries through WinZapp's neonize
build (`send_iq` / `send_mex`, neonize_patches/neonize/0006): what whatsmeow
has no function for. The stanzas the routes send were read from WhatsApp Web's
own modules over CDP (see each route's module); this file only carries them.

A node is {"tag", "attrs", "content"}: content a list of nodes, a string or
{"bytes": base64}; an attribute {"jid": "..."} is sent as a JID. In an answer,
attributes are strings.
"""


class QueryError(Exception):
    """The server refused the query (`code` is its error code, 0 when there was
    none: a timeout, a disconnected client), or the build cannot send it."""

    def __init__(self, message, code=0):
        super().__init__(message)
        self.code = int(code or 0)


def available(client) -> bool:
    """Can this client send raw queries (WinZapp's neonize build)?"""
    if client is None or not hasattr(client, "send_iq"):
        return False
    try:
        from neonize._binder import gocode
    except ImportError:
        return False
    return hasattr(gocode, "SendIQ")


def node(tag, attrs=None, content=None) -> dict:
    out = {"tag": tag}
    if attrs:
        out["attrs"] = attrs
    if content is not None:
        out["content"] = content
    return out


def jid(text) -> dict:
    """An attribute value sent as a JID."""
    return {"jid": str(text)}


def children(parent, tag=None) -> list:
    """The child nodes of `parent` (with `tag`, only those)."""
    content = (parent or {}).get("content")
    if not isinstance(content, list):
        return []
    return [c for c in content if isinstance(c, dict) and (tag is None or c.get("tag") == tag)]


def child(parent, tag):
    found = children(parent, tag)
    return found[0] if found else None


def text(node) -> str:
    """The text a node carries ('' when none): the answer's bytes, decoded."""
    import base64
    content = (node or {}).get("content")
    if isinstance(content, dict) and isinstance(content.get("bytes"), str):
        try:
            return base64.b64decode(content["bytes"]).decode("utf-8", "replace")
        except ValueError:
            return ""
    return content if isinstance(content, str) else ""


def child_text(parent, tag) -> str:
    return text(child(parent, tag))


def attr(node, name, default="") -> str:
    return str(((node or {}).get("attrs") or {}).get(name, default))


def answer_node(answer) -> dict:
    """The response node of a send_iq answer, or QueryError."""
    if not isinstance(answer, dict):
        raise QueryError("no answer")
    if "error" in answer:
        raise QueryError(answer.get("text") or answer["error"], answer.get("code", 0))
    found = answer.get("node")
    if not isinstance(found, dict):
        raise QueryError("no response node")
    return found


def answer_data(answer, field) -> dict:
    """`data[field]` of a send_mex answer, or QueryError."""
    if not isinstance(answer, dict):
        raise QueryError("no answer")
    data = answer.get("data")
    value = data.get(field) if isinstance(data, dict) else None
    if answer.get("error") or value is None:
        raise QueryError(answer.get("error") or f"{field} missing")
    return value


def send_iq(client, query) -> dict:
    """Sends one IQ; the response node, or QueryError. Runs on a thread."""
    if not available(client):
        raise QueryError("this neonize build sends no raw queries")
    return answer_node(client.send_iq(query))


def send_mex(client, query_id, variables, field) -> dict:
    """Runs one MEX query; `data[field]`, or QueryError. Runs on a thread."""
    if not available(client):
        raise QueryError("this neonize build sends no raw queries")
    return answer_data(client.send_mex(query_id, variables), field)
