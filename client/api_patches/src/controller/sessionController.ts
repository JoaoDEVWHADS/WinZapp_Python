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
 * See the License for the specific language governing permclearSessionissions and
 * limitations under the License.
 */
import { Message, Whatsapp } from '@wppconnect-team/wppconnect';
import { Request, Response } from 'express';
import fs from 'fs';
import mime from 'mime-types';
import QRCode from 'qrcode';
import { Logger } from 'winston';

import { version } from '../../package.json';
import config from '../config';
import CreateSessionUtil from '../util/createSessionUtil';
import { callWebHook, contactToArray } from '../util/functions';
import getAllTokens from '../util/getAllTokens';
import { clientsArray, deleteSessionOnArray } from '../util/sessionUtil';

const SessionUtil = new CreateSessionUtil();

async function downloadFileFunction(
  message: Message,
  client: Whatsapp,
  logger: Logger
) {
  try {
    const buffer = await client.decryptFile(message);

    const filename = `./WhatsAppImages/file${message.t}`;
    if (!fs.existsSync(filename)) {
      let result = '';
      if (message.type === 'ptt') {
        result = `${filename}.oga`;
      } else {
        result = `${filename}.${mime.extension(message.mimetype)}`;
      }

      await fs.writeFile(result, buffer, (err) => {
        if (err) {
          logger.error(err);
        }
      });

      return result;
    } else {
      return `${filename}.${mime.extension(message.mimetype)}`;
    }
  } catch (e) {
    logger.error(e);
    logger.warn(
      'Erro ao descriptografar a midia, tentando fazer o download direto...'
    );
    try {
      const buffer = await client.downloadMedia(message);
      const filename = `./WhatsAppImages/file${message.t}`;
      if (!fs.existsSync(filename)) {
        let result = '';
        if (message.type === 'ptt') {
          result = `${filename}.oga`;
        } else {
          result = `${filename}.${mime.extension(message.mimetype)}`;
        }

        await fs.writeFile(result, buffer, (err) => {
          if (err) {
            logger.error(err);
          }
        });

        return result;
      } else {
        return `${filename}.${mime.extension(message.mimetype)}`;
      }
    } catch (e) {
      logger.error(e);
      logger.warn('Não foi possível baixar a mídia...');
    }
  }
}

export async function download(message: any, client: any, logger: any) {
  try {
    const path = await downloadFileFunction(message, client, logger);
    return path?.replace('./', '');
  } catch (e) {
    logger.error(e);
  }
}

export async function startAllSessions(
  req: Request,
  res: Response
): Promise<any> {
  /**
   * #swagger.tags = ["Auth"]
     #swagger.autoBody=false
     #swagger.operationId = 'startAllSessions'
     #swagger.security = [{
            "bearerAuth": []
     }]
     #swagger.parameters["session"] = {
      schema: 'NERDWHATS_AMERICA'
     }
     #swagger.parameters["secretkey"] = {
      schema: 'THISISMYSECURECODE'
     }
   */
  const { secretkey } = req.params;
  const { authorization: token } = req.headers;

  let tokenDecrypt = '';

  if (secretkey === undefined) {
    tokenDecrypt = (token as any).split(' ')[0];
  } else {
    tokenDecrypt = secretkey;
  }

  const allSessions = await getAllTokens(req);

  if (tokenDecrypt !== req.serverOptions.secretKey) {
    res.status(400).json({
      response: 'error',
      message: 'The token is incorrect',
    });
  }

  allSessions.map(async (session: string) => {
    const util = new CreateSessionUtil();
    await util.opendata(req, session);
  });

  return await res
    .status(201)
    .json({ status: 'success', message: 'Starting all sessions' });
}

