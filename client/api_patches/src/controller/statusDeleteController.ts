import type { Request, Response } from 'express';

// Deleting one of the account's own statuses, for everyone who received it,
// as WhatsApp Web's own "Delete" in the status player does (read over CDP on
// 2026-10-18): WAWebRevokeStatusAction.sendStatusRevokeMsgAction(myStatus, msg)
// stores and sends a revoke to the status's recipients, then drops it from the
// list. WhatsApp's own confirmation says so: "It will also be deleted for
// everyone who received it."
//
// WA-JS wraps it (WPP.status.remove, through WPP.whatsapp.functions.revokeStatus),
// but that module belongs to the lazily loaded status drawer: until someone
// opens Status in WhatsApp Web, revokeStatus is undefined and the call fails.
// Measured: undefined right after load, a function once the drawer's code was
// loaded through the Bootloader, which shows nothing. WPP.status.remove also
// looks the account's status up by phone number only; this finds it through
// WPP.status.getMyStatus(), which follows the LID migration too.
//
// Sent once, never retried: a delete that timed out may have reached everyone.
//
// Runs inside the page: self-contained, no closure over anything here.
export async function deleteOwnStatus({ statusId }: { statusId: string }): Promise<any> {
  const root = globalThis as any;
  if (typeof statusId !== 'string' || !/^[A-Za-z0-9]{6,80}$/.test(statusId)) {
    return { ok: false, code: 'invalid_request' };
  }
  const wpp = root.WPP;
  const load = (name: string) => {
    try {
      return typeof root.require === 'function' ? root.require(name) : undefined;
    } catch (_) {
      return undefined;
    }
  };
  let mine: any;
  try {
    mine = await wpp?.status?.getMyStatus?.();
  } catch (_) {
    mine = null;
  }
  // Right after WhatsApp Web loads the account's statuses may not be there
  // yet: "not found" would drop from WinZapp a status everyone still sees.
  if (!mine) return { ok: false, code: 'unavailable' };
  const findIt = () => {
    let msgs: any[] = [];
    try {
      msgs = (typeof mine.getAllMsgs === 'function' ? mine.getAllMsgs() : mine.msgs?.getModelsArray?.()) || [];
    } catch (_) {
      msgs = [];
    }
    return msgs.find((m: any) => m?.id?.id === statusId);
  };
  // The list WhatsApp Web holds may be a part only: loaded to the end, as
  // statusController.ts does before reading it, before anything is "not found".
  // Complete when WhatsApp says nothing earlier is left, or a load brings
  // nothing more; a failing load leaves it unknown.
  const loadAll = async (): Promise<boolean> => {
    if (typeof mine.loadMore !== 'function') return mine.noEarlierMsgs === true;
    for (let i = 0; i < 40 && !mine.noEarlierMsgs; i++) {
      const before = mine.msgsLength ?? mine.msgs?.length ?? 0;
      try {
        await mine.loadMore();
      } catch (_) {
        return false;
      }
      const after = mine.msgsLength ?? mine.msgs?.length ?? 0;
      if (after <= before && !mine.isLoading) return true;
    }
    return mine.noEarlierMsgs === true;
  };
  let found = findIt();
  if (!found) {
    const complete = await loadAll();
    found = findIt();
    if (!found) return { ok: false, code: complete ? 'not_found' : 'unavailable' };
  }
  // Only the account's own: a status of someone else is never revoked here.
  if (found?.id?.fromMe !== true) return { ok: false, code: 'not_found' };
  const msg = found;

  const resolve = () => {
    const viaWpp = wpp?.whatsapp?.functions?.revokeStatus;
    if (typeof viaWpp === 'function') return viaWpp;
    const native = load('WAWebRevokeStatusAction')?.sendStatusRevokeMsgAction;
    return typeof native === 'function' ? native : null;
  };
  let revoke = resolve();
  if (!revoke) {
    const module = load('Bootloader');
    const bootloader = module?.default || module;
    if (typeof bootloader?.loadModules === 'function') {
      try {
        await new Promise<void>((done, fail) => {
          const timer = setTimeout(() => fail(new Error('unavailable')), 15000);
          bootloader.loadModules(['WAWebStatusDrawerFlow.react'],
            () => { clearTimeout(timer); done(); }, 'WinZapp');
        });
      } catch (_) {
        // Answered below: the action is still missing.
      }
      revoke = resolve();
    }
  }
  if (!revoke) return { ok: false, code: 'unavailable' };
  try {
    await revoke(mine, msg);
  } catch (_) {
    return { ok: false, code: 'delete_unconfirmed' };
  }
  return { ok: true };
}

const FAILURE_STATUS: Record<string, number> = {
  invalid_request: 400,
  not_found: 404,
};

export async function deleteStatus(req: Request, res: Response) {
  try {
    const page: any = (req.client as any)?.page;
    if (!page || page.isClosed?.()) throw new Error('unavailable');
    const result = await page.evaluate(deleteOwnStatus, { statusId: req.params.statusId });
    if (result?.ok === true) return res.status(200).json({ status: 'success' });
    const code = typeof result?.code === 'string' ? result.code : 'unavailable';
    return res.status(FAILURE_STATUS[code] || 502).json({ status: 'error', code, retrySafe: false });
  } catch (_) {
    // Never the native error: it can carry status text and ids.
    return res.status(502).json({ status: 'error', code: 'unavailable', retrySafe: false });
  }
}
