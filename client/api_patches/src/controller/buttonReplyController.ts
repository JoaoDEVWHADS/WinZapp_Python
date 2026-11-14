import type { Request, Response } from 'express';

// The answer to a button of a business's message, sent the way WhatsApp Web
// sends it when the button is tapped.
//
// Read over CDP on 2026-10-21 (WAWebGetInteractiveActionsFromButtons and
// WAWebSendButtonsMsgReplyChatAction):
//  - "dynamic": the reply buttons of a plain message (dynamicReplyButtons).
//    WAWebSendButtonsMsgReplyChatAction(message, button, chat) sends a
//    "buttons response" carrying the button's id. Checked live: the business
//    went on with its flow.
//  - "native": a quick reply of an interactive (native flow) message. The web
//    client sends a text with the button's label that quotes the message and
//    carries the button's index and id (sendTextMsgToChat, selectedIndex and
//    selectedId), then marks the button as clicked.
//  - "template": the buttons of a template message, answered by index by
//    WA-JS itself.
//  - "list": a row of a list message. The web client sends a list response
//    (type list_response) that carries the row's title, description and id,
//    quoting the list.
// Links, copied codes and phone numbers are never sent: the window acts on
// them.
//
// Sent once, never retried: a send that threw may have reached the business.
//
// Runs inside the page: self-contained, no closure over anything here.
export async function replyButtonInPage(request: any): Promise<any> {
  const root = globalThis as any;
  const load = (name: string) => {
    try {
      return typeof root.require === 'function' ? root.require(name) : undefined;
    } catch (_) {
      return undefined;
    }
  };
  const store = load('WAWebMsgCollection')?.MsgCollection;
  const frontend = load('WAWebFrontendMsgGetters');
  if (!store || !frontend) return { error: 'unavailable' };

  let msg = store.get(request.messageId);
  if (!msg && typeof root.WPP?.chat?.getMessageById === 'function') {
    try {
      await root.WPP.chat.getMessageById(request.messageId);
    } catch (_) {
      // Not in the chat: answered below.
    }
    msg = store.get(request.messageId);
  }
  if (!msg) return { error: 'message_not_found' };
  const raw = typeof msg.unsafe === 'function' ? msg.unsafe() : msg;
  const chat = frontend.getChat(raw);
  if (!chat) return { error: 'unavailable' };

  if (request.source === 'dynamic') {
    const button = raw.replyButtons?.getModelsArray?.()?.[request.index];
    const send = load('WAWebSendButtonsMsgReplyChatAction');
    if (!button) return { error: 'button_not_found' };
    if (typeof send !== 'function') return { error: 'unavailable' };
    await send(msg, button, chat);
    return { sent: true };
  }

  if (request.source === 'native') {
    const button = raw.interactivePayload?.buttons?.[request.index];
    let params: any = null;
    try {
      params = JSON.parse(button?.buttonParamsJson);
    } catch (_) {
      params = null;
    }
    if (!button || button.name !== 'quick_reply' || !params || typeof params.display_text !== 'string') {
      return { error: 'button_not_found' };
    }
    if (params.disabled === true) return { error: 'button_used' };
    const sendText = load('WAWebSendTextMsgChatAction')?.sendTextMsgToChat;
    const mark = load('WAWebBizInteractiveMessageQuickReplyAction')?.markInteractiveButtonClicked;
    if (typeof sendText !== 'function') return { error: 'unavailable' };
    await sendText(chat, params.display_text, {
      quotedMsg: raw, selectedIndex: request.index, selectedId: params.id,
    });
    if (typeof mark === 'function') {
      try {
        await mark(raw, request.index);
      } catch (_) {
        // Only the button's look; the answer was sent.
      }
    }
    return { sent: true };
  }

  if (request.source === 'list') {
    const rows = (raw.list?.sections ?? []).flatMap((section: any) => section?.rows ?? []);
    const row = rows[request.index];
    if (!row || typeof row.rowId !== 'string' || typeof row.title !== 'string') return { error: 'button_not_found' };
    const me = load('WAWebUserPrefsMeUser')?.getMePnUserOrThrow_DO_NOT_USE;
    const MsgKey = load('WAWebMsgKey');
    const ack = load('WAWebAck')?.ACK;
    const time = load('WATimeUtils')?.unixTime;
    const sender = load('WAWebSendMsgChatAction')?.addAndSendMsgToChat;
    const types = load('WAWebMsgType');
    const listType = load('WAWebProtobufsE2E.pb')?.Message$ListResponseMessage$ListType?.SINGLE_SELECT;
    if (typeof me !== 'function' || typeof MsgKey?.newId !== 'function' || !ack || typeof time !== 'function'
        || typeof sender !== 'function' || !types?.MSG_TYPE?.LIST_RESPONSE || !types?.MsgKind?.ListResponse
        || typeof msg.msgContextInfo !== 'function' || listType === undefined) {
      return { error: 'unavailable' };
    }
    const mePn = me();
    const description = typeof row.description === 'string' ? row.description : '';
    await sender(chat, {
      type: types.MSG_TYPE.LIST_RESPONSE,
      kind: types.MsgKind.ListResponse,
      ack: ack.CLOCK,
      from: mePn,
      id: new MsgKey({ from: mePn, to: chat.id, id: await MsgKey.newId(), participant: undefined, selfDir: 'out' }),
      local: true,
      isNewMsg: true,
      t: time(),
      to: chat.id,
      ...msg.msgContextInfo(chat.id),
      listResponse: { title: row.title, description, listType, singleSelectReply: { selectedRowId: row.rowId } },
      body: description ? `${row.title}\n${description}` : row.title,
      viewMode: 'VISIBLE',
    });
    return { sent: true };
  }

  const buttons = raw.hydratedButtons;
  if (!Array.isArray(buttons) || !buttons[request.index]?.quickReplyButton) return { error: 'button_not_found' };
  if (typeof root.WPP?.chat?.replyToButtonMessage !== 'function') return { error: 'unavailable' };
  await root.WPP.chat.replyToButtonMessage(raw.id.remote._serialized, request.messageId, {
    buttonIndex: request.index,
  });
  return { sent: true };
}