export async function showAllSessions(
  req: Request,
  res: Response
): Promise<any> {
  /**
   * #swagger.tags = ["Auth"]
     #swagger.autoBody=false
     #swagger.operationId = 'showAllSessions'
     #swagger.autoQuery=false
     #swagger.autoHeaders=false
     #swagger.security = [{
            "bearerAuth": []
     }]
     #swagger.parameters["secretkey"] = {
      schema: 'THISISMYSECURETOKEN'
     }
   */
  const { secretkey } = req.params;
  const { authorization: token } = req.headers;

  let tokenDecrypt: any = '';

  if (secretkey === undefined) {
    tokenDecrypt = token?.split(' ')[0];
  } else {
    tokenDecrypt = secretkey;
  }

  const arr: any = [];

  if (tokenDecrypt !== req.serverOptions.secretKey) {
    res.status(400).json({
      response: false,
      message: 'The token is incorrect',
    });
  }

  Object.keys(clientsArray).forEach((item) => {
    arr.push({ session: item });
  });

  res.status(200).json({ response: await getAllTokens(req) });
}

export async function startSession(req: Request, res: Response): Promise<any> {
  /**
   * #swagger.tags = ["Auth"]
     #swagger.autoBody=false
     #swagger.operationId = 'startSession'
     #swagger.security = [{
            "bearerAuth": []
     }]
     #swagger.parameters["session"] = {
      schema: 'NERDWHATS_AMERICA'
     }
     #swagger.requestBody = {
      required: true,
      "@content": {
        "application/json": {
          schema: {
            type: "object",
            properties: {
              webhook: { type: "string" },
              waitQrCode: { type: "boolean" },
              proxy: {
                type: "object",
                properties: {
                  url: { type: "string" },
                  username: { type: "string" },
                  password: { type: "string" },
                }
              }
            }
          },
          example: {
            webhook: "",
            waitQrCode: false,
            proxy: {
              url: "http://myproxy.com:8080",
              username: "myuser",
              password: "mypassword"
            }
          }
        }
      }
     }
   */
  const session = req.session;
  const { waitQrCode = false } = req.body;

  await getSessionState(req, res);
  await SessionUtil.opendata(req, session, waitQrCode ? res : null);
}

export async function closeSession(req: Request, res: Response): Promise<any> {
  /**
   * #swagger.tags = ["Auth"]
     #swagger.operationId = 'closeSession'
     #swagger.autoBody=true
     #swagger.security = [{
            "bearerAuth": []
     }]
     #swagger.parameters["session"] = {
      schema: 'NERDWHATS_AMERICA'
     }
   */
  const session = req.session;
  try {
    const client = (clientsArray as any)[session];
    if (!client) {
      return await res
        .status(200)
        .json({ status: true, message: 'Session successfully closed' });
    }

    if (client.status !== 'CONNECTED' && client.status !== 'open') {
      req.logger.info(`[${session}] Force killing session because status is ${client.status}`);
      client.shouldClose = true;
      try {
        SessionUtil.forceKillSession(session);
      } catch (e) {}
      (clientsArray as any)[session] = undefined;
      return await res
        .status(200)
        .json({ status: true, message: 'Session force closed' });
    }

    (clientsArray as any)[session] = { status: null };

    if (req.client && typeof req.client.close === 'function') {
      await req.client.close();
    }
      req.io.emit('whatsapp-status', false);
      callWebHook(req.client, req, 'closesession', {
        message: `Session: ${session} disconnected`,
        connected: false,
      });

      return await res
        .status(200)
        .json({ status: true, message: 'Session successfully closed' });
  } catch (error) {
    req.logger.error(error);
    return await res
      .status(500)
      .json({ status: false, message: 'Error closing session', error });
  }
}

