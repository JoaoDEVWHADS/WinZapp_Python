/*
 * Copyright 2021 WPPConnect Team
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { Logger } from 'winston';

import {
  countJidFallback,
  observeEvaluate,
} from '../middleware/instrumentation';

/**
 * WinZapp patch: finding the message behind a media request.
 *
 * Pulled out of getMediaByMessage(), which was 557 lines with this chain —
 * roughly half of it — inlined in the middle. The chain is the part with the
 * real reasoning: WhatsApp Web unloads messages from its Store, addresses the
 * same conversation under two identities, and answers "not found" for the
 * wrong one, so finding a message is a sequence of increasingly expensive
 * attempts rather than a lookup.
 *
 * The order matters and is deliberate, cheapest first:
 *
 *   1. the id exactly as given (it usually is in the Store);
 *   2. the same id without its device-port suffix (`…:86@lid` -> `…@lid`);
 *   3. the id trimmed to fromMe_chat_stanza, dropping the participant;
 *   4. paging the chat's older history into the Store and trying again;
 *   5. getMessages() to force a larger window in;
 *   6. resolving the conversation's OTHER JID form and retrying there.
 *
 * Separated so the controller can go back to being about HTTP, and so this
 * can be reasoned about (and one day tested) without an Express request.
 */
export interface MediaMessageLookup {
  client: any;
  messageId: string;
  cleanMsgId: string;
  body: any;
  logger: Logger;
}

