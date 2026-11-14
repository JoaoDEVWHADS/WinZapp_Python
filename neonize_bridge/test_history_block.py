"""A history block is stored in a few transactions (Session._store_history_block),
not a commit per chat and per name: those held the store's lock long enough
to stall every route and drop the client's socket."""
from types import SimpleNamespace as N

from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message

import server
from store import Store


class Counting:
    """The store, counting the per-item writes the block must not use."""

    def __init__(self, store):
        self.store, self.single = store, 0

    def chat(self, *a, **k):
        self.single += 1
        return self.store.chat(*a, **k)

    def contact(self, *a, **k):
        self.single += 1
        return self.store.contact(*a, **k)

    def __getattr__(self, name):
        return getattr(self.store, name)


def conversation(jid, n, unread=None):
    messages = [N(message=N(key=N(fromMe=False, ID=f"{jid[:3]}{i}", participant=""),
                            participant="", messageTimestamp=100 + i,
                            message=Message(conversation=f"m{i}"), pushName="Ana",
                            starred=False)) for i in range(n)]
    c = N(ID=jid, name="Chat " + jid[:3], displayName="", conversationTimestamp=200,
          lastMsgTimestamp=0, messages=messages,
          HasField=lambda f, u=unread: f == "unreadCount" and u is not None, unreadCount=unread)
    return c


def test_a_block_is_stored_without_a_write_per_chat(tmp_path):
    db = Counting(Store(str(tmp_path / "b.db")))
    data = N(pushnames=[N(ID="5511@s.whatsapp.net", pushname="Ana"), N(ID="", pushname="x")],
             conversations=[conversation("5511@s.whatsapp.net", 3, unread=2),
                            conversation("1203@g.us", 2), conversation("0@broadcast", 1)],
             progress=40)
    assert server.Session._store_history_block(N(db=db), data) == 40
    assert db.single == 0
    chats = {c["jid"]: c for c in db.chats()}
    assert set(chats) == {"5511@s.whatsapp.net", "1203@g.us"}
    assert chats["5511@s.whatsapp.net"]["unread"] == 2 and chats["1203@g.us"]["ts"] == 200
    assert len(db.messages("5511@s.whatsapp.net")) == 3 and len(db.messages("1203@g.us")) == 2
    assert db.contact_of("5511@s.whatsapp.net")["pushname"] == "Ana"