export async function logOutSession(req: Request, res: Response): Promise<any> {
  /**
   * #swagger.tags = ["Auth"]
     #swagger.operationId = 'logoutSession'
   * #swagger.description = 'This route logout and delete session data'
     #swagger.autoBody=false
     #swagger.security = [{
            "bearerAuth": []
     }]
     #swagger.parameters["session"] = {
      schema: 'NERDWHATS_AMERICA'
     }
   */
  try {
    const session = req.session;
    await req.client.logout();
    deleteSessionOnArray(req.session);

    setTimeout(async () => {
      const pathUserData = config.customUserDataDir + req.session;
      const pathTokens = __dirname + `../../../tokens/${req.session}.data.json`;

      if (fs.existsSync(pathUserData)) {
        await fs.promises.rm(pathUserData, {
          recursive: true,
          maxRetries: 5,
          force: true,
          retryDelay: 1000,
        });
      }
      if (fs.existsSync(pathTokens)) {
        await fs.promises.rm(pathTokens, {
          recursive: true,
          maxRetries: 5,
          force: true,
          retryDelay: 1000,
        });
      }

      req.io.emit('whatsapp-status', false);
      callWebHook(req.client, req, 'logoutsession', {
        message: `Session: ${session} logged out`,
        connected: false,
      });

      return await res
        .status(200)
        .json({ status: true, message: 'Session successfully closed' });
    }, 500);
    /*try {
      await req.client.close();
    } catch (error) {}*/
  } catch (error) {
    req.logger.error(error);
    res
      .status(500)
      .json({ status: false, message: 'Error closing session', error });
  }
}

export async function checkConnectionSession(
  req: Request,
  res: Response
): Promise<any> {
  /**
   * #swagger.tags = ["Auth"]
     #swagger.operationId = 'CheckConnectionState'
     #swagger.autoBody=false
     #swagger.security = [{
            "bearerAuth": []
     }]
     #swagger.parameters["session"] = {
      schema: 'NERDWHATS_AMERICA'
     }
   */
  try {
    await req.client.isConnected();

    res.status(200).json({ status: true, message: 'Connected' });
  } catch (error) {
    res.status(200).json({ status: false, message: 'Disconnected' });
  }
}

export async function downloadMediaByMessage(req: Request, res: Response) {
  /**
   * #swagger.tags = ["Messages"]
     #swagger.autoBody=false
     #swagger.operationId = 'downloadMediabyMessage'
     #swagger.security = [{
            "bearerAuth": []
     }]
     #swagger.parameters["session"] = {
      schema: 'NERDWHATS_AMERICA'
     }
     #swagger.requestBody = {
      required: true,
      "@content": {
        "application/json": {
          schema: {
            type: "object",
            properties: {
              messageId: { type: "string" },
            }
          },
          example: {
            messageId: '<messageId>'
          }
        }
      }
     }
   */
  const client = req.client;
  const { messageId } = req.body;

  if (!client || typeof client.getMessageById !== 'function') {
    return res.status(400).json({
      status: 'error',
      message: 'The WhatsApp session is not active.',
    });
  }

  let message;

  try {
    if (!messageId.isMedia || !messageId.type) {
      message = await client.getMessageById(messageId);
    } else {
      message = messageId;
    }

    if (!message)
      res.status(400).json({
        status: 'error',
        message: 'Message not found',
      });

    if (!(message['mimetype'] || message.isMedia || message.isMMS))
      res.status(400).json({
        status: 'error',
        message: 'Message does not contain media',
      });

    const buffer = await client.decryptFile(message);

    res
      .status(200)
      .json({ base64: buffer.toString('base64'), mimetype: message.mimetype });
  } catch (e) {
    req.logger.error(e);
    res.status(400).json({
      status: 'error',
      message: 'Decrypt file error',
      error: e,
    });
  }
}