export async function resolveMessageForMedia({
  client,
  messageId,
  cleanMsgId,
  body,
  logger,
}: MediaMessageLookup): Promise<any> {
  let message: any = null;
  // Lookup in Puppeteer store using original messageId first (with participant), then cleanMsgId
  try {
    message = await client.getMessageById(messageId);
  } catch (err: any) {}

  if (!message && messageId.includes(':')) {
    countJidFallback('get-media-by-message', messageId, messageId);
    // Strip device port suffix e.g. 62655318482954:94@lid -> 62655318482954@lid
    const noPortId = messageId.replace(/:\d+@/, '@');
    try {
      message = await client.getMessageById(noPortId);
    } catch (err: any) {}
  }

  if (!message && messageId !== cleanMsgId) {
    try {
      message = await client.getMessageById(cleanMsgId);
    } catch (err: any) {}
  }

  // Fallback: If message is not found, attempt loadEarlierMessages on the chat or resolve LID/JID mapping
  if (!message && cleanMsgId) {
    const parts = cleanMsgId.split('_');
    if (parts.length >= 3) {
      const fromMe = parts[0];
      const chatId = parts[1]; // e.g. 553195679326@c.us or 120363420948134065@g.us
      const msgStanzaId = parts[2];

      // Load older history into the Store so getMessageById can find a
      // message the page has since unloaded.
      //
      // This used to call client.loadEarlierMessages(), which cannot work
      // any more: it reaches WAPI.loadEarlierMessages(), whose bundled
      // implementation calls `chat.loadEarlierMsgs()` — a Chat model
      // method WhatsApp Web has removed. Every call threw
      // "t.loadEarlierMsgs is not a function" and was swallowed by the
      // catch below, so the first and cheapest step of this recovery chain
      // had been dead for a while with nothing but a warning to show for
      // it. Measured: 424 occurrences in the accumulated API log, the most
      // recent during this very session, on the same chat whose media
      // requests were failing.
      //
      // WPP.chat.getMessages() with an explicit direction is the supported
      // way to page backwards, and is what the getMessages() fallback
      // below already relies on.
      if (chatId) {
        logger.info(
          `Message ${cleanMsgId} not found in cache. Loading older history for ${chatId}`
        );
        try {
          await observeEvaluate('load-older-history', () =>
            client.page.evaluate(
              async ({ id, count }) => {
                const WPP = (globalThis as any).WPP;
                if (!WPP?.chat?.getMessages) return;
                await WPP.chat.getMessages(id, {
                  count,
                  direction: 'before',
                });
              },
              { id: chatId, count: 50 }
            )
          );
          try {
            message = await client.getMessageById(cleanMsgId);
          } catch (retryErr: any) {
            logger.warn(
              `Retry getMessageById failed: ${retryErr.message || retryErr}`
            );
          }
        } catch (loadErr: any) {
          logger.warn(
            `Error loading older history for ${chatId}: ${
              loadErr.message || loadErr
            }`
          );
        }
      }

      // If still not found, try using client.getMessages to force loading chat messages into Puppeteer store
      if (
        !message &&
        chatId &&
        typeof (client as any).getMessages === 'function'
      ) {
        try {
          logger.info(
            `Attempting client.getMessages to populate store for ${chatId}`
          );
          await (client as any).getMessages(chatId, { count: 100 });
          try {
            message = await client.getMessageById(cleanMsgId);
          } catch (retryErr: any) {}
        } catch (getMsgsErr: any) {}
      }

      // If still not found and chatId is @c.us or @lid, try finding the corresponding LID/phone chat JID in listChats() or via Puppeteer evaluation
      if (!message) {
        try {
          let resolvedJid: string | null = null;

          // 1. Try resolving LID using Puppeteer page evaluation directly from WhatsApp Web Contact/Chat Store
          if (client.page && !client.page.isClosed()) {
            try {
              resolvedJid = await client.page.evaluate(
                (targetChatId: string) => {
                  try {
                    // Check WPP/WAPI contact or chat stores
                    const phoneDigits = targetChatId
                      .split('@')[0]
                      .replace(/\D/g, '');
                    const chatStore =
                      (window as any).Store?.Chat ||
                      (window as any).WPP?.whatsapp?.ChatStore;
                    const contactStore =
                      (window as any).Store?.Contact ||
                      (window as any).WPP?.whatsapp?.ContactStore;

                    if (
                      contactStore &&
                      typeof contactStore.get === 'function'
                    ) {
                      const cnt =
                        contactStore.get(targetChatId) ||
                        contactStore.get(`${phoneDigits}@c.us`);
                      if (cnt && cnt.lid) {
                        return cnt.lid._serialized || cnt.lid.toString();
                      }
                    }

                    if (chatStore && chatStore.models) {
                      const match = chatStore.models.find((m: any) => {
                        const idStr = (
                          m.id?._serialized ||
                          m.id ||
                          ''
                        ).toString();
                        const phoneStr = (
                          m.phoneNumber ||
                          m.contact?.phoneNumber ||
                          m.contact?.id?._serialized ||
                          ''
                        ).toString();
                        return (
                          phoneDigits &&
                          (idStr.includes(phoneDigits) ||
                            phoneStr.includes(phoneDigits))
                        );
                      });
                      if (match) {
                        return match.id?._serialized || match.id.toString();
                      }
                    }
                  } catch (e) {}
                  return null;
                },
                chatId
              );
            } catch (evalErr: any) {
              logger.warn(
                `Page evaluate JID resolution failed for ${chatId}: ${
                  evalErr.message || evalErr
                }`
              );
            }
          }

          // 2. Fallback to listChats search inspecting contact phone numbers
          if (!resolvedJid) {
            const listChatsFn =
              typeof (client as any).listChats === 'function'
                ? (client as any).listChats.bind(client)
                : typeof (client as any).getAllChats === 'function'
                ? (client as any).getAllChats.bind(client)
                : null;
            if (listChatsFn) {
              const allChats: any[] = await listChatsFn();
              const phoneDigits = chatId.split('@')[0].replace(/\D/g, '');
              const altChat = Array.isArray(allChats)
                ? allChats.find((c: any) => {
                    const cId = (c.id?._serialized || c.id || '').toString();
                    const phoneStr = (
                      c.phoneNumber ||
                      c.contact?.phoneNumber ||
                      c.contact?.id?._serialized ||
                      ''
                    ).toString();
                    return (
                      phoneDigits &&
                      (cId.includes(phoneDigits) ||
                        phoneStr.includes(phoneDigits))
                    );
                  })
                : null;
              if (altChat) {
                resolvedJid = altChat.id?._serialized || altChat.id;
              }
            }
          }

          if (resolvedJid && resolvedJid !== chatId) {
            const altMsgId = `${fromMe}_${resolvedJid}_${msgStanzaId}`;
            logger.info(
              `Resolved alternative JID ${resolvedJid} for ${chatId}. Populating messages and retrying getMessageById for ${altMsgId}`
            );
            if (typeof (client as any).getMessages === 'function') {
              try {
                await (client as any).getMessages(resolvedJid, {
                  count: 100,
                });
              } catch (e: any) {}
            }
            try {
              message = await client.getMessageById(altMsgId);
            } catch (altErr: any) {
              logger.warn(
                `getMessageById with alt JID ${altMsgId} failed: ${
                  altErr.message || altErr
                }`
              );
            }
          }
        } catch (chatLookupErr: any) {
          logger.warn(
            `Failed to resolve alternative chat JID: ${
              chatLookupErr.message || chatLookupErr
            }`
          );
        }
      }
    }
  }

  // If Puppeteer could not find the message (or threw Chat not found), check if body contains decryption keys to proceed
  if (
    !message &&
    body &&
    (body.mediaKey || body.directPath || body.clientUrl || body.url)
  ) {
    logger.info(
      `Puppeteer lookup failed for ${messageId}, falling back to request body payload.`
    );
    message = { ...body };
    if (typeof message.mediaKey === 'object' && message.mediaKey?.data) {
      message.mediaKey = Buffer.from(message.mediaKey.data);
    } else if (typeof message.mediaKey === 'string') {
      message.mediaKey = Buffer.from(message.mediaKey, 'base64');
    }
  }

  return message;
}
