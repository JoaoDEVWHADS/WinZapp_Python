import { readPinnedMessages } from '../../controller/pinnedMessagesController';

function response() {
  const res: any = { statusCode: 0, body: null };
  res.status = (code: number) => { res.statusCode = code; return res; };
  res.json = (body: unknown) => { res.body = body; return res; };
  return res;
}

function request(ids: unknown = ['123@c.us'], pinned = ['false_123@c.us_OLD']) {
  return {
    body: { chatIds: ids },
    client: {
      page: { isClosed: () => false, evaluate: jest.fn().mockResolvedValue(pinned) },
      getMessageById: jest.fn().mockImplementation(async id => ({ id, type: 'chat', body: 'hello' })),
    },
  } as any;
}

describe('pinned messages', () => {
  it('serializes each target message, not the pin notification', async () => {
    const req = request(['123@c.us', '999@lid']);
    const res = response();
    await readPinnedMessages(req, res);
    expect(req.client.page.evaluate).toHaveBeenCalledWith(expect.any(Function), ['123@c.us', '999@lid']);
    expect(req.client.getMessageById).toHaveBeenCalledWith('false_123@c.us_OLD');
    expect(res.statusCode).toBe(200);
    expect(res.body.response).toEqual([{ id: 'false_123@c.us_OLD', type: 'chat', body: 'hello', pinInChat: true }]);
  });

  it('an empty native list is a successful empty result', async () => {
    const req = request(['123@c.us'], []);
    const res = response();
    await readPinnedMessages(req, res);
    expect(req.client.getMessageById).not.toHaveBeenCalled();
    expect(res.body).toEqual({ status: 'success', response: [] });
  });

  it.each([[], ['status@broadcast'], ['abc@c.us'], ['123@c.us;inject'],
    ['1@lid', '2@lid', '3@lid', '4@lid'], null, '123@c.us'])('rejects unsafe input %p before accessing the page', async ids => {
    const req = request(ids);
    const res = response();
    await readPinnedMessages(req, res);
    expect(res.statusCode).toBe(400);
    expect(req.client.page.evaluate).not.toHaveBeenCalled();
  });

  it('reports a dead page without touching WhatsApp', async () => {
    const req = request();
    req.client.page.isClosed = () => true;
    const res = response();
    await readPinnedMessages(req, res);
    expect(res.statusCode).toBe(503);
    expect(req.client.page.evaluate).not.toHaveBeenCalled();
  });

  it.each([null, { erro: true }])('inaccessible message %p is a failure, never a false partial list', async value => {
    const req = request();
    req.client.getMessageById.mockResolvedValue(value);
    const res = response();
    await readPinnedMessages(req, res);
    expect(res.statusCode).toBe(503);
    expect(res.body.response).toBeUndefined();
  });

  it('loads a pinned message the Store dropped, then serializes it', async () => {
    const req = request();
    req.client.getMessageById
      .mockResolvedValueOnce({ erro: true })
      .mockImplementationOnce(async id => ({ id, type: 'chat' }));
    const res = response();
    await readPinnedMessages(req, res);
    expect(req.client.page.evaluate).toHaveBeenCalledTimes(2);
    expect(res.statusCode).toBe(200);
    expect(res.body.response).toEqual([{ id: 'false_123@c.us_OLD', type: 'chat', pinInChat: true }]);
  });

  it('does not expose native exception text or credentials', async () => {
    const req = request();
    req.client.page.evaluate.mockRejectedValue(new Error('private contact 123@c.us'));
    const res = response();
    await readPinnedMessages(req, res);
    expect(res.body).toEqual({ status: 'error', code: 'pinned_messages_unavailable' });
  });
});