export async function getMediaByMessage(req: Request, res: Response) {
  /**
   * #swagger.tags = ["Messages"]
     #swagger.autoBody=false
     #swagger.operationId = 'getMediaByMessage'
     #swagger.security = [{
            "bearerAuth": []
     }]
     #swagger.parameters["session"] = {
      schema: 'NERDWHATS_AMERICA'
     }
     #swagger.parameters["session"] = {
      schema: 'messageId'
     }
   */
  const client = req.client;
  const { messageId } = req.params;

  if (!client || typeof client.getMessageById !== 'function') {
    return res.status(400).json({
      status: 'error',
      message: 'The WhatsApp session is not active.',
    });
  }

  // Normalize 4-part message ID (fromMe_chatId_msgId_participantLid) to 3-part standard ID
  let lookupId = messageId;
  const parts = messageId ? messageId.split('_') : [];
  if (parts.length === 4) {
    lookupId = `${parts[0]}_${parts[1]}_${parts[2]}`;
  }

  try {
    let message: any = null;

    // If details are provided in the request body (e.g. POST request with local cache) AND contain a valid URL, use them directly.
    const bodyUrl = req.body ? (req.body.clientUrl || req.body.url || req.body.deprecatedMms3Url || req.body.directPath || req.body.mediaUrl) : null;
    if (req.body && req.body.mediaKey && bodyUrl) {
      req.logger.info(`Received decryption keys and valid media URL in body for message ${messageId}. Bypassing Puppeteer lookup.`);
      message = req.body;
      let effectiveUrl = bodyUrl;
      if (typeof effectiveUrl === 'string' && effectiveUrl.startsWith('/')) {
        effectiveUrl = `https://mmg.whatsapp.net${effectiveUrl}`;
      }
      message.clientUrl = effectiveUrl;
      message.deprecatedMms3Url = effectiveUrl;
      message.url = effectiveUrl;
      message.mediaUrl = effectiveUrl;
      message.directPath = message.directPath || effectiveUrl;

      // Normalise key types and structures if needed by decryptFile
      if (typeof message.mediaKey === 'object' && message.mediaKey.data) {
        message.mediaKey = Buffer.from(message.mediaKey.data);
      } else if (typeof message.mediaKey === 'string') {
        message.mediaKey = Buffer.from(message.mediaKey, 'base64');
      }
    } else {
      try {
        message = await client.getMessageById(lookupId);
      } catch (err: any) {}
      if (!message && lookupId !== messageId) {
        try {
          message = await client.getMessageById(messageId);
        } catch (_) {}
      }

      // Robust fallback: query WhatsApp Web Store via WPP.chat.getMsg or scanning chat messages by ID prefix
      if (!message && client.page && !client.page.isClosed()) {
        try {
          const browserMsg = await client.page.evaluate(async (mId: string, lId: string) => {
            try {
              if ((window as any).WPP && (window as any).WPP.chat) {
                let msg = await (window as any).WPP.chat.getMsg(mId).catch(() => null)
                       || await (window as any).WPP.chat.getMsg(lId).catch(() => null);
                if (!msg && lId) {
                  const parts = lId.split('_');
                  if (parts.length >= 2) {
                    const chatId = parts[1];
                    const msgs = await (window as any).WPP.chat.getMessages(chatId, { count: 100 }).catch(() => []);
                    msg = msgs.find((m: any) => m && m.id && (m.id._serialized === mId || m.id._serialized === lId || m.id._serialized.startsWith(lId)));
                  }
                }
                if (msg) return JSON.parse(JSON.stringify(msg));
              }
            } catch (_) {}
            return null;
          }, messageId, lookupId);
          if (browserMsg) {
            message = browserMsg;
            req.logger.info(`Found message ${messageId} in browser Store via WPP.chat.getMsg`);
          }
        } catch (evalMsgErr) {
          req.logger.warn(`Browser evaluate message lookup error for ${messageId}: ${evalMsgErr}`);
        }
      }
    }

    // If message not found or doesn't have mediaUrl, try direct WPP.chat.downloadMedia in page evaluate
    const mediaUrl = message ? (message.clientUrl || message.deprecatedMms3Url || message.url || message.directPath) : null;
    if (!message || !mediaUrl) {
      req.logger.info(`Attempting direct browser-side media download via WPP for ${messageId}...`);
      try {
          if (client.page && !client.page.isClosed()) {
            try {
              const resultData: { base64Data: string | null, msgObj: any } | null = await Promise.race([
                client.page.evaluate(async (msgId: string, lId: string) => {
                  try {
                    if ((window as any).WPP && (window as any).WPP.chat) {
                      let msg = await (window as any).WPP.chat.getMsg(msgId).catch(() => null)
                             || await (window as any).WPP.chat.getMsg(lId).catch(() => null);
                      if (!msg && lId) {
                        const parts = lId.split('_');
                        if (parts.length >= 2) {
                          const chatId = parts[1];
                          const msgs = await (window as any).WPP.chat.getMessages(chatId, { count: 100 }).catch(() => []);
                          msg = msgs.find((m: any) => m && m.id && (m.id._serialized === msgId || m.id._serialized === lId || m.id._serialized.startsWith(lId)));
                        }
                      }

                      const blob = await (window as any).WPP.chat.downloadMedia(msgId).catch(() => null)
                                || await (window as any).WPP.chat.downloadMedia(lId).catch(() => null);
                      let b64: string | null = null;
                      if (blob && blob instanceof Blob) {
                        b64 = await new Promise<string>((resolve) => {
                          const reader = new FileReader();
                          reader.onloadend = () => resolve(reader.result as string);
                          reader.readAsDataURL(blob);
                        });
                      }
                      return { base64Data: b64, msgObj: msg ? JSON.parse(JSON.stringify(msg)) : null };
                    }
                    if ((window as any).WAPI && typeof (window as any).WAPI.downloadFile === 'function') {
                      const b64 = await (window as any).WAPI.downloadFile(msgId).catch(() => null)
                               || await (window as any).WAPI.downloadFile(lId).catch(() => null);
                      if (b64) return { base64Data: b64, msgObj: null };
                    }
                  } catch (err) {
                    return null;
                  }
                  return null;
                }, messageId, lookupId),
                new Promise<null>((resolve) => setTimeout(() => resolve(null), 6000))
              ]);

              if (resultData) {
                if (resultData.msgObj) {
                  message = resultData.msgObj;
                }
                if (resultData.base64Data) {
                  let mimetype = (message && message.mimetype) || 'audio/ogg';
                  let base64Clean = resultData.base64Data;
                  if (resultData.base64Data.startsWith('data:')) {
                    const matches = resultData.base64Data.match(/^data:(.*?);base64,(.*)$/);
                    if (matches) {
                      mimetype = matches[1];
                      base64Clean = matches[2];
                    }
                  }
                  req.logger.info(`Successfully retrieved media via WPP browser evaluate for ${messageId}`);
                  return res.status(200).json({ base64: base64Clean, mimetype });
                }
              }
            } catch (evalInnerErr) {
              req.logger.warn(`Browser evaluate media download skipped for ${messageId}: ${evalInnerErr}`);
            }
          }
        } catch (evalErr) {
          req.logger.error(`Error in WPP direct browser media download: ${evalErr}`);
        }
      }

    if (!message) {
      return res.status(400).json({
        status: 'error',
        message: `Message ${messageId} not found`,
      });
    }

    // Ensure mediaUrl and clientUrl/deprecatedMms3Url properties are fully populated early for decryptFile and WPPConnect helpers
    let effectiveUrl = message.clientUrl || message.deprecatedMms3Url || message.url || message.directPath || message.mediaUrl;
    if (effectiveUrl) {
      if (typeof effectiveUrl === 'string' && effectiveUrl.startsWith('/')) {
        effectiveUrl = `https://mmg.whatsapp.net${effectiveUrl}`;
      }
      message.clientUrl = effectiveUrl;
      message.deprecatedMms3Url = effectiveUrl;
      message.url = effectiveUrl;
      message.mediaUrl = effectiveUrl;
      message.directPath = message.directPath || effectiveUrl;
    }

    // Fast path: Try direct file decryption first if mediaKey and effectiveUrl are available
    if (message.mediaKey && effectiveUrl) {
      try {
        const buffer = await client.decryptFile(message);
        req.logger.info(`Successfully decrypted media via fast-path decryptFile for ${messageId}`);
        return res
          .status(200)
          .json({ base64: buffer.toString('base64'), mimetype: message.mimetype || 'audio/ogg' });
      } catch (fastDecryptErr) {
        req.logger.warn(`Fast decryptFile failed for ${messageId}: ${fastDecryptErr}. Proceeding to browser download fallback...`);
      }
    }

    // 1. Primary approach: Try WPPConnect's downloadMedia using active browser context with normalized lookupId (short 2.5s timeout)
    if (typeof (client as any).downloadMedia === 'function') {
      try {
        let timer: any;
        const downloadPromise = ((client as any).downloadMedia(lookupId).catch(() => null)
                             || (client as any).downloadMedia(messageId).catch(() => null)).finally(() => {
          if (timer) clearTimeout(timer);
        });
        const timeoutPromise = new Promise<string>((_, reject) => {
          timer = setTimeout(() => reject(new Error('Timeout downloading media via Puppeteer')), 2500);
        });
        let base64: string = await Promise.race([downloadPromise, timeoutPromise]);
        if (base64) {
          let mimetype = message.mimetype || 'audio/ogg';
          if (base64.startsWith('data:')) {
            const matches = base64.match(/^data:(.*?);base64,(.*)$/);
            if (matches) {
              mimetype = matches[1];
              base64 = matches[2];
            }
          }
          req.logger.info(`Successfully downloaded media via client.downloadMedia for ${messageId}`);
          return res.status(200).json({ base64, mimetype });
        }
      } catch (dlErr) {
        req.logger.warn(`Primary client.downloadMedia failed for ${messageId}: ${dlErr}. Falling back to decryptFile...`);
      }
    }

    // 2. Fallback approach: Try direct file decryption
    try {
      const buffer = await client.decryptFile(message);
      return res
        .status(200)
        .json({ base64: buffer.toString('base64'), mimetype: message.mimetype || 'audio/ogg' });
    } catch (decryptErr) {
      req.logger.error(`decryptFile failed for ${messageId}: ${decryptErr}`);
      
      // Attempt browser-side recovery: fetch the message fresh from WhatsApp Web to get updated CDN URLs
      let freshMessage: any = null;
      try {
        freshMessage = await client.getMessageById(messageId);
      } catch (err) {}

      if (!freshMessage && messageId) {
        const parts = messageId.split('_');
        if (parts.length >= 2) {
          const chatId = parts[1];
          if (chatId && typeof client.loadEarlierMessages === 'function') {
            try {
              await client.loadEarlierMessages(chatId);
              freshMessage = await client.getMessageById(messageId);
            } catch (err) {}
          }
        }
      }

      if (freshMessage) {
        try {
          req.logger.info(`Found fresh message in browser for ${messageId}, attempting decryption...`);
          const buffer = await client.decryptFile(freshMessage);
          return res.status(200).json({
            base64: buffer.toString('base64'),
            mimetype: freshMessage.mimetype || 'audio/ogg'
          });
        } catch (freshDecryptErr) {
          req.logger.error(`Decryption of fresh browser message failed: ${freshDecryptErr}`);
        }
      }
      throw decryptErr; // rethrow to trigger the 500 block if both failed
    }
  } catch (ex) {
    req.logger.error(ex);
    res.status(500).json({
      status: 'error',
      message: 'Failed to decrypt file',
      error: ex instanceof Error ? ex.message : ex,
    });
  }
}

