"""Contract for native status likes in the WPPConnect patch.

A status like is not a private text reply and cannot use the ordinary chat
reaction helper: WhatsApp requires a reaction message through
status@broadcast, targeted to the status author.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = (
    ROOT
    / "client"
    / "api_patches"
    / "src"
    / "controller"
    / "deviceController.ts"
)


def test_status_like_uses_targeted_status_reaction_transport():
    source = CONTROLLER.read_text(encoding="utf-8")
    status_branch = source[source.index("export async function reactMessage") :]

    assert "WPP.chat.sendRawMessage(" in status_branch
    assert "status@broadcast" in status_branch
    assert "reactionParentKey: model.id" in status_branch
    assert "broadcastParticipants: [authorWid]" in status_branch
    assert "sendReactionToMessage(model, reaction)" not in status_branch
