import { replyButtonInPage, replyToButton } from '../../controller/buttonReplyController';

const ID = 'false_5511900000001@lid_3EB0AAAAAAAAAAAA';

function fakePage({ present = true, extra = {}, withSender = true }: any = {}) {
  const chat = { id: 'chat' };
  const sendButtonReply = jest.fn(async () => {});
  const sendText = jest.fn(async () => {});
  const mark = jest.fn(async () => {});
  const sendList = jest.fn(async () => {});
  const replyToButtonMessage = jest.fn(async () => ({}));
  const button = { id: '2', displayText: 'Home' };
  const raw: any = {
    id: { remote: { _serialized: '5511900000001@lid' } },
    replyButtons: { getModelsArray: () => [{ id: '1' }, button] },
    interactivePayload: { buttons: [
      { name: 'quick_reply', buttonParamsJson: JSON.stringify({ display_text: 'Debt', id: 'd1' }) },
      { name: 'cta_url', buttonParamsJson: JSON.stringify({ display_text: 'Site', url: 'https://x.com' }) },
      { name: 'quick_reply', buttonParamsJson: JSON.stringify({ display_text: 'Used', id: 'u', disabled: true }) },
    ] },
    list: { sections: [{ rows: [{ title: 'Outage', rowId: 'r1' }] }, { rows: [{ title: 'Bills', description: 'd', rowId: 'r2' }] }] },
    hydratedButtons: [{ quickReplyButton: { id: 'q', displayText: 'Yes' } }, { urlButton: { url: 'https://x.com' } }],
    ...extra,
  };
  const msg = { unsafe: () => raw, msgContextInfo: (to: any) => ({ quotedStanzaID: 'Q', to }) };
  const modules: Record<string, any> = {
    WAWebMsgCollection: { MsgCollection: { get: (id: string) => (present && id === ID ? msg : undefined) } },
    WAWebFrontendMsgGetters: { getChat: () => chat },
    WAWebSendButtonsMsgReplyChatAction: withSender ? sendButtonReply : undefined,
    WAWebSendTextMsgChatAction: { sendTextMsgToChat: sendText },
    WAWebBizInteractiveMessageQuickReplyAction: { markInteractiveButtonClicked: mark },
    WAWebUserPrefsMeUser: { getMePnUserOrThrow_DO_NOT_USE: () => 'me' },
    WAWebMsgKey: class { static newId = async () => 'NEWID'; constructor(public parts: any) {} },
    WAWebAck: { ACK: { CLOCK: 0 } },
    WATimeUtils: { unixTime: () => 1790000000 },
    WAWebSendMsgChatAction: { addAndSendMsgToChat: sendList },
    WAWebMsgType: { MSG_TYPE: { LIST_RESPONSE: 'list_response' }, MsgKind: { ListResponse: 'listResponse' } },
    'WAWebProtobufsE2E.pb': { Message$ListResponseMessage$ListType: { SINGLE_SELECT: 1 } },
  };
  const require = (name: string) => {
    if (!(name in modules)) throw new Error('unknown');
    return modules[name];
  };
  return { require, chat, msg, raw, button, sendButtonReply, sendText, mark, sendList, replyToButtonMessage };
}

async function inPage(fake: any, source: string, index: number, messageId = ID) {
  const root = globalThis as any;
  const previous = { require: root.require, WPP: root.WPP };
  root.require = fake.require;
  root.WPP = { chat: { replyToButtonMessage: fake.replyToButtonMessage } };
  try {
    return await replyButtonInPage({ messageId, source, index });
  } finally {
    root.require = previous.require;
    root.WPP = previous.WPP;
  }
}

test('a reply button of a plain message is answered the way WhatsApp Web does', async () => {
  const fake = fakePage();
  expect(await inPage(fake, 'dynamic', 1)).toEqual({ sent: true });
  expect(fake.sendButtonReply).toHaveBeenCalledTimes(1);
  expect(fake.sendButtonReply).toHaveBeenCalledWith(fake.msg, fake.button, fake.chat);
});

test('a quick reply of an interactive message quotes it with the button index and id', async () => {
  const fake = fakePage();
  expect(await inPage(fake, 'native', 0)).toEqual({ sent: true });
  expect(fake.sendText).toHaveBeenCalledTimes(1);
  expect(fake.sendText).toHaveBeenCalledWith(fake.chat, 'Debt', { quotedMsg: fake.raw, selectedIndex: 0, selectedId: 'd1' });
  expect(fake.mark).toHaveBeenCalledWith(fake.raw, 0);
});