export async function getSessionState(req: Request, res: Response) {
  /**
     #swagger.tags = ["Auth"]
     #swagger.operationId = 'getSessionState'
     #swagger.summary = 'Retrieve status of a session'
     #swagger.autoBody = false
     #swagger.security = [{
            "bearerAuth": []
     }]
     #swagger.parameters["session"] = {
      schema: 'NERDWHATS_AMERICA'
     }
   */
  try {
    const { waitQrCode = false } = req.body;
    const client = req.client;
    const qr =
      client?.urlcode != null && client?.urlcode != ''
        ? await QRCode.toDataURL(client.urlcode)
        : null;

    if ((client == null || client.status == null) && !waitQrCode)
      res.status(200).json({ status: 'CLOSED', qrcode: null });
    else if (client != null)
      res.status(200).json({
        status: client.status,
        qrcode: qr,
        urlcode: client.urlcode,
        version: version,
      });
  } catch (ex) {
    req.logger.error(ex);
    res.status(500).json({
      status: 'error',
      message: 'The session is not active',
      error: ex,
    });
  }
}

export async function getQrCode(req: Request, res: Response) {
  /**
   * #swagger.tags = ["Auth"]
     #swagger.autoBody=false
     #swagger.operationId = 'getQrCode'
     #swagger.security = [{
            "bearerAuth": []
     }]
     #swagger.parameters["session"] = {
      schema: 'NERDWHATS_AMERICA'
     }
   */
  try {
    if (req?.client?.urlcode) {
      // We add options to generate the QR code in higher resolution
      // The /qrcode-session request will now return a readable qrcode.
      const qrOptions = {
        errorCorrectionLevel: 'M' as const,
        type: 'image/png' as const,
        scale: 5,
        width: 500,
      };
      const qr = req.client.urlcode
        ? await QRCode.toDataURL(req.client.urlcode, qrOptions)
        : null;
      const img = Buffer.from(
        (qr as any).replace(/^data:image\/(png|jpeg|jpg);base64,/, ''),
        'base64'
      );
      res.writeHead(200, {
        'Content-Type': 'image/png',
        'Content-Length': img.length,
      });
      res.end(img);
    } else if (typeof req.client === 'undefined') {
      res.status(200).json({
        status: null,
        message:
          'Session not started. Please, use the /start-session route, for initialization your session',
      });
    } else {
      res.status(200).json({
        status: req.client.status,
        message: 'QRCode is not available...',
      });
    }
  } catch (ex) {
    req.logger.error(ex);
    res
      .status(500)
      .json({ status: 'error', message: 'Error retrieving QRCode', error: ex });
  }
}

