"""Two message routes that were missing: `all-new-messages` (what arrived since
the previous call) and `send-status` (post a text status).

`all-new-messages`: each session has a cursor in the bridge's memory, the
position (rowid) of the last store message that was already delivered. The route
returns the messages stored after it, received from other people (mine, the
status board and the "deleted" notices stay out), and advances the cursor. The
first call of a session only marks the starting point and answers empty.
Limits, stated on purpose:
- the cursor goes away when the bridge restarts (the first call afterwards starts over);
- the history the phone sends on pairing also reaches the store, so the call
  right after it returns all of it (in slices of LIMIT);
- WPPConnect does not document this route's format; the response is the plain
  list of messages, like `all-unread-messages`.

`send-status`: WPPConnect posts the text of `message` to status@broadcast;
here it goes out like `send-text-storie` (text status), through server.py's
`publish_status`.

Nothing here was tested against a real account. The pure functions are at the top
(tested in test_chat_new.py); `register_routes` wires the routes to the server.
"""
import json

LIMIT = 5000         # messages per call; the rest comes in the next call


def last_rowid(db) -> int:
    """The position of the most recent stored message (0 if there is none)."""
    with db._lock:
        return int(db._conn.execute("SELECT COALESCE(MAX(rowid), 0) FROM msgs").fetchone()[0])


def stored_after(db, rowid, limit=LIMIT):
    """[(rowid, message in WPPConnect format)] stored after `rowid`, from the
    oldest to the newest. Reads the store's SQLite directly: the store has no
    such query and store.py belongs to another area."""
    with db._lock:
        rows = db._conn.execute(
            "SELECT rowid, data FROM msgs WHERE rowid>? ORDER BY rowid LIMIT ?",
            (rowid, limit)).fetchall()
    return [(l["rowid"], json.loads(l["data"])) for l in rows]


def is_new_received(message) -> bool:
    """A message from another person that deserves to show up as new."""
    if message.get("fromMe") or message.get("isStatus"):
        return False
    return message.get("type") != "revoked"


def new_and_cursor(rows, cursor):
    """([new messages], new cursor) from the `rows` of stored_after: the cursor
    passes through all the rows read, even the ones that do not count."""
    if not rows:
        return [], cursor
    return [m for _, m in rows if is_new_received(m)], rows[-1][0]


def status_text(body) -> str:
    """The text of `send-status` (field `message`, or `text`), or ValueError."""
    text = body.get("message") if isinstance(body, dict) else None
    if text in (None, "") and isinstance(body, dict):
        text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("message is required")
    return text


def register_routes(r, *, session, ok, error, publish_status, text_status):
    """Wire the routes to the aiohttp router `r`. `publish_status` and
    `text_status` are server.py's (the same path as send-text-storie)."""
    cursors = {}        # session name -> rowid of the last delivered message

    async def all_new_messages(req):
        s = session(req)
        cursor = cursors.get(s.name)
        if cursor is None:
            cursors[s.name] = last_rowid(s.db)
            return ok(status="success", response=[])
        new_messages, cursors[s.name] = new_and_cursor(stored_after(s.db, cursor), cursor)
        return ok(status="success", response=new_messages)

    async def send_status(req):
        try:
            body = await req.json()
            text = status_text(body)
        except ValueError as e:
            return error(e, 400)
        return await publish_status(req, lambda s, destination, _: text_status(
            s, destination, {"text": text, "options": body.get("options")}))

    r.add_get("/api/{tok}/all-new-messages", all_new_messages)
    r.add_post("/api/{tok}/send-status", send_status)