test('a quick reply is sent even when marking the button fails', async () => {
  const fake = fakePage();
  fake.mark.mockRejectedValue(new Error('x'));
  expect(await inPage(fake, 'native', 0)).toEqual({ sent: true });
});

test('a button that is not a quick reply, or was used, is never sent', async () => {
  const fake = fakePage();
  expect(await inPage(fake, 'native', 1)).toEqual({ error: 'button_not_found' });
  expect(await inPage(fake, 'native', 2)).toEqual({ error: 'button_used' });
  expect(await inPage(fake, 'native', 9)).toEqual({ error: 'button_not_found' });
  expect(fake.sendText).not.toHaveBeenCalled();
});

test('a list row is answered with a list response that quotes the list', async () => {
  const fake = fakePage();
  expect(await inPage(fake, 'list', 1)).toEqual({ sent: true });
  expect(fake.sendList).toHaveBeenCalledTimes(1);
  const [chat, sent] = fake.sendList.mock.calls[0] as any[];
  expect(chat).toBe(fake.chat);
  expect(sent).toMatchObject({
    type: 'list_response', kind: 'listResponse', from: 'me', local: true, quotedStanzaID: 'Q',
    listResponse: { title: 'Bills', description: 'd', listType: 1, singleSelectReply: { selectedRowId: 'r2' } },
    body: 'Bills\nd' });
  expect(await inPage(fake, 'list', 5)).toEqual({ error: 'button_not_found' });
  expect(fake.sendList).toHaveBeenCalledTimes(1);
});

test('a template quick reply is answered by index through WA-JS', async () => {
  const fake = fakePage();
  expect(await inPage(fake, 'template', 0)).toEqual({ sent: true });
  expect(fake.replyToButtonMessage).toHaveBeenCalledWith('5511900000001@lid', ID, { buttonIndex: 0 });
  expect(await inPage(fake, 'template', 1)).toEqual({ error: 'button_not_found' });
  expect(fake.replyToButtonMessage).toHaveBeenCalledTimes(1);
});

test('a missing message, button or WhatsApp Web function sends nothing', async () => {
  expect(await inPage(fakePage({ present: false }), 'dynamic', 0)).toEqual({ error: 'message_not_found' });
  const fake = fakePage();
  expect(await inPage(fake, 'dynamic', 5)).toEqual({ error: 'button_not_found' });
  expect(await inPage(fakePage({ withSender: false }), 'dynamic', 0)).toEqual({ error: 'unavailable' });
  expect(fake.sendButtonReply).not.toHaveBeenCalled();
});

function route(body: any, messageId = ID, evaluate: any = jest.fn()) {
  const res: any = { status: jest.fn(() => res), json: jest.fn(() => res) };
  const page = { evaluate, isClosed: () => false };
  return { res, page, run: () => replyToButton({ params: { messageId }, body, client: { page } } as any, res) };
}

test.each([
  ['an id that is not a message id', { source: 'dynamic', index: 0 }, '../x'],
  ['an unknown source', { source: 'other', index: 0 }, ID],
  ['an index past the limit', { source: 'dynamic', index: 12 }, ID],
  ['an index that is not a number', { source: 'dynamic', index: '0' }, ID],
])('the route refuses %s before touching the page', async (_name, body, messageId) => {
  const { res, page, run } = route(body, messageId);
  await run();
  expect(res.status).toHaveBeenCalledWith(400);
  expect(page.evaluate).not.toHaveBeenCalled();
});

test('the route answers with the server code and never the native error', async () => {
  const refused = route({ source: 'dynamic', index: 0 }, ID, jest.fn(async () => ({ error: 'button_used' })));
  await refused.run();
  expect(refused.res.status).toHaveBeenCalledWith(409);
  const failed = route({ source: 'dynamic', index: 0 }, ID, jest.fn(async () => { throw new Error('chat 5511900000001'); }));
  await failed.run();
  expect(failed.res.status).toHaveBeenCalledWith(503);
  expect(JSON.stringify(failed.res.json.mock.calls)).not.toContain('5511900000001');
  const sent = route({ source: 'dynamic', index: 0 }, ID, jest.fn(async () => ({ sent: true })));
  await sent.run();
  expect(sent.res.status).toHaveBeenCalledWith(200);
});
