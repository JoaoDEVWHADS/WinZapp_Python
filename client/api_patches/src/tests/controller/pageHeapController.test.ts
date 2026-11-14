import { collectGarbage, collectPageGarbage } from '../../controller/pageHeapController';

function fakePage({ send, legacy = false, closed = false }: any = {}) {
  const session = {
    send: send || jest.fn(async (method: string) => {
      if (method === 'Runtime.getHeapUsage') {
        session.reads += 1;
        return { usedSize: session.reads === 1 ? 900 : 400, totalSize: 1000 };
      }
      return {};
    }),
    detach: jest.fn().mockResolvedValue(undefined),
    reads: 0,
  };
  const open = jest.fn().mockResolvedValue(session);
  const page: any = { isClosed: () => closed };
  if (legacy) page.target = () => ({ createCDPSession: open });
  else page.createCDPSession = open;
  return { page, session, open };
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

function response() {
  const res: any = {};
  res.status = jest.fn(() => res);
  res.json = jest.fn(() => res);
  return res;
}

test('collects once through its own CDP session and reports the heap before and after', async () => {
  const { page, session } = fakePage();
  const result = await collectPageGarbage(page);
  expect(result).toMatchObject({ ok: true, before: 900, after: 400 });
  expect(typeof result.tookMs).toBe('number');
  expect(session.send.mock.calls.map((call: any[]) => call[0])).toEqual([
    'Runtime.getHeapUsage', 'HeapProfiler.collectGarbage', 'Runtime.getHeapUsage']);
  await flush();
  expect(session.detach).toHaveBeenCalledTimes(1);
});

test('an older Puppeteer opens the session through the page target', async () => {
  const { page, open } = fakePage({ legacy: true });
  expect((await collectPageGarbage(page)).ok).toBe(true);
  expect(open).toHaveBeenCalledTimes(1);
});

test('a heap reading that fails does not stop the collection', async () => {
  const send = jest.fn(async (method: string) => {
    if (method === 'Runtime.getHeapUsage') throw new Error('not supported');
    return {};
  });
  const { page } = fakePage({ send });
  expect(await collectPageGarbage(page)).toMatchObject({ ok: true, before: null, after: null });
  expect(send).toHaveBeenCalledWith('HeapProfiler.collectGarbage');
});

test('no page, or a closed one, is unavailable without touching CDP', async () => {
  expect(await collectPageGarbage(undefined)).toEqual({ ok: false, code: 'unavailable' });
  const { page, open } = fakePage({ closed: true });
  expect(await collectPageGarbage(page)).toEqual({ ok: false, code: 'unavailable' });
  expect(open).not.toHaveBeenCalled();
});

test('a failing collection is unavailable, and the next one may run', async () => {
  const send = jest.fn(async (method: string) => {
    if (method === 'HeapProfiler.collectGarbage') throw new Error('Target closed');
    return {};
  });
  const { page, session } = fakePage({ send });
  expect(await collectPageGarbage(page)).toEqual({ ok: false, code: 'unavailable' });
  await flush();
  expect(session.detach).toHaveBeenCalledTimes(1);
  expect((await collectPageGarbage(page)).code).toBe('unavailable');
});

test('one collection at a time per page: a second one is busy until the first ends', async () => {
  let finish: () => void = () => undefined;
  const send = jest.fn((method: string) => (method === 'HeapProfiler.collectGarbage'
    ? new Promise((resolve) => { finish = () => resolve({}); })
    : Promise.resolve({ usedSize: 1 })));
  const { page } = fakePage({ send });
  const first = collectPageGarbage(page);
  await flush();
  expect(await collectPageGarbage(page)).toEqual({ ok: false, code: 'busy' });
  finish();
  expect((await first).ok).toBe(true);
  await flush();
  // Free again: this one starts (and, never finished, runs into its deadline).
  expect(await collectPageGarbage(page, 5)).toEqual({ ok: false, code: 'timeout' });
  finish();
});

test('a collection past the deadline answers "timeout" and stays busy until it ends', async () => {
  let finish: () => void = () => undefined;
  const send = jest.fn((method: string) => (method === 'HeapProfiler.collectGarbage'
    ? new Promise((resolve) => { finish = () => resolve({}); })
    : Promise.resolve({ usedSize: 1 })));
  const { page, session } = fakePage({ send });
  expect(await collectPageGarbage(page, 5)).toEqual({ ok: false, code: 'timeout' });
  expect(await collectPageGarbage(page, 5)).toEqual({ ok: false, code: 'busy' });
  expect(session.detach).not.toHaveBeenCalled();
  finish();
  await flush();
  await flush();
  expect(session.detach).toHaveBeenCalledTimes(1);
});

test('the route answers success with the measurements and errors by code', async () => {
  const { page } = fakePage();
  const ok = response();
  await collectGarbage({ client: { page } } as any, ok);
  expect(ok.status).toHaveBeenCalledWith(200);
  expect(ok.json.mock.calls[0][0]).toMatchObject({ status: 'success', response: { before: 900, after: 400 } });

  const missing = response();
  await collectGarbage({ client: undefined } as any, missing);
  expect(missing.status).toHaveBeenCalledWith(503);
  expect(missing.json).toHaveBeenCalledWith({ status: 'error', code: 'unavailable' });
});