// "true_<chat>_<id>" or "false_<chat>_<id>", a message of a one-to-one chat.
const validMessage = (value: unknown): value is string =>
  typeof value === 'string' && /^(true|false)_\d+@(c\.us|lid)_[A-Za-z0-9]{8,64}$/.test(value);

const SOURCES = ['dynamic', 'native', 'template', 'list'];

const STATUS_OF: Record<string, number> = {
  message_not_found: 404, button_not_found: 404, button_used: 409,
};

export async function replyToButton(req: Request, res: Response) {
  const { source, index } = req.body || {};
  if (!validMessage(req.params.messageId) || !SOURCES.includes(source)
      || !Number.isInteger(index) || index < 0 || index > 11) {
    return res.status(400).json({ status: 'error', code: 'invalid_request' });
  }
  try {
    const page: any = (req.client as any)?.page;
    if (!page || page.isClosed?.()) throw new Error('unavailable');
    const answer = await page.evaluate(replyButtonInPage, { messageId: req.params.messageId, source, index });
    if (!answer || typeof answer !== 'object') throw new Error('unavailable');
    if (typeof answer.error === 'string') {
      const status = STATUS_OF[answer.error];
      if (!status) throw new Error('unavailable');
      return res.status(status).json({ status: 'error', code: answer.error });
    }
    return res.status(200).json({ status: 'success', response: { sent: answer.sent === true } });
  } catch (_) {
    // Never the native error: it can carry a chat id or the message's text.
    return res.status(503).json({ status: 'error', code: 'reply_button_unavailable' });
  }
}
