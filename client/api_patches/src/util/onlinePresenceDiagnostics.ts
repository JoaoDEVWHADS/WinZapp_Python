/* Content-free, sampled local observations. Never a receiver acknowledgement. */
const lastTrace = new WeakMap<object, number>();

export const OWN_PRESENCE_SOURCE = String.raw`function () {
  const wpp = window.WPP;
  const stream = wpp && wpp.whatsapp && wpp.whatsapp.Stream;
  if (!wpp || !stream) return { status: 'unavailable' };
  const available = stream.available;
  return { status: 'observed',
    supported: !!(wpp.conn && typeof wpp.conn.markAvailable === 'function'),
    available: typeof available === 'boolean' ? available : null };
}`;

export function beginOnlinePresenceDiagnostic(req: any) {
  const headers = req.headers || {};
  const sequence = headers['x-winzapp-presence-sequence'];
  const epoch = headers['x-winzapp-presence-epoch'];
  const client = req.client;
  if (headers['x-winzapp-presence-trace'] !== '1' ||
      typeof sequence !== 'string' || !/^[1-9][0-9]{0,6}$/.test(sequence) ||
      typeof epoch !== 'string' || !/^[1-9][0-9]{0,6}$/.test(epoch) ||
      !client || typeof client !== 'object') return null;
  const now = Date.now();
  if (now - (lastTrace.get(client) ?? -Infinity) < 1000) return null;
  lastTrace.set(client, now);
  return { sequence: Number(sequence), epoch: Number(epoch) };
}

export async function finishOnlinePresenceDiagnostic(req: any, trace: any, native: any, failed = false) {
  if (!trace) return null;
  let runtime: any = { status: 'unavailable' };
  const page = req.client && req.client.page;
  if (!failed && page && typeof page.evaluate === 'function') {
    let timer: any;
    try {
      runtime = await Promise.race([
        page.evaluate(`(${OWN_PRESENCE_SOURCE})()`),
        new Promise((resolve) => { timer = setTimeout(() => resolve({ status: 'timeout' }), 200); }),
      ]);
    } catch (_) {
      runtime = { status: 'failed' };
    } finally {
      clearTimeout(timer);
    }
  }
  // Whitelist even an unexpected provider return; never forward an object/stack.
  const observed = { status: ['observed', 'unavailable', 'timeout', 'failed'].includes(runtime?.status)
      ? runtime.status : 'failed',
    supported: runtime?.supported === true,
    available: typeof runtime?.available === 'boolean' ? runtime.available : null };
  const diagnostic = { ...trace, requested: typeof req.body?.isOnline === 'boolean'
      ? req.body.isOnline : req.body?.isOnline === undefined ? true : null,
    native: failed ? 'error' : native === true ? 'true' : native === false ? 'false'
      : native === undefined ? 'void' : 'other',
    runtime: observed, receiverConfirmed: false };
  try { req.logger.info('[presence-diag] ' + JSON.stringify(diagnostic)); } catch (_) { /* diagnostic only */ }
  return diagnostic;
}