export async function killServiceWorker(req: Request, res: Response) {
  /**
   * #swagger.ignore=true
   * #swagger.tags = ["Messages"]
     #swagger.operationId = 'killServiceWorkier'
     #swagger.autoBody=false
     #swagger.security = [{
            "bearerAuth": []
     }]
     #swagger.parameters["session"] = {
      schema: 'NERDWHATS_AMERICA'
     }
   */
  try {
    res.status(200).json({ status: 'error', response: 'Not implemented yet' });
  } catch (ex) {
    req.logger.error(ex);
    res.status(500).json({
      status: 'error',
      message: 'The session is not active',
      error: ex,
    });
  }
}

export async function restartService(req: Request, res: Response) {
  /**
   * #swagger.ignore=true
   * #swagger.tags = ["Messages"]
     #swagger.operationId = 'restartService'
     #swagger.autoBody=false
     #swagger.security = [{
            "bearerAuth": []
     }]
     #swagger.parameters["session"] = {
      schema: 'NERDWHATS_AMERICA'
     }
   */
  try {
    res.status(200).json({ status: 'error', response: 'Not implemented yet' });
  } catch (ex) {
    req.logger.error(ex);
    res.status(500).json({
      status: 'error',
      response: { message: 'The session is not active', error: ex },
    });
  }
}

