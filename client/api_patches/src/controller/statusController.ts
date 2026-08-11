import { Request, Response } from 'express';

import { unlinkAsync } from '../util/functions';

function returnError(req: Request, res: Response, error: any) {
  req.logger.error(error);
  res
    .status(500)
    .json({ status: 'Error', message: 'Erro ao enviar status.', error: error });
}

async function returnSucess(res: Response, data: any) {
  res.status(201).json({ status: 'success', response: data, mapper: 'return' });
}

/**
 * WinZapp patch: ensure the status@broadcast chat exists in the browser Store
 * before posting. `WPP.status.sendTextStatus` -> sendRawStatus ->
 * assertFindChat('status@broadcast') throws "Chat not found" when the Status
 * view was never opened in this Chrome session — the Store has no entry for
 * the virtual status chat yet — and every text-status post silently failed
 * (before the status.layer.js async fix, the failure was swallowed inside
 * page.evaluate and reported as success; now it surfaces as HTTP 500).
 * `WPP.chat.find` uses findOrCreateLatestChat, which registers the chat.
 */
async function ensureStatusChat(client: any) {
  try {
    await client.page.evaluate(async () => {
      const WPP = (window as any).WPP;
      if (WPP?.chat?.find) {
        try {
          await WPP.chat.find('status@broadcast');
        } catch (e) {
          // findOrCreateLatestChat can reject for the virtual status chat on
          // some WA versions — the send below still runs and may succeed.
        }
      }
    });
  } catch (e) {
    // never block the actual post on this best-effort warm-up
  }
}

export async function sendTextStorie(req: Request, res: Response) {
  /**
     #swagger.tags = ["Status Stories"]
     #swagger.autoBody=false
     #swagger.security = [{
            "bearerAuth": []
     }]
     #swagger.parameters["session"] = {
      schema: 'NERDWHATS_AMERICA'
     }
     #swagger.parameters["obj"] = {
      in: 'body',
      schema: {
        text: 'My new storie',
        options: { backgroundColor: '#0275d8', font: 2},
      }
     }
     #swagger.requestBody = {
      required: true,
      content: {
        'application/json': {
          schema: {
            type: 'object',
            properties: {
              text: { type: 'string' },
              options: { type: 'object' },
            },
            required: ['text'],
          },
          examples: {
            'Default': {
              value: {
                text: 'My new storie',
                options: { backgroundColor: '#0275d8', font: 2},
              },
            },
          },
        },
      },
    }
   */
  const { text, options } = req.body;

  if (!text)
    res.status(401).send({
      message: 'Text was not informed',
    });

  try {
    await ensureStatusChat(req.client);
    const results: any = [];
    results.push(await req.client.sendTextStatus(text, options));

    if (results.length === 0)
      res.status(400).json('Error sending the text of stories');
    returnSucess(res, results);
  } catch (error) {
    returnError(req, res, error);
  }
}

export async function sendImageStorie(req: Request, res: Response) {
  /**
     #swagger.tags = ["Status Stories"]
     #swagger.autoBody=false
     #swagger.security = [{
            "bearerAuth": []
     }]
     #swagger.parameters["session"] = {
      schema: 'NERDWHATS_AMERICA'
     }
     #swagger.requestBody = {
      required: true,
      content: {
        'application/json': {
          schema: {
            type: 'object',
            properties: {
              path: { type: 'string' },
            },
            required: ['path'],
          },
          examples: {
            'Default': {
              value: {
                path: 'Path of your image',
              },
            },
          },
        },
      },
    }
   */
  const { path } = req.body;

  if (!path && !req.file)
    res.status(401).send({
      message: 'Sending the image is mandatory',
    });

  const pathFile = path || req.file?.path;

  try {
    await ensureStatusChat(req.client);
    const results: any = [];
    results.push(await req.client.sendImageStatus(pathFile));

    if (results.length === 0)
      res.status(400).json('Error sending the image of stories');
    returnSucess(res, results);
  } catch (error) {
    returnError(req, res, error);
  }
}

export async function sendVideoStorie(req: Request, res: Response) {
  /**
     #swagger.tags = ["Status Stories"]
     #swagger.autoBody=false
     #swagger.security = [{
            "bearerAuth": []
     }]
     #swagger.parameters["session"] = {
      schema: 'NERDWHATS_AMERICA'
     }
     #swagger.requestBody = {
      required: true,
      content: {
        "application/json": {
          schema: {
            type: "object",
            properties: {
              path: { type: "string" }
            },
            required: ["path"]
          },
          examples: {
            "Default": {
              value: {
                path: "Path of your video"
              }
            }
          }
        }
      }
    }
   */
  const { path } = req.body;

  if (!path && !req.file)
    res.status(401).send({
      message: 'Sending the Video is mandatory',
    });

  const pathFile = path || req.file?.path;

  try {
    await ensureStatusChat(req.client);
    const results: any = [];

    results.push(await req.client.sendVideoStatus(pathFile));

    if (results.length === 0) res.status(400).json('Error sending message');
    if (req.file) await unlinkAsync(pathFile);
    returnSucess(res, results);
  } catch (error) {
    returnError(req, res, error);
  }
}

/**
 * WinZapp patch: GET /api/:session/statuses — pull the user's own posted
 * statuses (and other contacts' statuses) straight from the account's
 * StatusV3Store, instead of relying solely on status@broadcast messages
 * arriving over the Socket.IO channel (which WhatsApp Web only emits once
 * the Status view has been opened in the browser, so the WinZapp Status tab
 * stayed empty on fresh sessions).
 */
export async function getStatuses(req: Request, res: Response) {
  /**
     #swagger.tags = ["Status Stories"]
     #swagger.autoBody=false
     #swagger.security = [{
            "bearerAuth": []
     }]
   */
  try {
    const result = await req.client.page.evaluate(async () => {
      const WPP = (window as any).WPP;
      const out: any = { myStatus: [], contacts: [] };
      if (!WPP?.status) return out;

      const serialize = (m: any) => {
        try {
          if ((window as any).WAPI?._serializeRawObj) {
            return (window as any).WAPI._serializeRawObj(m);
          }
          return m?.toJSON ? m.toJSON() : m;
        } catch (e) {
          return null;
        }
      };

      // Own posted statuses, straight from the account.
      try {
        const my = await WPP.status.getMyStatus();
        const msgs = my?.getAllMsgs ? my.getAllMsgs() : [];
        out.myStatus = (msgs || []).map(serialize).filter(Boolean);
      } catch (e) {
        // not paired/ready yet — leave myStatus empty
      }

      // Other contacts' statuses from the StatusV3 collection.
      try {
        const store = WPP?.whatsapp?.StatusV3Store;
        const models = store?.models || [];
        const me = WPP.conn?.getMyUserWid?.()?.toString?.() ?? '';
        for (const model of models) {
          try {
            const author = model?.id?._serialized || model?.id || '';
            if (!author || author === me) continue; // own status handled above
            const msgs = model?.getAllMsgs ? model.getAllMsgs() : [];
            if (!msgs || !msgs.length) continue;
            out.contacts.push({
              jid: author,
              msgs: msgs.map(serialize).filter(Boolean),
            });
          } catch (e) {
            // skip a broken entry
          }
        }
      } catch (e) {
        // Store not reachable — contacts stay empty
      }

      return out;
    });
    returnSucess(res, result);
  } catch (error) {
    returnError(req, res, error);
  }
}
