// Live reply counts for community announcements.
//
// WA-JS has no event for announcement replies (comments). WhatsApp Web itself
// learns about one in WAWebAddonCommentMsgProcessor.afterUpsert, which calls
// WAWebCommentUtils.updateReplyCount: the parent message's `replyCount` changes
// on its model in MsgStore, which raises `change:replyCount` even with the
// native replies modal closed (useWAWebCommentReplyCount listens to the same
// attribute). CommentCollection is no help: it only fills while that modal is
// open. Measured over CDP on WhatsApp Web with WA-JS 4.7.1, 2026-10-18.
//
// The chat list preview ("Fulano respondeu a um aviso") is the chat's own
// `chatlistPreview` ({type: 'comment', msgKey, parentMsgKey, sender,
// timestamp in ms}), set by afterUpsert's filterAndUpdateChatPreviews. list-chats
// already serializes it (chat.toJSON()); `change:chatlistPreview` on ChatStore
// sends it right away instead of at the next 60 s chat-list poll.
//
// Only ids, the sender's id, a timestamp and a count leave the page: never
// the reply text or the message secret.

const BINDING = '__winzappOnAnnouncementReplies';
const MAX_PAYLOAD = 512;

/** Runs inside the page; serialized by Puppeteer, so self-contained. */
export function installAnnouncementReplyBridgeInPage(): boolean {
  const win = window as any;
  const wpp = win.WPP;
  const store = wpp && wpp.isFullReady && wpp.whatsapp && wpp.whatsapp.MsgStore;
  const chats = wpp && wpp.whatsapp && wpp.whatsapp.ChatStore;
  const notify = win.__winzappOnAnnouncementReplies;
  if (!store || typeof store.on !== 'function' || !chats || typeof chats.on !== 'function'
      || typeof notify !== 'function') {
    return false;
  }
  const text = (value: any) => (value == null ? '' : String(value._serialized || value));
  if (!chats.__winzappAnnouncementReplies) {
    chats.__winzappAnnouncementReplies = true;
    chats.on('change:chatlistPreview', (chat: any) => {
      try {
        const chatId = text(chat && chat.id);
        if (!chatId.endsWith('@g.us')) return;
        const preview = chat.chatlistPreview;
        // Any other kind (a reaction) or none only tells Python that a reply
        // is no longer the preview; WinZapp tracks reactions itself.
        const value = preview && preview.type === 'comment'
          ? { type: 'comment', msgKey: text(preview.msgKey), sender: text(preview.sender),
              timestamp: Number(preview.timestamp) || 0 }
          : { type: preview ? String(preview.type || '') : '' };
        notify(JSON.stringify({ kind: 'preview', chatId, preview: value }));
      } catch {
        // Never let a listener exception reach WhatsApp's own event loop.
      }
    });
  }
  // A WhatsApp Web reload is a new document and a new MsgStore: the guard
  // lives on the store, so a reload installs again and a repeat does not.
  if (store.__winzappAnnouncementReplies) return true;
  store.__winzappAnnouncementReplies = true;
  store.on('change:replyCount', (msg: any) => {
    try {
      const id = msg && msg.id;
      const serialized = id && (id._serialized || String(id));
      const remote = id && id.remote;
      const chatId = remote && (remote._serialized || String(remote));
      const replyCount = msg.replyCount;
      if (typeof serialized !== 'string' || typeof chatId !== 'string'
          || !chatId.endsWith('@g.us') || !Number.isInteger(replyCount) || replyCount < 0) {
        return;
      }
      notify(JSON.stringify({ id: serialized, chatId, replyCount }));
    } catch {
      // Never let a listener exception reach WhatsApp's own event loop.
    }
  });
  return true;
}

/** The socket payload for one page notification, or null when malformed. */
export function announcementRepliesPayload(raw: unknown, session: string) {
  if (typeof raw !== 'string' || raw.length > MAX_PAYLOAD) return null;
  try {
    const value = JSON.parse(raw);
    if (value && value.kind === 'preview') {
      const { chatId, preview } = value;
      if (typeof chatId !== 'string' || !chatId.endsWith('@g.us') || !preview
          || typeof preview.type !== 'string') {
        return null;
      }
      return { session, kind: 'preview', chatId, preview };
    }
    const { id, chatId, replyCount } = value || {};
    if (typeof id !== 'string' || !id || typeof chatId !== 'string' || !chatId.endsWith('@g.us')
        || !Number.isInteger(replyCount) || replyCount < 0) {
      return null;
    }
    return { session, id, chatId, replyCount };
  } catch {
    return null;
  }
}

export async function installAnnouncementReplyBridge(client: any, io: any, logger: any) {
  const page = client?.page;
  if (!page) return;
  try {
    await page.exposeFunction(BINDING, (raw: unknown) => {
      const payload = announcementRepliesPayload(raw, client.session);
      if (payload) io.to(`session:${client.session}`).emit('announcement-replies', payload);
    });
  } catch {
    // Puppeteer bindings survive navigation; duplicate registration is expected.
  }
  const install = (attempt = 0) => {
    page.evaluate(installAnnouncementReplyBridgeInPage)
      .then((installed: boolean) => {
        if (!installed && attempt < 120) {
          setTimeout(() => install(attempt + 1), 500);
        } else if (installed) {
          logger?.info?.(`[${client.session}] announcement reply bridge installed`);
        } else {
          // As the unread-count listener says it: without this, replies
          // simply stop updating live and nothing tells why.
          logger?.warn?.(`[announcementReplyBridge] GAVE UP after ${attempt + 1} attempts — `
            + 'wa-js never became ready, announcement replies will not update live');
        }
      })
      .catch((e: any) =>
        logger?.warn?.(`[announcementReplyBridge] install failed: ${e?.message || e}`));
  };
  // A page reload is a fresh JS context: the listener goes with it.
  page.on('load', () => install());
  install();
}