export async function subscribePresence(req: Request, res: Response) {
  /**
   * #swagger.tags = ["Misc"]
     #swagger.operationId = 'subscribePresence'
     #swagger.autoBody=false
     #swagger.security = [{
            "bearerAuth": []
     }]
     #swagger.parameters["session"] = {
      schema: 'NERDWHATS_AMERICA'
     }
     #swagger.requestBody = {
      required: true,
      "@content": {
        "application/json": {
          schema: {
            type: "object",
            properties: {
              phone: { type: "string" },
              isGroup: { type: "boolean" },
              all: { type: "boolean" },
            }
          },
          example: {
            phone: '5521999999999',
            isGroup: false,
            all: false,
          }
        }
      }
     }
   */
  try {
    const { phone, isGroup = false, all = false, isLid = false } = req.body;

    const subscribeOne = async (contato: string) => {
      // Prefer the modern WPP.contact.subscribePresence which works with
      // current WhatsApp Web. The legacy req.client.subscribePresence uses
      // the internal WAPI that calls Store.Presence.find() — broken in newer
      // WA versions and returns 500. We fall back to the legacy path if the
      // WPP API is not available.
      const page = (req.client as any).page;
      if (page) {
        try {
          await page.evaluate((id: string) => {
            const wpp = (window as any).WPP;
            if (wpp && wpp.contact && typeof wpp.contact.subscribePresence === 'function') {
              return wpp.contact.subscribePresence(id);
            }
            // Fallback to WPP.whatsapp.PresenceUtils if available
            if (wpp && wpp.whatsapp && wpp.whatsapp.PresenceUtils) {
              return wpp.whatsapp.PresenceUtils.subscribeToPresence(id);
            }
            throw new Error('WPP.contact.subscribePresence not available');
          }, contato);
          req.logger.info(`[subscribePresence] WPP subscribed: ${contato}`);
          return;
        } catch (wppErr) {
          req.logger.warn(`[subscribePresence] WPP fallback for ${contato}: ${wppErr}`);
        }
      }
      // Legacy fallback
      await req.client.subscribePresence(contato);
    };

    if (all) {
      let contacts;
      if (isGroup) {
        const groups = await req.client.getAllGroups(false);
        contacts = groups.map((p: any) => p.id._serialized);
      } else {
        const chats = await req.client.getAllContacts();
        contacts = chats.map((c: any) => c.id._serialized);
      }
      for (const contato of contacts) {
        await subscribeOne(contato);
      }
    } else {
      for (const contato of contactToArray(phone, isGroup, false, isLid)) {
        await subscribeOne(contato);
      }
    }

    res.status(200).json({
      status: 'success',
      response: { message: 'Subscribe presence executed' },
    });
  } catch (error) {
    req.logger.error(error);
    res.status(500).json({
      status: 'error',
      message: 'Error on subscribe presence',
      error: error,
    });
  }
}

