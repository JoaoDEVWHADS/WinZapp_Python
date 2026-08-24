"""Contract for native status likes in the WPPConnect patch.

A status like is not a private text reply or a status post. WhatsApp Web has a
dedicated action that handles LID conversion and direct device fanout to the
status author.
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

    assert "WAWebSendStatusReactionAction" in status_branch
    assert (
        "statusReactionAction.sendStatusReaction(model, reaction || '')"
        in status_branch
    )
    assert "WPP.chat.sendRawMessage(" not in status_branch
    assert "broadcastParticipants: [authorWid]" not in status_branch
    assert "crypto.getRandomValues(new Uint8Array(10))" not in status_branch
    assert "WPP.whatsapp.randomHex" not in status_branch
    assert "[status-reaction] begin" in status_branch
    assert "[status-reaction] accepted" in status_branch
    assert "[status-reaction] failed" in status_branch
    assert "sendReactionToMessage(model, reaction)" not in status_branch
