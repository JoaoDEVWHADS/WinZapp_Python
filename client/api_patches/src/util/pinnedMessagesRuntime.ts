// Self-contained: Puppeteer serializes this function into the WhatsApp page.
// JavaScript syntax also lets the Node tests run the exact browser function.
export async function readPinnedMessageIds(chatIds) {
  const wpp = globalThis['WPP'];
  const store = wpp?.whatsapp?.PinInChatStore;
  const pinState = wpp?.whatsapp?.enums?.PIN_STATE?.PIN;
  if (typeof store?.byChatId !== 'function' || pinState === undefined
      || typeof wpp?.chat?.get !== 'function') {
    throw new Error('pinned_messages_unavailable');
  }
  let table;
  let deserialize;
  let isValid;
  if (wpp.loader?.loaderType === 'meta') {
    // The Meta runtime persists pins without hydrating PinInChatStore.
    // An empty aggregate is therefore not evidence that a chat has no pins.
    const load = wpp.loader.loadModule;
    if (typeof load !== 'function') throw new Error('pinned_messages_unavailable');
    const storage = load('WAWebModelStorageUtils')?.getStorage?.();
    deserialize = load('WAWebPinsDbSerialization')?.deserializePinInChat;
    isValid = load('WAWebPinInChatCollection')?.isPinValid;
    table = storage?.table?.('pinned-messages');
    if (typeof table?.anyOf !== 'function' || typeof deserialize !== 'function'
        || typeof isValid !== 'function') throw new Error('pinned_messages_unavailable');
  }
  const ids = new Set();
  let found = false;
  for (const chatId of chatIds) {
    const chat = wpp.chat.get(chatId);
    if (!chat) continue;
    found = true;
    // Current WhatsApp returns an aggregated collection despite WA-JS's
    // array declaration. Older versions can still return the array itself.
    const collection = table
      ? await table.anyOf(['chatId'], [chat.id.toString()])
      : store.byChatId(chat.id);
    const entries = Array.isArray(collection)
      ? collection : collection?.getModelsArray?.();
    if (!Array.isArray(entries)) throw new Error('pinned_messages_invalid');
    for (const row of entries) {
      const entry = table ? deserialize(row) : row;
      // parentMsgKey is the pinned message; msgKey is the pin notification.
      if (table && !isValid(entry)) continue;
      if (entry.pinType !== pinState) continue;
      const expiry = Number(entry.pinExpiryDuration);
      const timestamp = Number(entry.t);
      if (expiry > 0 && timestamp > 0
          && timestamp + expiry <= Date.now() / 1000) continue;
      const key = entry.parentMsgKey;
      const id = typeof key === 'string' ? key : key?._serialized ?? key?.toString?.();
      if (!id) throw new Error('pinned_messages_invalid');
      ids.add(id);
    }
  }
  if (!found) throw new Error('pinned_chat_not_found');
  return [...ids];
}

// A resolved WA-JS call can still report rejection with pinned !== requested.
export async function writePinnedMessage({ messageId, pin }) {
  try {
    const wpp = globalThis['WPP'];
    if (typeof messageId !== 'string' || !messageId || typeof pin !== 'boolean'
        || typeof wpp?.chat?.pinMsg !== 'function') {
      return { ok: false, error: 'pin_message_unavailable' };
    }
    const result = await wpp.chat.pinMsg(messageId, pin);
    if (result?.pinned !== pin) return { ok: false, error: 'pin_message_unconfirmed' };
    return { ok: true, pinned: result.pinned };
  } catch {
    // Native errors may carry contact names, message content and identifiers.
    return { ok: false, error: 'pin_message_failed' };
  }
}