export async function setOnlinePresence(req: Request, res: Response) {
  /**
   * #swagger.tags = ["Misc"]
     #swagger.operationId = 'setOnlinePresence'
     #swagger.autoBody=false
     #swagger.security = [{
            "bearerAuth": []
     }]
     #swagger.parameters["session"] = {
      schema: 'NERDWHATS_AMERICA'
     }
     #swagger.requestBody = {
      required: true,
      "@content": {
        "application/json": {
          schema: {
            type: "object",
            properties: {
              isOnline: { type: "boolean" },
            }
          },
          example: {
   isOnline: false,
          }
        }
      }
     }
   */
  try {
    const { isOnline = true } = req.body;

    await req.client.setOnlinePresence(isOnline);

    res.status(200).json({
      status: 'success',
      response: { message: 'Set Online Presence Successfully' },
    });
  } catch (error) {
    res.status(500).json({
      status: 'error',
      message: 'Error on set online presence',
      error: error,
    });
  }
}

export async function editBusinessProfile(req: Request, res: Response) {
  /**
   * #swagger.tags = ["Profile"]
     #swagger.operationId = 'editBusinessProfile'
   * #swagger.description = 'Edit your bussiness profile'
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
        $adress: 'Av. Nossa Senhora de Copacabana, 315',
        $email: 'test@test.com.br',
        $categories: {
          $id: "133436743388217",
          $localized_display_name: "Artes e entretenimento",
          $not_a_biz: false,
        },
        $website: [
          "https://www.wppconnect.io",
          "https://www.teste2.com.br",
        ],
      }
     }
     
     #swagger.requestBody = {
      required: true,
      "@content": {
        "application/json": {
          schema: {
            type: "object",
            properties: {
              adress: { type: "string" },
              email: { type: "string" },
              categories: { type: "object" },
              websites: { type: "array" },
            }
          },
          example: {
            adress: 'Av. Nossa Senhora de Copacabana, 315',
            email: 'test@test.com.br',
            categories: {
              $id: "133436743388217",
              $localized_display_name: "Artes e entretenimento",
              $not_a_biz: false,
            },
            website: [
              "https://www.wppconnect.io",
              "https://www.teste2.com.br",
            ],
          }
        }
      }
     }
   */
  try {
    res.status(200).json(await req.client.editBusinessProfile(req.body));
  } catch (error) {
    res.status(500).json({
      status: 'error',
      message: 'Error on edit business profile',
      error: error,
    });
  }
}
