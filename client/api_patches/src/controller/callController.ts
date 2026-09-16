/*
 * WinZapp call-control endpoints.
 *
 * WhatsApp Web owns signaling and encryption inside Chromium. WinZapp owns the
 * accessible desktop UI and the Python microphone/speaker pipeline. These
 * endpoints expose the WA-JS call functions WPPConnect Server does not expose
 * yet, while activating the injected media bridge before a call asks for audio.
 */
import { Request, Response } from 'express';

import { ensureCallMediaBridge, setCallMediaBridgeActive } from '../util/callMediaBridge';

type CallActionPayload = {
  callId?: string;
  to?: string;
  isVideo?: boolean;
};

function getWhatsappPage(req: Request): any {
  const client = req.client as any;
  const page = client?.waPage || client?.page;
  if (!page || typeof page.evaluate !== 'function') {
    throw new Error('WhatsApp page is not available for call control');
  }
  return page;
}

async function evaluateWppCall(req: Request, action: string, payload: CallActionPayload = {}) {
  const page = getWhatsappPage(req);
  return page.evaluate(
    async ({ action, payload }) => {
      const win = window as any;
      if (!win.WPP?.call) throw new Error('WPP.call is not available');

      if (action === 'accept') {
        return win.WPP.call.accept(payload.callId || undefined);
      }
      if (action === 'reject') {
        return win.WPP.call.rejectCall(payload.callId || undefined);
      }
      if (action === 'end') {
        return win.WPP.call.end();
      }
      if (action === 'offer') {
        const call = await win.WPP.call.offer(payload.to, { isVideo: !!payload.isVideo });
        return {
          id: String(call?.id?._serialized || call?.id || ''),
          peerJid: String(call?.peerJid?._serialized || call?.peerJid?.toString?.() || ''),
          state: String(call?.getState?.() || call?.state || ''),
          isVideo: !!call?.isVideo,
          isGroup: !!call?.isGroup,
          outgoing: !!call?.outgoing,
        };
      }

      throw new Error(`Unsupported call action: ${action}`);
    },
    { action, payload }
  );
}

function ok(res: Response, response: any) {
  res.status(200).json({ status: 'success', response });
}

function fail(req: Request, res: Response, action: string, error: unknown) {
  req.logger.error(error);
  const message = error instanceof Error ? error.message : String(error);
  res.status(500).json({ status: 'error', message: `Error on ${action}`, error: message });
}

async function prepareAudioBridge(req: Request): Promise<boolean> {
  const client = req.client as any;
  const installed = await ensureCallMediaBridge(client, req.io, req.logger);
  if (!installed) throw new Error('WinZapp call media bridge is not available');
  const enabled = await setCallMediaBridgeActive(client, true);
  if (!enabled) throw new Error('WinZapp call media bridge could not be enabled');
  return true;
}

async function stopAudioBridge(req: Request): Promise<void> {
  await setCallMediaBridgeActive(req.client as any, false);
}

export async function acceptCall(req: Request, res: Response) {
  try {
    await prepareAudioBridge(req);
    ok(res, await evaluateWppCall(req, 'accept', req.body || {}));
  } catch (error) {
    await stopAudioBridge(req);
    fail(req, res, 'acceptCall', error);
  }
}

export async function rejectCall(req: Request, res: Response) {
  try {
    await stopAudioBridge(req);
    ok(res, await evaluateWppCall(req, 'reject', req.body || {}));
  } catch (error) {
    fail(req, res, 'rejectCall', error);
  }
}

export async function endCall(req: Request, res: Response) {
  try {
    await stopAudioBridge(req);
    ok(res, await evaluateWppCall(req, 'end', req.body || {}));
  } catch (error) {
    fail(req, res, 'endCall', error);
  }
}

export async function offerCall(req: Request, res: Response) {
  try {
    const body = req.body || {};
    if (!body.to) {
      res.status(400).json({ status: 'error', message: 'Parameter to is required!' });
      return;
    }
    await prepareAudioBridge(req);
    ok(res, await evaluateWppCall(req, 'offer', body));
  } catch (error) {
    await stopAudioBridge(req);
    fail(req, res, 'offerCall', error);
  }
}
