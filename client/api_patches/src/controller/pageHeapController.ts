import type { Request, Response } from 'express';

// A full garbage collection of the WhatsApp Web page's V8 heap, on request
// (issue #379, part 2). The sync and backfill move large message arrays across
// the Puppeteer bridge; the page drops them once they are answered, but
// Chromium may leave the space unreclaimed for a long time after a big sync.
// WinZapp asks for this only after a large batch has finished
// (client/core/page_heap.py), never per message.
//
// HeapProfiler.collectGarbage reclaims only what nothing references any more,
// so no WhatsApp Web state is lost; the cost is a pause of the page's
// JavaScript while it runs (tens of ms reported on a large account). Our own
// CDP session, detached afterwards, leaves wppconnect's session untouched.
// Runtime.getHeapUsage before and after puts the effect in the client's log.
//
// One collection per page at a time: a second request while one runs is
// answered "busy" instead of queuing another pause behind it.

export const COLLECT_TIMEOUT_MS = 20000;

const running = new WeakMap<object, true>();

async function openSession(page: any): Promise<any> {
  if (typeof page.createCDPSession === 'function') return page.createCDPSession();
  return page.target().createCDPSession();
}

async function usedHeap(session: any): Promise<number | null> {
  try {
    const usage = await session.send('Runtime.getHeapUsage');
    return typeof usage?.usedSize === 'number' ? usage.usedSize : null;
  } catch (_) {
    return null;
  }
}

export async function collectPageGarbage(page: any, timeoutMs = COLLECT_TIMEOUT_MS): Promise<any> {
  if (!page || page.isClosed?.()) return { ok: false, code: 'unavailable' };
  if (running.has(page)) return { ok: false, code: 'busy' };
  running.set(page, true);
  let session: any = null;
  const work = (async () => {
    session = await openSession(page);
    const before = await usedHeap(session);
    const started = Date.now();
    await session.send('HeapProfiler.collectGarbage');
    const tookMs = Date.now() - started;
    return { ok: true, before, after: await usedHeap(session), tookMs };
  })().catch(() => ({ ok: false, code: 'unavailable' }));
  // Released and detached only when the collection itself ends, even after a
  // timeout answered the caller: a second one must not start under it.
  work.finally(() => {
    running.delete(page);
    if (session && typeof session.detach === 'function') {
      Promise.resolve().then(() => session.detach()).catch(() => undefined);
    }
  });
  let timer: any;
  const timeout = new Promise((resolve) => {
    timer = setTimeout(() => resolve({ ok: false, code: 'timeout' }), timeoutMs);
  });
  try {
    return await Promise.race([work, timeout]);
  } finally {
    clearTimeout(timer);
  }
}

const FAILURE_STATUS: Record<string, number> = {
  busy: 409,
  timeout: 504,
};

export async function collectGarbage(req: Request, res: Response) {
  try {
    const result = await collectPageGarbage((req.client as any)?.page);
    if (result?.ok === true) {
      const { before, after, tookMs } = result;
      return res.status(200).json({ status: 'success', response: { before, after, tookMs } });
    }
    const code = typeof result?.code === 'string' ? result.code : 'unavailable';
    return res.status(FAILURE_STATUS[code] || 503).json({ status: 'error', code });
  } catch (_) {
    return res.status(503).json({ status: 'error', code: 'unavailable' });
  }
}
