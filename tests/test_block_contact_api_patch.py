from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_block_contact_creates_the_chat_before_blocking():
    controller = (
        ROOT / "client/api_patches/src/controller/deviceController.ts"
    ).read_text(encoding="utf-8")
    start = controller.index("export async function blockContact")
    end = controller.index("export async function unblockContact")
    body = controller[start:end]

    # WhatsApp rejects blocking a pn contact that has no chat, so the chat
    # must be created first, and before the block call itself.
    assert "WPP.chat.find" in body
    assert body.index("WPP.chat.find") < body.index("req.client.blockContact")
