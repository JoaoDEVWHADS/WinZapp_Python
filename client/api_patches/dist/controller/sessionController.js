"use strict";var _interopRequireDefault = require("@babel/runtime/helpers/interopRequireDefault");Object.defineProperty(exports, "__esModule", { value: true });exports.checkConnectionSession = checkConnectionSession;exports.closeSession = closeSession;exports.download = download;exports.downloadMediaByMessage = downloadMediaByMessage;exports.editBusinessProfile = editBusinessProfile;exports.getMediaByMessage = getMediaByMessage;exports.getQrCode = getQrCode;exports.getSessionState = getSessionState;exports.killServiceWorker = killServiceWorker;exports.logOutSession = logOutSession;exports.reconnectSocketStream = reconnectSocketStream;exports.restartService = restartService;exports.setOnlinePresence = setOnlinePresence;exports.showAllSessions = showAllSessions;exports.startAllSessions = startAllSessions;exports.startSession = startSession;exports.subscribePresence = subscribePresence;
















var _fs = _interopRequireDefault(require("fs"));
var _mimeTypes = _interopRequireDefault(require("mime-types"));
var _qrcode = _interopRequireDefault(require("qrcode"));


var _package = require("../../package.json");
var _config = _interopRequireDefault(require("../config"));
var _createSessionUtil = _interopRequireDefault(require("../util/createSessionUtil"));
var _functions = require("../util/functions");
var _getAllTokens = _interopRequireDefault(require("../util/getAllTokens"));
var _sessionUtil = require("../util/sessionUtil"); /*
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
 */const SessionUtil = new _createSessionUtil.default();async function downloadFileFunction(message, client, logger) {try {const buffer = await client.decryptFile(message);const filename = `./WhatsAppImages/file${message.t}`;if (!_fs.default.existsSync(filename)) {let result = '';
      if (message.type === 'ptt') {
        result = `${filename}.oga`;
      } else {
        result = `${filename}.${_mimeTypes.default.extension(message.mimetype)}`;
      }

      await _fs.default.writeFile(result, buffer, (err) => {
        if (err) {
          logger.error(err);
        }
      });

      return result;
    } else {
      return `${filename}.${_mimeTypes.default.extension(message.mimetype)}`;
    }
  } catch (e) {
    logger.error(e);
    logger.warn(
      'Erro ao descriptografar a midia, tentando fazer o download direto...'
    );
    try {
      const buffer = await client.downloadMedia(message);
      const filename = `./WhatsAppImages/file${message.t}`;
      if (!_fs.default.existsSync(filename)) {
        let result = '';
        if (message.type === 'ptt') {
          result = `${filename}.oga`;
        } else {
          result = `${filename}.${_mimeTypes.default.extension(message.mimetype)}`;
        }

        await _fs.default.writeFile(result, buffer, (err) => {
          if (err) {
            logger.error(err);
          }
        });

        return result;
      } else {
        return `${filename}.${_mimeTypes.default.extension(message.mimetype)}`;
      }
    } catch (e) {
      logger.error(e);
      logger.warn('Não foi possível baixar a mídia...');
    }
  }
}

async function download(message, client, logger) {
  try {
    const path = await downloadFileFunction(message, client, logger);
    return path?.replace('./', '');
  } catch (e) {
    logger.error(e);
  }
}

async function startAllSessions(
req,
res)
{
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
    tokenDecrypt = token.split(' ')[0];
  } else {
    tokenDecrypt = secretkey;
  }

  const allSessions = await (0, _getAllTokens.default)(req);

  if (tokenDecrypt !== req.serverOptions.secretKey) {
    res.status(400).json({
      response: 'error',
      message: 'The token is incorrect'
    });
  }

  allSessions.map(async (session) => {
    const util = new _createSessionUtil.default();
    await util.opendata(req, session);
  });

  return await res.
  status(201).
  json({ status: 'success', message: 'Starting all sessions' });
}

async function showAllSessions(
req,
res)
{
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

  let tokenDecrypt = '';

  if (secretkey === undefined) {
    tokenDecrypt = token?.split(' ')[0];
  } else {
    tokenDecrypt = secretkey;
  }

  const arr = [];

  if (tokenDecrypt !== req.serverOptions.secretKey) {
    res.status(400).json({
      response: false,
      message: 'The token is incorrect'
    });
  }

  Object.keys(_sessionUtil.clientsArray).forEach((item) => {
    arr.push({ session: item });
  });

  res.status(200).json({ response: await (0, _getAllTokens.default)(req) });
}

async function startSession(req, res) {
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

async function closeSession(req, res) {
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
    const client = _sessionUtil.clientsArray[session];
    if (!client) {
      return await res.
      status(200).
      json({ status: true, message: 'Session successfully closed' });
    }

    if (client.status !== 'CONNECTED' && client.status !== 'open') {
      req.logger.info(`[${session}] Force killing session because status is ${client.status}`);
      client.shouldClose = true;
      try {
        SessionUtil.forceKillSession(session, req.logger);
      } catch (e) {}
      _sessionUtil.clientsArray[session] = undefined;
      return await res.
      status(200).
      json({ status: true, message: 'Session force closed' });
    }

    _sessionUtil.clientsArray[session] = { status: null };

    if (req.client && typeof req.client.close === 'function') {
      await req.client.close();
    }
    req.io.emit('whatsapp-status', false);
    (0, _functions.callWebHook)(req.client, req, 'closesession', {
      message: `Session: ${session} disconnected`,
      connected: false
    });

    return await res.
    status(200).
    json({ status: true, message: 'Session successfully closed' });
  } catch (error) {
    req.logger.error(error);
    return await res.
    status(500).
    json({ status: false, message: 'Error closing session', error });
  }
}

async function logOutSession(req, res) {
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
    (0, _sessionUtil.deleteSessionOnArray)(req.session);

    setTimeout(async () => {
      const pathUserData = _config.default.customUserDataDir + req.session;
      const pathTokens = __dirname + `../../../tokens/${req.session}.data.json`;

      if (_fs.default.existsSync(pathUserData)) {
        await _fs.default.promises.rm(pathUserData, {
          recursive: true,
          maxRetries: 5,
          force: true,
          retryDelay: 1000
        });
      }
      if (_fs.default.existsSync(pathTokens)) {
        await _fs.default.promises.rm(pathTokens, {
          recursive: true,
          maxRetries: 5,
          force: true,
          retryDelay: 1000
        });
      }

      req.io.emit('whatsapp-status', false);
      (0, _functions.callWebHook)(req.client, req, 'logoutsession', {
        message: `Session: ${session} logged out`,
        connected: false
      });

      return await res.
      status(200).
      json({ status: true, message: 'Session successfully closed' });
    }, 500);
    /*try {
      await req.client.close();
    } catch (error) {}*/
  } catch (error) {
    req.logger.error(error);
    res.
    status(500).
    json({ status: false, message: 'Error closing session', error });
  }
}

async function checkConnectionSession(
req,
res)
{
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

// WinZapp patch: nudge WhatsApp Web's own multi-device socket back open.
//
// Reported live: after the OS resumes from sleep, WinZapp's status-session
// probe keeps reporting the WPPConnect session object as "CONNECTED" (that
// string is just cached at session creation — see checkConnectionSession's
// own comment above it), but the *live* isConnected() probe never comes back
// true again, forever — the app is stuck offline until the whole program is
// restarted (a fresh Puppeteer/Chrome + fresh page).
//
// The real WhatsApp Web client re-opens its socket stream via
// WPP.whatsapp.Cmd.openSocketStream() — normally triggered by the page's own
// visibility/focus/online DOM events. This session's Chrome page runs
// headless and is never focused or brought to the foreground, so nothing
// ever fires those events after a suspend/resume cycle — the socket that
// went down during sleep has no trigger left to reconnect it, unlike a real,
// visible browser tab a user might click back into. Calling the same
// internal command directly reproduces whatever a focus/visibility event
// would have triggered on a normal tab.
async function reconnectSocketStream(req, res) {
  /**
   * #swagger.tags = ["Auth"]
     #swagger.autoBody=false
     #swagger.security = [{
            "bearerAuth": []
     }]
     #swagger.parameters["session"] = {
      schema: 'NERDWHATS_AMERICA'
     }
   */
  try {
    const page = req.client?.page;
    if (!page || page.isClosed()) {
      return res.status(400).json({
        status: 'error',
        message: 'The WhatsApp session is not active.'
      });
    }
    const result = await page.evaluate(() => {
      try {
        const wpp = window.WPP;
        if (wpp?.whatsapp?.Cmd?.openSocketStream) {
          wpp.whatsapp.Cmd.openSocketStream();
          return { ok: true };
        }
        return { ok: false, error: 'WPP.whatsapp.Cmd.openSocketStream not available' };
      } catch (e) {
        return { ok: false, error: e?.message || String(e) };
      }
    });
    if (!result?.ok) {
      req.logger.warn(`[reconnectSocketStream] ${result?.error || 'unknown failure'}`);
    }
    res.status(200).json({ status: 'success', response: result });
  } catch (error) {
    req.logger.error(error);
    res.status(500).json({
      status: 'error',
      message: error?.message || String(error)
    });
  }
}

async function downloadMediaByMessage(req, res) {
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
      message: 'The WhatsApp session is not active.'
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
      message: 'Message not found'
    });

    if (!(message['mimetype'] || message.isMedia || message.isMMS))
    res.status(400).json({
      status: 'error',
      message: 'Message does not contain media'
    });

    const buffer = await client.decryptFile(message);

    res.
    status(200).
    json({ base64: buffer.toString('base64'), mimetype: message.mimetype });
  } catch (e) {
    req.logger.error(e);
    res.status(400).json({
      status: 'error',
      message: 'Decrypt file error',
      error: e
    });
  }
}

async function getMediaByMessage(req, res) {
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
      message: 'The WhatsApp session is not active.'
    });
  }

  try {
    let message = null;

    // If details are provided in the request body (e.g. POST request with local cache), use them directly.
    if (req.body && (req.body.mediaKey || req.body.clientUrl)) {
      req.logger.info(`Received decryption keys in body for message ${messageId}. Bypassing Puppeteer lookup.`);
      message = req.body;
      // Normalise key types and structures if needed by decryptFile
      if (typeof message.mediaKey === 'object' && message.mediaKey.data) {
        message.mediaKey = Buffer.from(message.mediaKey.data);
      } else if (typeof message.mediaKey === 'string') {
        message.mediaKey = Buffer.from(message.mediaKey, 'base64');
      }
    } else {
      try {
        message = await client.getMessageById(messageId);
      } catch (err) {
        req.logger.warn(`client.getMessageById threw error: ${err.message || err}. Trying fallback...`);
      }

      // Fallback: If message is not found, it might not be loaded in the WhatsApp Web cache.
      // Try to parse the chatId from the serialized messageId (format: fromMe_chatId_msgId_participant)
      // and load earlier messages to force sync it.
      if (!message && messageId) {
        const parts = messageId.split('_');
        if (parts.length >= 2) {
          const chatId = parts[1]; // e.g. 120363420948134065@g.us or phone@c.us
          if (chatId) {
            req.logger.info(`Message ${messageId} not found in cache. Attempting WPP.chat.find & loadEarlierMessages for ${chatId}`);
            try {
              if (client.page && !client.page.isClosed()) {
                message = await client.page.evaluate(async ({ msgId, targetChatId }) => {
                  try {
                    const WPP = window.WPP;
                    const Store = window.Store;

                    // Helper 1: Convert string JID to Wid if possible
                    let targetWid = targetChatId;
                    if (WPP?.whatsapp?.WidFactory?.create) {
                      try {
                        targetWid = WPP.whatsapp.WidFactory.create(targetChatId);
                      } catch (e) {}
                    }

                    // Helper 2: Ensure chat is loaded
                    if (WPP?.chat?.find) {
                      try {await WPP.chat.find(targetChatId);} catch (e) {}
                      try {if (targetWid !== targetChatId) await WPP.chat.find(targetWid);} catch (e) {}
                      try {
                        if (targetChatId.includes('@c.us')) {
                          await WPP.chat.find(targetChatId.replace(/@c\.us/g, '@s.whatsapp.net'));
                        }
                      } catch (e) {}
                    }

                    if (WPP?.chat?.loadEarlierMessages) {
                      try {await WPP.chat.loadEarlierMessages(targetChatId);} catch (e) {}
                    }

                    // Helper 3: Deep search message
                    const getMsgSafe = async (mId) => {
                      if (!mId) return null;
                      if (WPP?.chat?.getMessageById) {
                        try {
                          const m = await WPP.chat.getMessageById(mId);
                          if (m) return m;
                        } catch (e) {}
                        try {
                          if (mId.includes('@c.us')) {
                            const m = await WPP.chat.getMessageById(mId.replace(/@c\.us/g, '@s.whatsapp.net'));
                            if (m) return m;
                          } else if (mId.includes('@s.whatsapp.net')) {
                            const m = await WPP.chat.getMessageById(mId.replace(/@s\.whatsapp\.net/g, '@c.us'));
                            if (m) return m;
                          }
                        } catch (e) {}
                      }

                      // Fallback: search Store.Msg.models by raw message ID
                      const parts = mId.split('_');
                      const rawId = parts.length > 2 ? parts[2] : mId;
                      if (Store?.Msg?.models) {
                        const found = Store.Msg.models.find((item) => {
                          if (!item || !item.id) return false;
                          const ser = item.id._serialized || '';
                          const itemId = item.id.id || '';
                          return itemId === rawId || ser === mId || rawId && ser.includes(rawId);
                        });
                        if (found) return found;
                      }
                      return null;
                    };

                    return await getMsgSafe(msgId);
                  } catch (e) {
                    console.log(`[browser-evaluate getMediaByMessage fallback error]: ${e}`);
                    return null;
                  }
                }, { msgId: messageId, targetChatId: chatId });
              }

              // Second check if evaluate returned null but client.getMessageById might work now
              if (!message && typeof client.getMessageById === 'function') {
                try {
                  message = await client.getMessageById(messageId);
                } catch (retryErr) {
                  req.logger.error(`Retry getMessageById failed: ${retryErr.message || retryErr}`);
                }
              }
            } catch (loadErr) {
              req.logger.error(`Error executing getMediaByMessage fallback: ${loadErr}`);
            }
          }
        }
      }
    }

    if (!message) {
      return res.status(400).json({
        status: 'error',
        message: `Message ${messageId} not found`
      });
    }

    // Ensure client browser context is alive
    if (client.page && client.page.isClosed()) {
      req.logger.warn(`Browser page is closed for session when downloading media ${messageId}`);
      return res.status(503).json({
        status: 'error',
        message: 'Browser session is closed or re-connecting'
      });
    }

    // Ensure it contains media properties or has mimetype
    const mediaUrl = message.clientUrl || message.deprecatedMms3Url;
    if (!mediaUrl) {
      if (typeof client.downloadMedia === 'function' && client.page && !client.page.isClosed()) {
        req.logger.info(`Message ${messageId} does not have clientUrl. Trying client.downloadMedia with 5s timeout...`);
        try {
          let timer;
          const downloadPromise = client.downloadMedia(messageId).catch((err) => {
            req.logger.warn(`client.downloadMedia caught inner error: ${err}`);
            return null;
          }).finally(() => {
            if (timer) clearTimeout(timer);
          });
          const timeoutPromise = new Promise((resolve) => {
            timer = setTimeout(() => {
              req.logger.warn(`Timeout 5000ms reached for client.downloadMedia (${messageId})`);
              resolve(null);
            }, 5000);
          });
          let base64 = await Promise.race([downloadPromise, timeoutPromise]);
          if (base64) {
            let mimetype = message.mimetype || 'audio/ogg';
            if (base64.startsWith('data:')) {
              const matches = base64.match(/^data:(.*?);base64,(.*)$/);
              if (matches) {
                mimetype = matches[1];
                base64 = matches[2];
              }
            }
            return res.status(200).json({ base64, mimetype });
          }
        } catch (downloadErr) {
          req.logger.error(`Error in client.downloadMedia fallback: ${downloadErr}`);
        }
      }
      return res.status(400).json({
        status: 'error',
        message: 'Message does not contain media download URL'
      });
    }

    try {
      const buffer = await client.decryptFile(message);
      res.
      status(200).
      json({ base64: buffer.toString('base64'), mimetype: message.mimetype || 'audio/ogg' });
    } catch (decryptErr) {
      req.logger.error(`decryptFile failed, trying browser-side recovery: ${decryptErr}`);

      // Attempt browser-side recovery: fetch the message fresh from WhatsApp Web to get updated CDN URLs
      let freshMessage = null;
      if (client.page && !client.page.isClosed()) {
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

      // Final fallback to WPPConnect's downloadMedia
      if (typeof client.downloadMedia === 'function' && client.page && !client.page.isClosed()) {
        try {
          let timer;
          const downloadPromise = client.downloadMedia(messageId).catch((err) => {
            req.logger.warn(`client.downloadMedia caught inner error: ${err}`);
            return null;
          }).finally(() => {
            if (timer) clearTimeout(timer);
          });
          const timeoutPromise = new Promise((resolve) => {
            timer = setTimeout(() => {
              req.logger.warn(`Timeout 5000ms reached for client.downloadMedia (${messageId})`);
              resolve(null);
            }, 5000);
          });
          let base64 = await Promise.race([downloadPromise, timeoutPromise]);
          if (base64) {
            let mimetype = (freshMessage || message).mimetype || 'audio/ogg';
            if (base64.startsWith('data:')) {
              const matches = base64.match(/^data:(.*?);base64,(.*)$/);
              if (matches) {
                mimetype = matches[1];
                base64 = matches[2];
              }
            }
            return res.status(200).json({ base64, mimetype });
          }
        } catch (downloadErr) {
          req.logger.error(`Error in client.downloadMedia fallback after decryption error: ${downloadErr}`);
        }
      }
      throw decryptErr; // rethrow to trigger the 500 block if both failed
    }
  } catch (ex) {
    req.logger.error(ex);
    res.status(500).json({
      status: 'error',
      message: 'Failed to decrypt file',
      error: ex instanceof Error ? ex.message : ex
    });
  }
}

async function getSessionState(req, res) {
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
    client?.urlcode != null && client?.urlcode != '' ?
    await _qrcode.default.toDataURL(client.urlcode) :
    null;

    if ((client == null || client.status == null) && !waitQrCode)
    res.status(200).json({ status: 'CLOSED', qrcode: null });else
    if (client != null)
    res.status(200).json({
      status: client.status,
      qrcode: qr,
      urlcode: client.urlcode,
      version: _package.version
    });
  } catch (ex) {
    req.logger.error(ex);
    res.status(500).json({
      status: 'error',
      message: 'The session is not active',
      error: ex
    });
  }
}

async function getQrCode(req, res) {
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
        errorCorrectionLevel: 'M',
        type: 'image/png',
        scale: 5,
        width: 500
      };
      const qr = req.client.urlcode ?
      await _qrcode.default.toDataURL(req.client.urlcode, qrOptions) :
      null;
      const img = Buffer.from(
        qr.replace(/^data:image\/(png|jpeg|jpg);base64,/, ''),
        'base64'
      );
      res.writeHead(200, {
        'Content-Type': 'image/png',
        'Content-Length': img.length
      });
      res.end(img);
    } else if (typeof req.client === 'undefined') {
      res.status(200).json({
        status: null,
        message:
        'Session not started. Please, use the /start-session route, for initialization your session'
      });
    } else {
      res.status(200).json({
        status: req.client.status,
        message: 'QRCode is not available...'
      });
    }
  } catch (ex) {
    req.logger.error(ex);
    res.
    status(500).
    json({ status: 'error', message: 'Error retrieving QRCode', error: ex });
  }
}

async function killServiceWorker(req, res) {
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
      error: ex
    });
  }
}

async function restartService(req, res) {
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
      response: { message: 'The session is not active', error: ex }
    });
  }
}

async function subscribePresence(req, res) {
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

    const subscribeOne = async (contato) => {
      // Prefer the modern WPP.contact.subscribePresence which works with
      // current WhatsApp Web. The legacy req.client.subscribePresence uses
      // the internal WAPI that calls Store.Presence.find() — broken in newer
      // WA versions and returns 500. We fall back to the legacy path if the
      // WPP API is not available.
      const page = req.client.page;
      if (page) {
        try {
          await page.evaluate((id) => {
            const wpp = window.WPP;
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
        contacts = groups.map((p) => p.id._serialized);
      } else {
        const chats = await req.client.getAllContacts();
        contacts = chats.map((c) => c.id._serialized);
      }
      for (const contato of contacts) {
        await subscribeOne(contato);
      }
    } else {
      for (const contato of (0, _functions.contactToArray)(phone, isGroup, false, isLid)) {
        await subscribeOne(contato);
      }
    }

    res.status(200).json({
      status: 'success',
      response: { message: 'Subscribe presence executed' }
    });
  } catch (error) {
    req.logger.error(error);
    res.status(500).json({
      status: 'error',
      message: 'Error on subscribe presence',
      error: error
    });
  }
}

async function setOnlinePresence(req, res) {
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
      response: { message: 'Set Online Presence Successfully' }
    });
  } catch (error) {
    res.status(500).json({
      status: 'error',
      message: 'Error on set online presence',
      error: error
    });
  }
}

async function editBusinessProfile(req, res) {
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
      error: error
    });
  }
}
//# sourceMappingURL=data:application/json;charset=utf-8;base64,eyJ2ZXJzaW9uIjozLCJuYW1lcyI6WyJfZnMiLCJfaW50ZXJvcFJlcXVpcmVEZWZhdWx0IiwicmVxdWlyZSIsIl9taW1lVHlwZXMiLCJfcXJjb2RlIiwiX3BhY2thZ2UiLCJfY29uZmlnIiwiX2NyZWF0ZVNlc3Npb25VdGlsIiwiX2Z1bmN0aW9ucyIsIl9nZXRBbGxUb2tlbnMiLCJfc2Vzc2lvblV0aWwiLCJTZXNzaW9uVXRpbCIsIkNyZWF0ZVNlc3Npb25VdGlsIiwiZG93bmxvYWRGaWxlRnVuY3Rpb24iLCJtZXNzYWdlIiwiY2xpZW50IiwibG9nZ2VyIiwiYnVmZmVyIiwiZGVjcnlwdEZpbGUiLCJmaWxlbmFtZSIsInQiLCJmcyIsImV4aXN0c1N5bmMiLCJyZXN1bHQiLCJ0eXBlIiwibWltZSIsImV4dGVuc2lvbiIsIm1pbWV0eXBlIiwid3JpdGVGaWxlIiwiZXJyIiwiZXJyb3IiLCJlIiwid2FybiIsImRvd25sb2FkTWVkaWEiLCJkb3dubG9hZCIsInBhdGgiLCJyZXBsYWNlIiwic3RhcnRBbGxTZXNzaW9ucyIsInJlcSIsInJlcyIsInNlY3JldGtleSIsInBhcmFtcyIsImF1dGhvcml6YXRpb24iLCJ0b2tlbiIsImhlYWRlcnMiLCJ0b2tlbkRlY3J5cHQiLCJ1bmRlZmluZWQiLCJzcGxpdCIsImFsbFNlc3Npb25zIiwiZ2V0QWxsVG9rZW5zIiwic2VydmVyT3B0aW9ucyIsInNlY3JldEtleSIsInN0YXR1cyIsImpzb24iLCJyZXNwb25zZSIsIm1hcCIsInNlc3Npb24iLCJ1dGlsIiwib3BlbmRhdGEiLCJzaG93QWxsU2Vzc2lvbnMiLCJhcnIiLCJPYmplY3QiLCJrZXlzIiwiY2xpZW50c0FycmF5IiwiZm9yRWFjaCIsIml0ZW0iLCJwdXNoIiwic3RhcnRTZXNzaW9uIiwid2FpdFFyQ29kZSIsImJvZHkiLCJnZXRTZXNzaW9uU3RhdGUiLCJjbG9zZVNlc3Npb24iLCJpbmZvIiwic2hvdWxkQ2xvc2UiLCJmb3JjZUtpbGxTZXNzaW9uIiwiY2xvc2UiLCJpbyIsImVtaXQiLCJjYWxsV2ViSG9vayIsImNvbm5lY3RlZCIsImxvZ091dFNlc3Npb24iLCJsb2dvdXQiLCJkZWxldGVTZXNzaW9uT25BcnJheSIsInNldFRpbWVvdXQiLCJwYXRoVXNlckRhdGEiLCJjb25maWciLCJjdXN0b21Vc2VyRGF0YURpciIsInBhdGhUb2tlbnMiLCJfX2Rpcm5hbWUiLCJwcm9taXNlcyIsInJtIiwicmVjdXJzaXZlIiwibWF4UmV0cmllcyIsImZvcmNlIiwicmV0cnlEZWxheSIsImNoZWNrQ29ubmVjdGlvblNlc3Npb24iLCJpc0Nvbm5lY3RlZCIsInJlY29ubmVjdFNvY2tldFN0cmVhbSIsInBhZ2UiLCJpc0Nsb3NlZCIsImV2YWx1YXRlIiwid3BwIiwid2luZG93IiwiV1BQIiwid2hhdHNhcHAiLCJDbWQiLCJvcGVuU29ja2V0U3RyZWFtIiwib2siLCJTdHJpbmciLCJkb3dubG9hZE1lZGlhQnlNZXNzYWdlIiwibWVzc2FnZUlkIiwiZ2V0TWVzc2FnZUJ5SWQiLCJpc01lZGlhIiwiaXNNTVMiLCJiYXNlNjQiLCJ0b1N0cmluZyIsImdldE1lZGlhQnlNZXNzYWdlIiwibWVkaWFLZXkiLCJjbGllbnRVcmwiLCJkYXRhIiwiQnVmZmVyIiwiZnJvbSIsInBhcnRzIiwibGVuZ3RoIiwiY2hhdElkIiwibXNnSWQiLCJ0YXJnZXRDaGF0SWQiLCJTdG9yZSIsInRhcmdldFdpZCIsIldpZEZhY3RvcnkiLCJjcmVhdGUiLCJjaGF0IiwiZmluZCIsImluY2x1ZGVzIiwibG9hZEVhcmxpZXJNZXNzYWdlcyIsImdldE1zZ1NhZmUiLCJtSWQiLCJtIiwicmF3SWQiLCJNc2ciLCJtb2RlbHMiLCJmb3VuZCIsImlkIiwic2VyIiwiX3NlcmlhbGl6ZWQiLCJpdGVtSWQiLCJjb25zb2xlIiwibG9nIiwicmV0cnlFcnIiLCJsb2FkRXJyIiwibWVkaWFVcmwiLCJkZXByZWNhdGVkTW1zM1VybCIsInRpbWVyIiwiZG93bmxvYWRQcm9taXNlIiwiY2F0Y2giLCJmaW5hbGx5IiwiY2xlYXJUaW1lb3V0IiwidGltZW91dFByb21pc2UiLCJQcm9taXNlIiwicmVzb2x2ZSIsInJhY2UiLCJzdGFydHNXaXRoIiwibWF0Y2hlcyIsIm1hdGNoIiwiZG93bmxvYWRFcnIiLCJkZWNyeXB0RXJyIiwiZnJlc2hNZXNzYWdlIiwiZnJlc2hEZWNyeXB0RXJyIiwiZXgiLCJFcnJvciIsInFyIiwidXJsY29kZSIsIlFSQ29kZSIsInRvRGF0YVVSTCIsInFyY29kZSIsInZlcnNpb24iLCJnZXRRckNvZGUiLCJxck9wdGlvbnMiLCJlcnJvckNvcnJlY3Rpb25MZXZlbCIsInNjYWxlIiwid2lkdGgiLCJpbWciLCJ3cml0ZUhlYWQiLCJlbmQiLCJraWxsU2VydmljZVdvcmtlciIsInJlc3RhcnRTZXJ2aWNlIiwic3Vic2NyaWJlUHJlc2VuY2UiLCJwaG9uZSIsImlzR3JvdXAiLCJhbGwiLCJpc0xpZCIsInN1YnNjcmliZU9uZSIsImNvbnRhdG8iLCJjb250YWN0IiwiUHJlc2VuY2VVdGlscyIsInN1YnNjcmliZVRvUHJlc2VuY2UiLCJ3cHBFcnIiLCJjb250YWN0cyIsImdyb3VwcyIsImdldEFsbEdyb3VwcyIsInAiLCJjaGF0cyIsImdldEFsbENvbnRhY3RzIiwiYyIsImNvbnRhY3RUb0FycmF5Iiwic2V0T25saW5lUHJlc2VuY2UiLCJpc09ubGluZSIsImVkaXRCdXNpbmVzc1Byb2ZpbGUiXSwic291cmNlcyI6WyIuLi8uLi9zcmMvY29udHJvbGxlci9zZXNzaW9uQ29udHJvbGxlci50cyJdLCJzb3VyY2VzQ29udGVudCI6WyIvKlxuICogQ29weXJpZ2h0IDIwMjEgV1BQQ29ubmVjdCBUZWFtXG4gKlxuICogTGljZW5zZWQgdW5kZXIgdGhlIEFwYWNoZSBMaWNlbnNlLCBWZXJzaW9uIDIuMCAodGhlIFwiTGljZW5zZVwiKTtcbiAqIHlvdSBtYXkgbm90IHVzZSB0aGlzIGZpbGUgZXhjZXB0IGluIGNvbXBsaWFuY2Ugd2l0aCB0aGUgTGljZW5zZS5cbiAqIFlvdSBtYXkgb2J0YWluIGEgY29weSBvZiB0aGUgTGljZW5zZSBhdFxuICpcbiAqICAgICBodHRwOi8vd3d3LmFwYWNoZS5vcmcvbGljZW5zZXMvTElDRU5TRS0yLjBcbiAqXG4gKiBVbmxlc3MgcmVxdWlyZWQgYnkgYXBwbGljYWJsZSBsYXcgb3IgYWdyZWVkIHRvIGluIHdyaXRpbmcsIHNvZnR3YXJlXG4gKiBkaXN0cmlidXRlZCB1bmRlciB0aGUgTGljZW5zZSBpcyBkaXN0cmlidXRlZCBvbiBhbiBcIkFTIElTXCIgQkFTSVMsXG4gKiBXSVRIT1VUIFdBUlJBTlRJRVMgT1IgQ09ORElUSU9OUyBPRiBBTlkgS0lORCwgZWl0aGVyIGV4cHJlc3Mgb3IgaW1wbGllZC5cbiAqIFNlZSB0aGUgTGljZW5zZSBmb3IgdGhlIHNwZWNpZmljIGxhbmd1YWdlIGdvdmVybmluZyBwZXJtY2xlYXJTZXNzaW9uaXNzaW9ucyBhbmRcbiAqIGxpbWl0YXRpb25zIHVuZGVyIHRoZSBMaWNlbnNlLlxuICovXG5pbXBvcnQgeyBNZXNzYWdlLCBXaGF0c2FwcCB9IGZyb20gJ0B3cHBjb25uZWN0LXRlYW0vd3BwY29ubmVjdCc7XG5pbXBvcnQgeyBSZXF1ZXN0LCBSZXNwb25zZSB9IGZyb20gJ2V4cHJlc3MnO1xuaW1wb3J0IGZzIGZyb20gJ2ZzJztcbmltcG9ydCBtaW1lIGZyb20gJ21pbWUtdHlwZXMnO1xuaW1wb3J0IFFSQ29kZSBmcm9tICdxcmNvZGUnO1xuaW1wb3J0IHsgTG9nZ2VyIH0gZnJvbSAnd2luc3Rvbic7XG5cbmltcG9ydCB7IHZlcnNpb24gfSBmcm9tICcuLi8uLi9wYWNrYWdlLmpzb24nO1xuaW1wb3J0IGNvbmZpZyBmcm9tICcuLi9jb25maWcnO1xuaW1wb3J0IENyZWF0ZVNlc3Npb25VdGlsIGZyb20gJy4uL3V0aWwvY3JlYXRlU2Vzc2lvblV0aWwnO1xuaW1wb3J0IHsgY2FsbFdlYkhvb2ssIGNvbnRhY3RUb0FycmF5IH0gZnJvbSAnLi4vdXRpbC9mdW5jdGlvbnMnO1xuaW1wb3J0IGdldEFsbFRva2VucyBmcm9tICcuLi91dGlsL2dldEFsbFRva2Vucyc7XG5pbXBvcnQgeyBjbGllbnRzQXJyYXksIGRlbGV0ZVNlc3Npb25PbkFycmF5IH0gZnJvbSAnLi4vdXRpbC9zZXNzaW9uVXRpbCc7XG5cbmNvbnN0IFNlc3Npb25VdGlsID0gbmV3IENyZWF0ZVNlc3Npb25VdGlsKCk7XG5cbmFzeW5jIGZ1bmN0aW9uIGRvd25sb2FkRmlsZUZ1bmN0aW9uKFxuICBtZXNzYWdlOiBNZXNzYWdlLFxuICBjbGllbnQ6IFdoYXRzYXBwLFxuICBsb2dnZXI6IExvZ2dlclxuKSB7XG4gIHRyeSB7XG4gICAgY29uc3QgYnVmZmVyID0gYXdhaXQgY2xpZW50LmRlY3J5cHRGaWxlKG1lc3NhZ2UpO1xuXG4gICAgY29uc3QgZmlsZW5hbWUgPSBgLi9XaGF0c0FwcEltYWdlcy9maWxlJHttZXNzYWdlLnR9YDtcbiAgICBpZiAoIWZzLmV4aXN0c1N5bmMoZmlsZW5hbWUpKSB7XG4gICAgICBsZXQgcmVzdWx0ID0gJyc7XG4gICAgICBpZiAobWVzc2FnZS50eXBlID09PSAncHR0Jykge1xuICAgICAgICByZXN1bHQgPSBgJHtmaWxlbmFtZX0ub2dhYDtcbiAgICAgIH0gZWxzZSB7XG4gICAgICAgIHJlc3VsdCA9IGAke2ZpbGVuYW1lfS4ke21pbWUuZXh0ZW5zaW9uKG1lc3NhZ2UubWltZXR5cGUpfWA7XG4gICAgICB9XG5cbiAgICAgIGF3YWl0IGZzLndyaXRlRmlsZShyZXN1bHQsIGJ1ZmZlciwgKGVycikgPT4ge1xuICAgICAgICBpZiAoZXJyKSB7XG4gICAgICAgICAgbG9nZ2VyLmVycm9yKGVycik7XG4gICAgICAgIH1cbiAgICAgIH0pO1xuXG4gICAgICByZXR1cm4gcmVzdWx0O1xuICAgIH0gZWxzZSB7XG4gICAgICByZXR1cm4gYCR7ZmlsZW5hbWV9LiR7bWltZS5leHRlbnNpb24obWVzc2FnZS5taW1ldHlwZSl9YDtcbiAgICB9XG4gIH0gY2F0Y2ggKGUpIHtcbiAgICBsb2dnZXIuZXJyb3IoZSk7XG4gICAgbG9nZ2VyLndhcm4oXG4gICAgICAnRXJybyBhbyBkZXNjcmlwdG9ncmFmYXIgYSBtaWRpYSwgdGVudGFuZG8gZmF6ZXIgbyBkb3dubG9hZCBkaXJldG8uLi4nXG4gICAgKTtcbiAgICB0cnkge1xuICAgICAgY29uc3QgYnVmZmVyID0gYXdhaXQgY2xpZW50LmRvd25sb2FkTWVkaWEobWVzc2FnZSk7XG4gICAgICBjb25zdCBmaWxlbmFtZSA9IGAuL1doYXRzQXBwSW1hZ2VzL2ZpbGUke21lc3NhZ2UudH1gO1xuICAgICAgaWYgKCFmcy5leGlzdHNTeW5jKGZpbGVuYW1lKSkge1xuICAgICAgICBsZXQgcmVzdWx0ID0gJyc7XG4gICAgICAgIGlmIChtZXNzYWdlLnR5cGUgPT09ICdwdHQnKSB7XG4gICAgICAgICAgcmVzdWx0ID0gYCR7ZmlsZW5hbWV9Lm9nYWA7XG4gICAgICAgIH0gZWxzZSB7XG4gICAgICAgICAgcmVzdWx0ID0gYCR7ZmlsZW5hbWV9LiR7bWltZS5leHRlbnNpb24obWVzc2FnZS5taW1ldHlwZSl9YDtcbiAgICAgICAgfVxuXG4gICAgICAgIGF3YWl0IGZzLndyaXRlRmlsZShyZXN1bHQsIGJ1ZmZlciwgKGVycikgPT4ge1xuICAgICAgICAgIGlmIChlcnIpIHtcbiAgICAgICAgICAgIGxvZ2dlci5lcnJvcihlcnIpO1xuICAgICAgICAgIH1cbiAgICAgICAgfSk7XG5cbiAgICAgICAgcmV0dXJuIHJlc3VsdDtcbiAgICAgIH0gZWxzZSB7XG4gICAgICAgIHJldHVybiBgJHtmaWxlbmFtZX0uJHttaW1lLmV4dGVuc2lvbihtZXNzYWdlLm1pbWV0eXBlKX1gO1xuICAgICAgfVxuICAgIH0gY2F0Y2ggKGUpIHtcbiAgICAgIGxvZ2dlci5lcnJvcihlKTtcbiAgICAgIGxvZ2dlci53YXJuKCdOw6NvIGZvaSBwb3Nzw612ZWwgYmFpeGFyIGEgbcOtZGlhLi4uJyk7XG4gICAgfVxuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBkb3dubG9hZChtZXNzYWdlOiBhbnksIGNsaWVudDogYW55LCBsb2dnZXI6IGFueSkge1xuICB0cnkge1xuICAgIGNvbnN0IHBhdGggPSBhd2FpdCBkb3dubG9hZEZpbGVGdW5jdGlvbihtZXNzYWdlLCBjbGllbnQsIGxvZ2dlcik7XG4gICAgcmV0dXJuIHBhdGg/LnJlcGxhY2UoJy4vJywgJycpO1xuICB9IGNhdGNoIChlKSB7XG4gICAgbG9nZ2VyLmVycm9yKGUpO1xuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBzdGFydEFsbFNlc3Npb25zKFxuICByZXE6IFJlcXVlc3QsXG4gIHJlczogUmVzcG9uc2Vcbik6IFByb21pc2U8YW55PiB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiQXV0aFwiXVxuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5vcGVyYXRpb25JZCA9ICdzdGFydEFsbFNlc3Npb25zJ1xuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2VjcmV0a2V5XCJdID0ge1xuICAgICAgc2NoZW1hOiAnVEhJU0lTTVlTRUNVUkVDT0RFJ1xuICAgICB9XG4gICAqL1xuICBjb25zdCB7IHNlY3JldGtleSB9ID0gcmVxLnBhcmFtcztcbiAgY29uc3QgeyBhdXRob3JpemF0aW9uOiB0b2tlbiB9ID0gcmVxLmhlYWRlcnM7XG5cbiAgbGV0IHRva2VuRGVjcnlwdCA9ICcnO1xuXG4gIGlmIChzZWNyZXRrZXkgPT09IHVuZGVmaW5lZCkge1xuICAgIHRva2VuRGVjcnlwdCA9ICh0b2tlbiBhcyBhbnkpLnNwbGl0KCcgJylbMF07XG4gIH0gZWxzZSB7XG4gICAgdG9rZW5EZWNyeXB0ID0gc2VjcmV0a2V5O1xuICB9XG5cbiAgY29uc3QgYWxsU2Vzc2lvbnMgPSBhd2FpdCBnZXRBbGxUb2tlbnMocmVxKTtcblxuICBpZiAodG9rZW5EZWNyeXB0ICE9PSByZXEuc2VydmVyT3B0aW9ucy5zZWNyZXRLZXkpIHtcbiAgICByZXMuc3RhdHVzKDQwMCkuanNvbih7XG4gICAgICByZXNwb25zZTogJ2Vycm9yJyxcbiAgICAgIG1lc3NhZ2U6ICdUaGUgdG9rZW4gaXMgaW5jb3JyZWN0JyxcbiAgICB9KTtcbiAgfVxuXG4gIGFsbFNlc3Npb25zLm1hcChhc3luYyAoc2Vzc2lvbjogc3RyaW5nKSA9PiB7XG4gICAgY29uc3QgdXRpbCA9IG5ldyBDcmVhdGVTZXNzaW9uVXRpbCgpO1xuICAgIGF3YWl0IHV0aWwub3BlbmRhdGEocmVxLCBzZXNzaW9uKTtcbiAgfSk7XG5cbiAgcmV0dXJuIGF3YWl0IHJlc1xuICAgIC5zdGF0dXMoMjAxKVxuICAgIC5qc29uKHsgc3RhdHVzOiAnc3VjY2VzcycsIG1lc3NhZ2U6ICdTdGFydGluZyBhbGwgc2Vzc2lvbnMnIH0pO1xufVxuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24gc2hvd0FsbFNlc3Npb25zKFxuICByZXE6IFJlcXVlc3QsXG4gIHJlczogUmVzcG9uc2Vcbik6IFByb21pc2U8YW55PiB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiQXV0aFwiXVxuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5vcGVyYXRpb25JZCA9ICdzaG93QWxsU2Vzc2lvbnMnXG4gICAgICNzd2FnZ2VyLmF1dG9RdWVyeT1mYWxzZVxuICAgICAjc3dhZ2dlci5hdXRvSGVhZGVycz1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlY3JldGtleVwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ1RISVNJU01ZU0VDVVJFVE9LRU4nXG4gICAgIH1cbiAgICovXG4gIGNvbnN0IHsgc2VjcmV0a2V5IH0gPSByZXEucGFyYW1zO1xuICBjb25zdCB7IGF1dGhvcml6YXRpb246IHRva2VuIH0gPSByZXEuaGVhZGVycztcblxuICBsZXQgdG9rZW5EZWNyeXB0OiBhbnkgPSAnJztcblxuICBpZiAoc2VjcmV0a2V5ID09PSB1bmRlZmluZWQpIHtcbiAgICB0b2tlbkRlY3J5cHQgPSB0b2tlbj8uc3BsaXQoJyAnKVswXTtcbiAgfSBlbHNlIHtcbiAgICB0b2tlbkRlY3J5cHQgPSBzZWNyZXRrZXk7XG4gIH1cblxuICBjb25zdCBhcnI6IGFueSA9IFtdO1xuXG4gIGlmICh0b2tlbkRlY3J5cHQgIT09IHJlcS5zZXJ2ZXJPcHRpb25zLnNlY3JldEtleSkge1xuICAgIHJlcy5zdGF0dXMoNDAwKS5qc29uKHtcbiAgICAgIHJlc3BvbnNlOiBmYWxzZSxcbiAgICAgIG1lc3NhZ2U6ICdUaGUgdG9rZW4gaXMgaW5jb3JyZWN0JyxcbiAgICB9KTtcbiAgfVxuXG4gIE9iamVjdC5rZXlzKGNsaWVudHNBcnJheSkuZm9yRWFjaCgoaXRlbSkgPT4ge1xuICAgIGFyci5wdXNoKHsgc2Vzc2lvbjogaXRlbSB9KTtcbiAgfSk7XG5cbiAgcmVzLnN0YXR1cygyMDApLmpzb24oeyByZXNwb25zZTogYXdhaXQgZ2V0QWxsVG9rZW5zKHJlcSkgfSk7XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBzdGFydFNlc3Npb24ocmVxOiBSZXF1ZXN0LCByZXM6IFJlc3BvbnNlKTogUHJvbWlzZTxhbnk+IHtcbiAgLyoqXG4gICAqICNzd2FnZ2VyLnRhZ3MgPSBbXCJBdXRoXCJdXG4gICAgICNzd2FnZ2VyLmF1dG9Cb2R5PWZhbHNlXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ3N0YXJ0U2Vzc2lvbidcbiAgICAgI3N3YWdnZXIuc2VjdXJpdHkgPSBbe1xuICAgICAgICAgICAgXCJiZWFyZXJBdXRoXCI6IFtdXG4gICAgIH1dXG4gICAgICNzd2FnZ2VyLnBhcmFtZXRlcnNbXCJzZXNzaW9uXCJdID0ge1xuICAgICAgc2NoZW1hOiAnTkVSRFdIQVRTX0FNRVJJQ0EnXG4gICAgIH1cbiAgICAgI3N3YWdnZXIucmVxdWVzdEJvZHkgPSB7XG4gICAgICByZXF1aXJlZDogdHJ1ZSxcbiAgICAgIFwiQGNvbnRlbnRcIjoge1xuICAgICAgICBcImFwcGxpY2F0aW9uL2pzb25cIjoge1xuICAgICAgICAgIHNjaGVtYToge1xuICAgICAgICAgICAgdHlwZTogXCJvYmplY3RcIixcbiAgICAgICAgICAgIHByb3BlcnRpZXM6IHtcbiAgICAgICAgICAgICAgd2ViaG9vazogeyB0eXBlOiBcInN0cmluZ1wiIH0sXG4gICAgICAgICAgICAgIHdhaXRRckNvZGU6IHsgdHlwZTogXCJib29sZWFuXCIgfSxcbiAgICAgICAgICAgICAgcHJveHk6IHtcbiAgICAgICAgICAgICAgICB0eXBlOiBcIm9iamVjdFwiLFxuICAgICAgICAgICAgICAgIHByb3BlcnRpZXM6IHtcbiAgICAgICAgICAgICAgICAgIHVybDogeyB0eXBlOiBcInN0cmluZ1wiIH0sXG4gICAgICAgICAgICAgICAgICB1c2VybmFtZTogeyB0eXBlOiBcInN0cmluZ1wiIH0sXG4gICAgICAgICAgICAgICAgICBwYXNzd29yZDogeyB0eXBlOiBcInN0cmluZ1wiIH0sXG4gICAgICAgICAgICAgICAgfVxuICAgICAgICAgICAgICB9XG4gICAgICAgICAgICB9XG4gICAgICAgICAgfSxcbiAgICAgICAgICBleGFtcGxlOiB7XG4gICAgICAgICAgICB3ZWJob29rOiBcIlwiLFxuICAgICAgICAgICAgd2FpdFFyQ29kZTogZmFsc2UsXG4gICAgICAgICAgICBwcm94eToge1xuICAgICAgICAgICAgICB1cmw6IFwiaHR0cDovL215cHJveHkuY29tOjgwODBcIixcbiAgICAgICAgICAgICAgdXNlcm5hbWU6IFwibXl1c2VyXCIsXG4gICAgICAgICAgICAgIHBhc3N3b3JkOiBcIm15cGFzc3dvcmRcIlxuICAgICAgICAgICAgfVxuICAgICAgICAgIH1cbiAgICAgICAgfVxuICAgICAgfVxuICAgICB9XG4gICAqL1xuICBjb25zdCBzZXNzaW9uID0gcmVxLnNlc3Npb247XG4gIGNvbnN0IHsgd2FpdFFyQ29kZSA9IGZhbHNlIH0gPSByZXEuYm9keTtcblxuICBhd2FpdCBnZXRTZXNzaW9uU3RhdGUocmVxLCByZXMpO1xuICBhd2FpdCBTZXNzaW9uVXRpbC5vcGVuZGF0YShyZXEsIHNlc3Npb24sIHdhaXRRckNvZGUgPyByZXMgOiBudWxsKTtcbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIGNsb3NlU2Vzc2lvbihyZXE6IFJlcXVlc3QsIHJlczogUmVzcG9uc2UpOiBQcm9taXNlPGFueT4ge1xuICAvKipcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIkF1dGhcIl1cbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAnY2xvc2VTZXNzaW9uJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT10cnVlXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAqL1xuICBjb25zdCBzZXNzaW9uID0gcmVxLnNlc3Npb247XG4gIHRyeSB7XG4gICAgY29uc3QgY2xpZW50ID0gKGNsaWVudHNBcnJheSBhcyBhbnkpW3Nlc3Npb25dO1xuICAgIGlmICghY2xpZW50KSB7XG4gICAgICByZXR1cm4gYXdhaXQgcmVzXG4gICAgICAgIC5zdGF0dXMoMjAwKVxuICAgICAgICAuanNvbih7IHN0YXR1czogdHJ1ZSwgbWVzc2FnZTogJ1Nlc3Npb24gc3VjY2Vzc2Z1bGx5IGNsb3NlZCcgfSk7XG4gICAgfVxuXG4gICAgaWYgKGNsaWVudC5zdGF0dXMgIT09ICdDT05ORUNURUQnICYmIGNsaWVudC5zdGF0dXMgIT09ICdvcGVuJykge1xuICAgICAgcmVxLmxvZ2dlci5pbmZvKGBbJHtzZXNzaW9ufV0gRm9yY2Uga2lsbGluZyBzZXNzaW9uIGJlY2F1c2Ugc3RhdHVzIGlzICR7Y2xpZW50LnN0YXR1c31gKTtcbiAgICAgIGNsaWVudC5zaG91bGRDbG9zZSA9IHRydWU7XG4gICAgICB0cnkge1xuICAgICAgICBTZXNzaW9uVXRpbC5mb3JjZUtpbGxTZXNzaW9uKHNlc3Npb24sIHJlcS5sb2dnZXIpO1xuICAgICAgfSBjYXRjaCAoZSkge31cbiAgICAgIChjbGllbnRzQXJyYXkgYXMgYW55KVtzZXNzaW9uXSA9IHVuZGVmaW5lZDtcbiAgICAgIHJldHVybiBhd2FpdCByZXNcbiAgICAgICAgLnN0YXR1cygyMDApXG4gICAgICAgIC5qc29uKHsgc3RhdHVzOiB0cnVlLCBtZXNzYWdlOiAnU2Vzc2lvbiBmb3JjZSBjbG9zZWQnIH0pO1xuICAgIH1cblxuICAgIChjbGllbnRzQXJyYXkgYXMgYW55KVtzZXNzaW9uXSA9IHsgc3RhdHVzOiBudWxsIH07XG5cbiAgICBpZiAocmVxLmNsaWVudCAmJiB0eXBlb2YgcmVxLmNsaWVudC5jbG9zZSA9PT0gJ2Z1bmN0aW9uJykge1xuICAgICAgYXdhaXQgcmVxLmNsaWVudC5jbG9zZSgpO1xuICAgIH1cbiAgICAgIHJlcS5pby5lbWl0KCd3aGF0c2FwcC1zdGF0dXMnLCBmYWxzZSk7XG4gICAgICBjYWxsV2ViSG9vayhyZXEuY2xpZW50LCByZXEsICdjbG9zZXNlc3Npb24nLCB7XG4gICAgICAgIG1lc3NhZ2U6IGBTZXNzaW9uOiAke3Nlc3Npb259IGRpc2Nvbm5lY3RlZGAsXG4gICAgICAgIGNvbm5lY3RlZDogZmFsc2UsXG4gICAgICB9KTtcblxuICAgICAgcmV0dXJuIGF3YWl0IHJlc1xuICAgICAgICAuc3RhdHVzKDIwMClcbiAgICAgICAgLmpzb24oeyBzdGF0dXM6IHRydWUsIG1lc3NhZ2U6ICdTZXNzaW9uIHN1Y2Nlc3NmdWxseSBjbG9zZWQnIH0pO1xuICB9IGNhdGNoIChlcnJvcikge1xuICAgIHJlcS5sb2dnZXIuZXJyb3IoZXJyb3IpO1xuICAgIHJldHVybiBhd2FpdCByZXNcbiAgICAgIC5zdGF0dXMoNTAwKVxuICAgICAgLmpzb24oeyBzdGF0dXM6IGZhbHNlLCBtZXNzYWdlOiAnRXJyb3IgY2xvc2luZyBzZXNzaW9uJywgZXJyb3IgfSk7XG4gIH1cbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIGxvZ091dFNlc3Npb24ocmVxOiBSZXF1ZXN0LCByZXM6IFJlc3BvbnNlKTogUHJvbWlzZTxhbnk+IHtcbiAgLyoqXG4gICAqICNzd2FnZ2VyLnRhZ3MgPSBbXCJBdXRoXCJdXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ2xvZ291dFNlc3Npb24nXG4gICAqICNzd2FnZ2VyLmRlc2NyaXB0aW9uID0gJ1RoaXMgcm91dGUgbG9nb3V0IGFuZCBkZWxldGUgc2Vzc2lvbiBkYXRhJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgKi9cbiAgdHJ5IHtcbiAgICBjb25zdCBzZXNzaW9uID0gcmVxLnNlc3Npb247XG4gICAgYXdhaXQgcmVxLmNsaWVudC5sb2dvdXQoKTtcbiAgICBkZWxldGVTZXNzaW9uT25BcnJheShyZXEuc2Vzc2lvbik7XG5cbiAgICBzZXRUaW1lb3V0KGFzeW5jICgpID0+IHtcbiAgICAgIGNvbnN0IHBhdGhVc2VyRGF0YSA9IGNvbmZpZy5jdXN0b21Vc2VyRGF0YURpciArIHJlcS5zZXNzaW9uO1xuICAgICAgY29uc3QgcGF0aFRva2VucyA9IF9fZGlybmFtZSArIGAuLi8uLi8uLi90b2tlbnMvJHtyZXEuc2Vzc2lvbn0uZGF0YS5qc29uYDtcblxuICAgICAgaWYgKGZzLmV4aXN0c1N5bmMocGF0aFVzZXJEYXRhKSkge1xuICAgICAgICBhd2FpdCBmcy5wcm9taXNlcy5ybShwYXRoVXNlckRhdGEsIHtcbiAgICAgICAgICByZWN1cnNpdmU6IHRydWUsXG4gICAgICAgICAgbWF4UmV0cmllczogNSxcbiAgICAgICAgICBmb3JjZTogdHJ1ZSxcbiAgICAgICAgICByZXRyeURlbGF5OiAxMDAwLFxuICAgICAgICB9KTtcbiAgICAgIH1cbiAgICAgIGlmIChmcy5leGlzdHNTeW5jKHBhdGhUb2tlbnMpKSB7XG4gICAgICAgIGF3YWl0IGZzLnByb21pc2VzLnJtKHBhdGhUb2tlbnMsIHtcbiAgICAgICAgICByZWN1cnNpdmU6IHRydWUsXG4gICAgICAgICAgbWF4UmV0cmllczogNSxcbiAgICAgICAgICBmb3JjZTogdHJ1ZSxcbiAgICAgICAgICByZXRyeURlbGF5OiAxMDAwLFxuICAgICAgICB9KTtcbiAgICAgIH1cblxuICAgICAgcmVxLmlvLmVtaXQoJ3doYXRzYXBwLXN0YXR1cycsIGZhbHNlKTtcbiAgICAgIGNhbGxXZWJIb29rKHJlcS5jbGllbnQsIHJlcSwgJ2xvZ291dHNlc3Npb24nLCB7XG4gICAgICAgIG1lc3NhZ2U6IGBTZXNzaW9uOiAke3Nlc3Npb259IGxvZ2dlZCBvdXRgLFxuICAgICAgICBjb25uZWN0ZWQ6IGZhbHNlLFxuICAgICAgfSk7XG5cbiAgICAgIHJldHVybiBhd2FpdCByZXNcbiAgICAgICAgLnN0YXR1cygyMDApXG4gICAgICAgIC5qc29uKHsgc3RhdHVzOiB0cnVlLCBtZXNzYWdlOiAnU2Vzc2lvbiBzdWNjZXNzZnVsbHkgY2xvc2VkJyB9KTtcbiAgICB9LCA1MDApO1xuICAgIC8qdHJ5IHtcbiAgICAgIGF3YWl0IHJlcS5jbGllbnQuY2xvc2UoKTtcbiAgICB9IGNhdGNoIChlcnJvcikge30qL1xuICB9IGNhdGNoIChlcnJvcikge1xuICAgIHJlcS5sb2dnZXIuZXJyb3IoZXJyb3IpO1xuICAgIHJlc1xuICAgICAgLnN0YXR1cyg1MDApXG4gICAgICAuanNvbih7IHN0YXR1czogZmFsc2UsIG1lc3NhZ2U6ICdFcnJvciBjbG9zaW5nIHNlc3Npb24nLCBlcnJvciB9KTtcbiAgfVxufVxuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24gY2hlY2tDb25uZWN0aW9uU2Vzc2lvbihcbiAgcmVxOiBSZXF1ZXN0LFxuICByZXM6IFJlc3BvbnNlXG4pOiBQcm9taXNlPGFueT4ge1xuICAvKipcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIkF1dGhcIl1cbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAnQ2hlY2tDb25uZWN0aW9uU3RhdGUnXG4gICAgICNzd2FnZ2VyLmF1dG9Cb2R5PWZhbHNlXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAqL1xuICB0cnkge1xuICAgIGF3YWl0IHJlcS5jbGllbnQuaXNDb25uZWN0ZWQoKTtcblxuICAgIHJlcy5zdGF0dXMoMjAwKS5qc29uKHsgc3RhdHVzOiB0cnVlLCBtZXNzYWdlOiAnQ29ubmVjdGVkJyB9KTtcbiAgfSBjYXRjaCAoZXJyb3IpIHtcbiAgICByZXMuc3RhdHVzKDIwMCkuanNvbih7IHN0YXR1czogZmFsc2UsIG1lc3NhZ2U6ICdEaXNjb25uZWN0ZWQnIH0pO1xuICB9XG59XG5cbi8vIFdpblphcHAgcGF0Y2g6IG51ZGdlIFdoYXRzQXBwIFdlYidzIG93biBtdWx0aS1kZXZpY2Ugc29ja2V0IGJhY2sgb3Blbi5cbi8vXG4vLyBSZXBvcnRlZCBsaXZlOiBhZnRlciB0aGUgT1MgcmVzdW1lcyBmcm9tIHNsZWVwLCBXaW5aYXBwJ3Mgc3RhdHVzLXNlc3Npb25cbi8vIHByb2JlIGtlZXBzIHJlcG9ydGluZyB0aGUgV1BQQ29ubmVjdCBzZXNzaW9uIG9iamVjdCBhcyBcIkNPTk5FQ1RFRFwiICh0aGF0XG4vLyBzdHJpbmcgaXMganVzdCBjYWNoZWQgYXQgc2Vzc2lvbiBjcmVhdGlvbiDigJQgc2VlIGNoZWNrQ29ubmVjdGlvblNlc3Npb24nc1xuLy8gb3duIGNvbW1lbnQgYWJvdmUgaXQpLCBidXQgdGhlICpsaXZlKiBpc0Nvbm5lY3RlZCgpIHByb2JlIG5ldmVyIGNvbWVzIGJhY2tcbi8vIHRydWUgYWdhaW4sIGZvcmV2ZXIg4oCUIHRoZSBhcHAgaXMgc3R1Y2sgb2ZmbGluZSB1bnRpbCB0aGUgd2hvbGUgcHJvZ3JhbSBpc1xuLy8gcmVzdGFydGVkIChhIGZyZXNoIFB1cHBldGVlci9DaHJvbWUgKyBmcmVzaCBwYWdlKS5cbi8vXG4vLyBUaGUgcmVhbCBXaGF0c0FwcCBXZWIgY2xpZW50IHJlLW9wZW5zIGl0cyBzb2NrZXQgc3RyZWFtIHZpYVxuLy8gV1BQLndoYXRzYXBwLkNtZC5vcGVuU29ja2V0U3RyZWFtKCkg4oCUIG5vcm1hbGx5IHRyaWdnZXJlZCBieSB0aGUgcGFnZSdzIG93blxuLy8gdmlzaWJpbGl0eS9mb2N1cy9vbmxpbmUgRE9NIGV2ZW50cy4gVGhpcyBzZXNzaW9uJ3MgQ2hyb21lIHBhZ2UgcnVuc1xuLy8gaGVhZGxlc3MgYW5kIGlzIG5ldmVyIGZvY3VzZWQgb3IgYnJvdWdodCB0byB0aGUgZm9yZWdyb3VuZCwgc28gbm90aGluZ1xuLy8gZXZlciBmaXJlcyB0aG9zZSBldmVudHMgYWZ0ZXIgYSBzdXNwZW5kL3Jlc3VtZSBjeWNsZSDigJQgdGhlIHNvY2tldCB0aGF0XG4vLyB3ZW50IGRvd24gZHVyaW5nIHNsZWVwIGhhcyBubyB0cmlnZ2VyIGxlZnQgdG8gcmVjb25uZWN0IGl0LCB1bmxpa2UgYSByZWFsLFxuLy8gdmlzaWJsZSBicm93c2VyIHRhYiBhIHVzZXIgbWlnaHQgY2xpY2sgYmFjayBpbnRvLiBDYWxsaW5nIHRoZSBzYW1lXG4vLyBpbnRlcm5hbCBjb21tYW5kIGRpcmVjdGx5IHJlcHJvZHVjZXMgd2hhdGV2ZXIgYSBmb2N1cy92aXNpYmlsaXR5IGV2ZW50XG4vLyB3b3VsZCBoYXZlIHRyaWdnZXJlZCBvbiBhIG5vcm1hbCB0YWIuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24gcmVjb25uZWN0U29ja2V0U3RyZWFtKHJlcTogUmVxdWVzdCwgcmVzOiBSZXNwb25zZSkge1xuICAvKipcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIkF1dGhcIl1cbiAgICAgI3N3YWdnZXIuYXV0b0JvZHk9ZmFsc2VcbiAgICAgI3N3YWdnZXIuc2VjdXJpdHkgPSBbe1xuICAgICAgICAgICAgXCJiZWFyZXJBdXRoXCI6IFtdXG4gICAgIH1dXG4gICAgICNzd2FnZ2VyLnBhcmFtZXRlcnNbXCJzZXNzaW9uXCJdID0ge1xuICAgICAgc2NoZW1hOiAnTkVSRFdIQVRTX0FNRVJJQ0EnXG4gICAgIH1cbiAgICovXG4gIHRyeSB7XG4gICAgY29uc3QgcGFnZSA9IChyZXEuY2xpZW50IGFzIGFueSk/LnBhZ2U7XG4gICAgaWYgKCFwYWdlIHx8IHBhZ2UuaXNDbG9zZWQoKSkge1xuICAgICAgcmV0dXJuIHJlcy5zdGF0dXMoNDAwKS5qc29uKHtcbiAgICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgICBtZXNzYWdlOiAnVGhlIFdoYXRzQXBwIHNlc3Npb24gaXMgbm90IGFjdGl2ZS4nLFxuICAgICAgfSk7XG4gICAgfVxuICAgIGNvbnN0IHJlc3VsdCA9IGF3YWl0IHBhZ2UuZXZhbHVhdGUoKCkgPT4ge1xuICAgICAgdHJ5IHtcbiAgICAgICAgY29uc3Qgd3BwID0gKHdpbmRvdyBhcyBhbnkpLldQUDtcbiAgICAgICAgaWYgKHdwcD8ud2hhdHNhcHA/LkNtZD8ub3BlblNvY2tldFN0cmVhbSkge1xuICAgICAgICAgIHdwcC53aGF0c2FwcC5DbWQub3BlblNvY2tldFN0cmVhbSgpO1xuICAgICAgICAgIHJldHVybiB7IG9rOiB0cnVlIH07XG4gICAgICAgIH1cbiAgICAgICAgcmV0dXJuIHsgb2s6IGZhbHNlLCBlcnJvcjogJ1dQUC53aGF0c2FwcC5DbWQub3BlblNvY2tldFN0cmVhbSBub3QgYXZhaWxhYmxlJyB9O1xuICAgICAgfSBjYXRjaCAoZTogYW55KSB7XG4gICAgICAgIHJldHVybiB7IG9rOiBmYWxzZSwgZXJyb3I6IGU/Lm1lc3NhZ2UgfHwgU3RyaW5nKGUpIH07XG4gICAgICB9XG4gICAgfSk7XG4gICAgaWYgKCFyZXN1bHQ/Lm9rKSB7XG4gICAgICByZXEubG9nZ2VyLndhcm4oYFtyZWNvbm5lY3RTb2NrZXRTdHJlYW1dICR7cmVzdWx0Py5lcnJvciB8fCAndW5rbm93biBmYWlsdXJlJ31gKTtcbiAgICB9XG4gICAgcmVzLnN0YXR1cygyMDApLmpzb24oeyBzdGF0dXM6ICdzdWNjZXNzJywgcmVzcG9uc2U6IHJlc3VsdCB9KTtcbiAgfSBjYXRjaCAoZXJyb3I6IGFueSkge1xuICAgIHJlcS5sb2dnZXIuZXJyb3IoZXJyb3IpO1xuICAgIHJlcy5zdGF0dXMoNTAwKS5qc29uKHtcbiAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgIG1lc3NhZ2U6IGVycm9yPy5tZXNzYWdlIHx8IFN0cmluZyhlcnJvciksXG4gICAgfSk7XG4gIH1cbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIGRvd25sb2FkTWVkaWFCeU1lc3NhZ2UocmVxOiBSZXF1ZXN0LCByZXM6IFJlc3BvbnNlKSB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiTWVzc2FnZXNcIl1cbiAgICAgI3N3YWdnZXIuYXV0b0JvZHk9ZmFsc2VcbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAnZG93bmxvYWRNZWRpYWJ5TWVzc2FnZSdcbiAgICAgI3N3YWdnZXIuc2VjdXJpdHkgPSBbe1xuICAgICAgICAgICAgXCJiZWFyZXJBdXRoXCI6IFtdXG4gICAgIH1dXG4gICAgICNzd2FnZ2VyLnBhcmFtZXRlcnNbXCJzZXNzaW9uXCJdID0ge1xuICAgICAgc2NoZW1hOiAnTkVSRFdIQVRTX0FNRVJJQ0EnXG4gICAgIH1cbiAgICAgI3N3YWdnZXIucmVxdWVzdEJvZHkgPSB7XG4gICAgICByZXF1aXJlZDogdHJ1ZSxcbiAgICAgIFwiQGNvbnRlbnRcIjoge1xuICAgICAgICBcImFwcGxpY2F0aW9uL2pzb25cIjoge1xuICAgICAgICAgIHNjaGVtYToge1xuICAgICAgICAgICAgdHlwZTogXCJvYmplY3RcIixcbiAgICAgICAgICAgIHByb3BlcnRpZXM6IHtcbiAgICAgICAgICAgICAgbWVzc2FnZUlkOiB7IHR5cGU6IFwic3RyaW5nXCIgfSxcbiAgICAgICAgICAgIH1cbiAgICAgICAgICB9LFxuICAgICAgICAgIGV4YW1wbGU6IHtcbiAgICAgICAgICAgIG1lc3NhZ2VJZDogJzxtZXNzYWdlSWQ+J1xuICAgICAgICAgIH1cbiAgICAgICAgfVxuICAgICAgfVxuICAgICB9XG4gICAqL1xuICBjb25zdCBjbGllbnQgPSByZXEuY2xpZW50O1xuICBjb25zdCB7IG1lc3NhZ2VJZCB9ID0gcmVxLmJvZHk7XG5cbiAgaWYgKCFjbGllbnQgfHwgdHlwZW9mIGNsaWVudC5nZXRNZXNzYWdlQnlJZCAhPT0gJ2Z1bmN0aW9uJykge1xuICAgIHJldHVybiByZXMuc3RhdHVzKDQwMCkuanNvbih7XG4gICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICBtZXNzYWdlOiAnVGhlIFdoYXRzQXBwIHNlc3Npb24gaXMgbm90IGFjdGl2ZS4nLFxuICAgIH0pO1xuICB9XG5cbiAgbGV0IG1lc3NhZ2U7XG5cbiAgdHJ5IHtcbiAgICBpZiAoIW1lc3NhZ2VJZC5pc01lZGlhIHx8ICFtZXNzYWdlSWQudHlwZSkge1xuICAgICAgbWVzc2FnZSA9IGF3YWl0IGNsaWVudC5nZXRNZXNzYWdlQnlJZChtZXNzYWdlSWQpO1xuICAgIH0gZWxzZSB7XG4gICAgICBtZXNzYWdlID0gbWVzc2FnZUlkO1xuICAgIH1cblxuICAgIGlmICghbWVzc2FnZSlcbiAgICAgIHJlcy5zdGF0dXMoNDAwKS5qc29uKHtcbiAgICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgICBtZXNzYWdlOiAnTWVzc2FnZSBub3QgZm91bmQnLFxuICAgICAgfSk7XG5cbiAgICBpZiAoIShtZXNzYWdlWydtaW1ldHlwZSddIHx8IG1lc3NhZ2UuaXNNZWRpYSB8fCBtZXNzYWdlLmlzTU1TKSlcbiAgICAgIHJlcy5zdGF0dXMoNDAwKS5qc29uKHtcbiAgICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgICBtZXNzYWdlOiAnTWVzc2FnZSBkb2VzIG5vdCBjb250YWluIG1lZGlhJyxcbiAgICAgIH0pO1xuXG4gICAgY29uc3QgYnVmZmVyID0gYXdhaXQgY2xpZW50LmRlY3J5cHRGaWxlKG1lc3NhZ2UpO1xuXG4gICAgcmVzXG4gICAgICAuc3RhdHVzKDIwMClcbiAgICAgIC5qc29uKHsgYmFzZTY0OiBidWZmZXIudG9TdHJpbmcoJ2Jhc2U2NCcpLCBtaW1ldHlwZTogbWVzc2FnZS5taW1ldHlwZSB9KTtcbiAgfSBjYXRjaCAoZSkge1xuICAgIHJlcS5sb2dnZXIuZXJyb3IoZSk7XG4gICAgcmVzLnN0YXR1cyg0MDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgbWVzc2FnZTogJ0RlY3J5cHQgZmlsZSBlcnJvcicsXG4gICAgICBlcnJvcjogZSxcbiAgICB9KTtcbiAgfVxufVxuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24gZ2V0TWVkaWFCeU1lc3NhZ2UocmVxOiBSZXF1ZXN0LCByZXM6IFJlc3BvbnNlKSB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiTWVzc2FnZXNcIl1cbiAgICAgI3N3YWdnZXIuYXV0b0JvZHk9ZmFsc2VcbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAnZ2V0TWVkaWFCeU1lc3NhZ2UnXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAgICNzd2FnZ2VyLnBhcmFtZXRlcnNbXCJzZXNzaW9uXCJdID0ge1xuICAgICAgc2NoZW1hOiAnbWVzc2FnZUlkJ1xuICAgICB9XG4gICAqL1xuICBjb25zdCBjbGllbnQgPSByZXEuY2xpZW50O1xuICBjb25zdCB7IG1lc3NhZ2VJZCB9ID0gcmVxLnBhcmFtcztcblxuICBpZiAoIWNsaWVudCB8fCB0eXBlb2YgY2xpZW50LmdldE1lc3NhZ2VCeUlkICE9PSAnZnVuY3Rpb24nKSB7XG4gICAgcmV0dXJuIHJlcy5zdGF0dXMoNDAwKS5qc29uKHtcbiAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgIG1lc3NhZ2U6ICdUaGUgV2hhdHNBcHAgc2Vzc2lvbiBpcyBub3QgYWN0aXZlLicsXG4gICAgfSk7XG4gIH1cblxuICB0cnkge1xuICAgIGxldCBtZXNzYWdlOiBhbnkgPSBudWxsO1xuXG4gICAgLy8gSWYgZGV0YWlscyBhcmUgcHJvdmlkZWQgaW4gdGhlIHJlcXVlc3QgYm9keSAoZS5nLiBQT1NUIHJlcXVlc3Qgd2l0aCBsb2NhbCBjYWNoZSksIHVzZSB0aGVtIGRpcmVjdGx5LlxuICAgIGlmIChyZXEuYm9keSAmJiAocmVxLmJvZHkubWVkaWFLZXkgfHwgcmVxLmJvZHkuY2xpZW50VXJsKSkge1xuICAgICAgcmVxLmxvZ2dlci5pbmZvKGBSZWNlaXZlZCBkZWNyeXB0aW9uIGtleXMgaW4gYm9keSBmb3IgbWVzc2FnZSAke21lc3NhZ2VJZH0uIEJ5cGFzc2luZyBQdXBwZXRlZXIgbG9va3VwLmApO1xuICAgICAgbWVzc2FnZSA9IHJlcS5ib2R5O1xuICAgICAgLy8gTm9ybWFsaXNlIGtleSB0eXBlcyBhbmQgc3RydWN0dXJlcyBpZiBuZWVkZWQgYnkgZGVjcnlwdEZpbGVcbiAgICAgIGlmICh0eXBlb2YgbWVzc2FnZS5tZWRpYUtleSA9PT0gJ29iamVjdCcgJiYgbWVzc2FnZS5tZWRpYUtleS5kYXRhKSB7XG4gICAgICAgIG1lc3NhZ2UubWVkaWFLZXkgPSBCdWZmZXIuZnJvbShtZXNzYWdlLm1lZGlhS2V5LmRhdGEpO1xuICAgICAgfSBlbHNlIGlmICh0eXBlb2YgbWVzc2FnZS5tZWRpYUtleSA9PT0gJ3N0cmluZycpIHtcbiAgICAgICAgbWVzc2FnZS5tZWRpYUtleSA9IEJ1ZmZlci5mcm9tKG1lc3NhZ2UubWVkaWFLZXksICdiYXNlNjQnKTtcbiAgICAgIH1cbiAgICB9IGVsc2Uge1xuICAgICAgdHJ5IHtcbiAgICAgICAgbWVzc2FnZSA9IGF3YWl0IGNsaWVudC5nZXRNZXNzYWdlQnlJZChtZXNzYWdlSWQpO1xuICAgICAgfSBjYXRjaCAoZXJyOiBhbnkpIHtcbiAgICAgICAgcmVxLmxvZ2dlci53YXJuKGBjbGllbnQuZ2V0TWVzc2FnZUJ5SWQgdGhyZXcgZXJyb3I6ICR7ZXJyLm1lc3NhZ2UgfHwgZXJyfS4gVHJ5aW5nIGZhbGxiYWNrLi4uYCk7XG4gICAgICB9XG5cbiAgICAgIC8vIEZhbGxiYWNrOiBJZiBtZXNzYWdlIGlzIG5vdCBmb3VuZCwgaXQgbWlnaHQgbm90IGJlIGxvYWRlZCBpbiB0aGUgV2hhdHNBcHAgV2ViIGNhY2hlLlxuICAgICAgLy8gVHJ5IHRvIHBhcnNlIHRoZSBjaGF0SWQgZnJvbSB0aGUgc2VyaWFsaXplZCBtZXNzYWdlSWQgKGZvcm1hdDogZnJvbU1lX2NoYXRJZF9tc2dJZF9wYXJ0aWNpcGFudClcbiAgICAgIC8vIGFuZCBsb2FkIGVhcmxpZXIgbWVzc2FnZXMgdG8gZm9yY2Ugc3luYyBpdC5cbiAgICAgIGlmICghbWVzc2FnZSAmJiBtZXNzYWdlSWQpIHtcbiAgICAgICAgY29uc3QgcGFydHMgPSBtZXNzYWdlSWQuc3BsaXQoJ18nKTtcbiAgICAgICAgaWYgKHBhcnRzLmxlbmd0aCA+PSAyKSB7XG4gICAgICAgICAgY29uc3QgY2hhdElkID0gcGFydHNbMV07IC8vIGUuZy4gMTIwMzYzNDIwOTQ4MTM0MDY1QGcudXMgb3IgcGhvbmVAYy51c1xuICAgICAgICAgIGlmIChjaGF0SWQpIHtcbiAgICAgICAgICAgIHJlcS5sb2dnZXIuaW5mbyhgTWVzc2FnZSAke21lc3NhZ2VJZH0gbm90IGZvdW5kIGluIGNhY2hlLiBBdHRlbXB0aW5nIFdQUC5jaGF0LmZpbmQgJiBsb2FkRWFybGllck1lc3NhZ2VzIGZvciAke2NoYXRJZH1gKTtcbiAgICAgICAgICAgIHRyeSB7XG4gICAgICAgICAgICAgIGlmIChjbGllbnQucGFnZSAmJiAhY2xpZW50LnBhZ2UuaXNDbG9zZWQoKSkge1xuICAgICAgICAgICAgICAgIG1lc3NhZ2UgPSBhd2FpdCBjbGllbnQucGFnZS5ldmFsdWF0ZShhc3luYyAoeyBtc2dJZCwgdGFyZ2V0Q2hhdElkIH0pID0+IHtcbiAgICAgICAgICAgICAgICAgIHRyeSB7XG4gICAgICAgICAgICAgICAgICAgIGNvbnN0IFdQUCA9ICh3aW5kb3cgYXMgYW55KS5XUFA7XG4gICAgICAgICAgICAgICAgICAgIGNvbnN0IFN0b3JlID0gKHdpbmRvdyBhcyBhbnkpLlN0b3JlO1xuXG4gICAgICAgICAgICAgICAgICAgIC8vIEhlbHBlciAxOiBDb252ZXJ0IHN0cmluZyBKSUQgdG8gV2lkIGlmIHBvc3NpYmxlXG4gICAgICAgICAgICAgICAgICAgIGxldCB0YXJnZXRXaWQgPSB0YXJnZXRDaGF0SWQ7XG4gICAgICAgICAgICAgICAgICAgIGlmIChXUFA/LndoYXRzYXBwPy5XaWRGYWN0b3J5Py5jcmVhdGUpIHtcbiAgICAgICAgICAgICAgICAgICAgICB0cnkge1xuICAgICAgICAgICAgICAgICAgICAgICAgdGFyZ2V0V2lkID0gV1BQLndoYXRzYXBwLldpZEZhY3RvcnkuY3JlYXRlKHRhcmdldENoYXRJZCk7XG4gICAgICAgICAgICAgICAgICAgICAgfSBjYXRjaCAoZSkge31cbiAgICAgICAgICAgICAgICAgICAgfVxuXG4gICAgICAgICAgICAgICAgICAgIC8vIEhlbHBlciAyOiBFbnN1cmUgY2hhdCBpcyBsb2FkZWRcbiAgICAgICAgICAgICAgICAgICAgaWYgKFdQUD8uY2hhdD8uZmluZCkge1xuICAgICAgICAgICAgICAgICAgICAgIHRyeSB7IGF3YWl0IFdQUC5jaGF0LmZpbmQodGFyZ2V0Q2hhdElkKTsgfSBjYXRjaCAoZSkge31cbiAgICAgICAgICAgICAgICAgICAgICB0cnkgeyBpZiAodGFyZ2V0V2lkICE9PSB0YXJnZXRDaGF0SWQpIGF3YWl0IFdQUC5jaGF0LmZpbmQodGFyZ2V0V2lkKTsgfSBjYXRjaCAoZSkge31cbiAgICAgICAgICAgICAgICAgICAgICB0cnkge1xuICAgICAgICAgICAgICAgICAgICAgICAgaWYgKHRhcmdldENoYXRJZC5pbmNsdWRlcygnQGMudXMnKSkge1xuICAgICAgICAgICAgICAgICAgICAgICAgICBhd2FpdCBXUFAuY2hhdC5maW5kKHRhcmdldENoYXRJZC5yZXBsYWNlKC9AY1xcLnVzL2csICdAcy53aGF0c2FwcC5uZXQnKSk7XG4gICAgICAgICAgICAgICAgICAgICAgICB9XG4gICAgICAgICAgICAgICAgICAgICAgfSBjYXRjaCAoZSkge31cbiAgICAgICAgICAgICAgICAgICAgfVxuXG4gICAgICAgICAgICAgICAgICAgIGlmIChXUFA/LmNoYXQ/LmxvYWRFYXJsaWVyTWVzc2FnZXMpIHtcbiAgICAgICAgICAgICAgICAgICAgICB0cnkgeyBhd2FpdCBXUFAuY2hhdC5sb2FkRWFybGllck1lc3NhZ2VzKHRhcmdldENoYXRJZCk7IH0gY2F0Y2ggKGUpIHt9XG4gICAgICAgICAgICAgICAgICAgIH1cblxuICAgICAgICAgICAgICAgICAgICAvLyBIZWxwZXIgMzogRGVlcCBzZWFyY2ggbWVzc2FnZVxuICAgICAgICAgICAgICAgICAgICBjb25zdCBnZXRNc2dTYWZlID0gYXN5bmMgKG1JZDogc3RyaW5nKSA9PiB7XG4gICAgICAgICAgICAgICAgICAgICAgaWYgKCFtSWQpIHJldHVybiBudWxsO1xuICAgICAgICAgICAgICAgICAgICAgIGlmIChXUFA/LmNoYXQ/LmdldE1lc3NhZ2VCeUlkKSB7XG4gICAgICAgICAgICAgICAgICAgICAgICB0cnkge1xuICAgICAgICAgICAgICAgICAgICAgICAgICBjb25zdCBtID0gYXdhaXQgV1BQLmNoYXQuZ2V0TWVzc2FnZUJ5SWQobUlkKTtcbiAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgKG0pIHJldHVybiBtO1xuICAgICAgICAgICAgICAgICAgICAgICAgfSBjYXRjaCAoZSkge31cbiAgICAgICAgICAgICAgICAgICAgICAgIHRyeSB7XG4gICAgICAgICAgICAgICAgICAgICAgICAgIGlmIChtSWQuaW5jbHVkZXMoJ0BjLnVzJykpIHtcbiAgICAgICAgICAgICAgICAgICAgICAgICAgICBjb25zdCBtID0gYXdhaXQgV1BQLmNoYXQuZ2V0TWVzc2FnZUJ5SWQobUlkLnJlcGxhY2UoL0BjXFwudXMvZywgJ0BzLndoYXRzYXBwLm5ldCcpKTtcbiAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiAobSkgcmV0dXJuIG07XG4gICAgICAgICAgICAgICAgICAgICAgICAgIH0gZWxzZSBpZiAobUlkLmluY2x1ZGVzKCdAcy53aGF0c2FwcC5uZXQnKSkge1xuICAgICAgICAgICAgICAgICAgICAgICAgICAgIGNvbnN0IG0gPSBhd2FpdCBXUFAuY2hhdC5nZXRNZXNzYWdlQnlJZChtSWQucmVwbGFjZSgvQHNcXC53aGF0c2FwcFxcLm5ldC9nLCAnQGMudXMnKSk7XG4gICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgKG0pIHJldHVybiBtO1xuICAgICAgICAgICAgICAgICAgICAgICAgICB9XG4gICAgICAgICAgICAgICAgICAgICAgICB9IGNhdGNoIChlKSB7fVxuICAgICAgICAgICAgICAgICAgICAgIH1cblxuICAgICAgICAgICAgICAgICAgICAgIC8vIEZhbGxiYWNrOiBzZWFyY2ggU3RvcmUuTXNnLm1vZGVscyBieSByYXcgbWVzc2FnZSBJRFxuICAgICAgICAgICAgICAgICAgICAgIGNvbnN0IHBhcnRzID0gbUlkLnNwbGl0KCdfJyk7XG4gICAgICAgICAgICAgICAgICAgICAgY29uc3QgcmF3SWQgPSBwYXJ0cy5sZW5ndGggPiAyID8gcGFydHNbMl0gOiBtSWQ7XG4gICAgICAgICAgICAgICAgICAgICAgaWYgKFN0b3JlPy5Nc2c/Lm1vZGVscykge1xuICAgICAgICAgICAgICAgICAgICAgICAgY29uc3QgZm91bmQgPSBTdG9yZS5Nc2cubW9kZWxzLmZpbmQoKGl0ZW06IGFueSkgPT4ge1xuICAgICAgICAgICAgICAgICAgICAgICAgICBpZiAoIWl0ZW0gfHwgIWl0ZW0uaWQpIHJldHVybiBmYWxzZTtcbiAgICAgICAgICAgICAgICAgICAgICAgICAgY29uc3Qgc2VyID0gaXRlbS5pZC5fc2VyaWFsaXplZCB8fCAnJztcbiAgICAgICAgICAgICAgICAgICAgICAgICAgY29uc3QgaXRlbUlkID0gaXRlbS5pZC5pZCB8fCAnJztcbiAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJuIGl0ZW1JZCA9PT0gcmF3SWQgfHwgc2VyID09PSBtSWQgfHwgKHJhd0lkICYmIHNlci5pbmNsdWRlcyhyYXdJZCkpO1xuICAgICAgICAgICAgICAgICAgICAgICAgfSk7XG4gICAgICAgICAgICAgICAgICAgICAgICBpZiAoZm91bmQpIHJldHVybiBmb3VuZDtcbiAgICAgICAgICAgICAgICAgICAgICB9XG4gICAgICAgICAgICAgICAgICAgICAgcmV0dXJuIG51bGw7XG4gICAgICAgICAgICAgICAgICAgIH07XG5cbiAgICAgICAgICAgICAgICAgICAgcmV0dXJuIGF3YWl0IGdldE1zZ1NhZmUobXNnSWQpO1xuICAgICAgICAgICAgICAgICAgfSBjYXRjaCAoZSkge1xuICAgICAgICAgICAgICAgICAgICBjb25zb2xlLmxvZyhgW2Jyb3dzZXItZXZhbHVhdGUgZ2V0TWVkaWFCeU1lc3NhZ2UgZmFsbGJhY2sgZXJyb3JdOiAke2V9YCk7XG4gICAgICAgICAgICAgICAgICAgIHJldHVybiBudWxsO1xuICAgICAgICAgICAgICAgICAgfVxuICAgICAgICAgICAgICAgIH0sIHsgbXNnSWQ6IG1lc3NhZ2VJZCwgdGFyZ2V0Q2hhdElkOiBjaGF0SWQgfSk7XG4gICAgICAgICAgICAgIH1cblxuICAgICAgICAgICAgICAvLyBTZWNvbmQgY2hlY2sgaWYgZXZhbHVhdGUgcmV0dXJuZWQgbnVsbCBidXQgY2xpZW50LmdldE1lc3NhZ2VCeUlkIG1pZ2h0IHdvcmsgbm93XG4gICAgICAgICAgICAgIGlmICghbWVzc2FnZSAmJiB0eXBlb2YgY2xpZW50LmdldE1lc3NhZ2VCeUlkID09PSAnZnVuY3Rpb24nKSB7XG4gICAgICAgICAgICAgICAgdHJ5IHtcbiAgICAgICAgICAgICAgICAgIG1lc3NhZ2UgPSBhd2FpdCBjbGllbnQuZ2V0TWVzc2FnZUJ5SWQobWVzc2FnZUlkKTtcbiAgICAgICAgICAgICAgICB9IGNhdGNoIChyZXRyeUVycjogYW55KSB7XG4gICAgICAgICAgICAgICAgICByZXEubG9nZ2VyLmVycm9yKGBSZXRyeSBnZXRNZXNzYWdlQnlJZCBmYWlsZWQ6ICR7cmV0cnlFcnIubWVzc2FnZSB8fCByZXRyeUVycn1gKTtcbiAgICAgICAgICAgICAgICB9XG4gICAgICAgICAgICAgIH1cbiAgICAgICAgICAgIH0gY2F0Y2ggKGxvYWRFcnIpIHtcbiAgICAgICAgICAgICAgcmVxLmxvZ2dlci5lcnJvcihgRXJyb3IgZXhlY3V0aW5nIGdldE1lZGlhQnlNZXNzYWdlIGZhbGxiYWNrOiAke2xvYWRFcnJ9YCk7XG4gICAgICAgICAgICB9XG4gICAgICAgICAgfVxuICAgICAgICB9XG4gICAgICB9XG4gICAgfVxuXG4gICAgaWYgKCFtZXNzYWdlKSB7XG4gICAgICByZXR1cm4gcmVzLnN0YXR1cyg0MDApLmpzb24oe1xuICAgICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICAgIG1lc3NhZ2U6IGBNZXNzYWdlICR7bWVzc2FnZUlkfSBub3QgZm91bmRgLFxuICAgICAgfSk7XG4gICAgfVxuXG4gICAgLy8gRW5zdXJlIGNsaWVudCBicm93c2VyIGNvbnRleHQgaXMgYWxpdmVcbiAgICBpZiAoY2xpZW50LnBhZ2UgJiYgY2xpZW50LnBhZ2UuaXNDbG9zZWQoKSkge1xuICAgICAgcmVxLmxvZ2dlci53YXJuKGBCcm93c2VyIHBhZ2UgaXMgY2xvc2VkIGZvciBzZXNzaW9uIHdoZW4gZG93bmxvYWRpbmcgbWVkaWEgJHttZXNzYWdlSWR9YCk7XG4gICAgICByZXR1cm4gcmVzLnN0YXR1cyg1MDMpLmpzb24oe1xuICAgICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICAgIG1lc3NhZ2U6ICdCcm93c2VyIHNlc3Npb24gaXMgY2xvc2VkIG9yIHJlLWNvbm5lY3RpbmcnLFxuICAgICAgfSk7XG4gICAgfVxuXG4gICAgLy8gRW5zdXJlIGl0IGNvbnRhaW5zIG1lZGlhIHByb3BlcnRpZXMgb3IgaGFzIG1pbWV0eXBlXG4gICAgY29uc3QgbWVkaWFVcmwgPSBtZXNzYWdlLmNsaWVudFVybCB8fCBtZXNzYWdlLmRlcHJlY2F0ZWRNbXMzVXJsO1xuICAgIGlmICghbWVkaWFVcmwpIHtcbiAgICAgIGlmICh0eXBlb2YgKGNsaWVudCBhcyBhbnkpLmRvd25sb2FkTWVkaWEgPT09ICdmdW5jdGlvbicgJiYgY2xpZW50LnBhZ2UgJiYgIWNsaWVudC5wYWdlLmlzQ2xvc2VkKCkpIHtcbiAgICAgICAgcmVxLmxvZ2dlci5pbmZvKGBNZXNzYWdlICR7bWVzc2FnZUlkfSBkb2VzIG5vdCBoYXZlIGNsaWVudFVybC4gVHJ5aW5nIGNsaWVudC5kb3dubG9hZE1lZGlhIHdpdGggNXMgdGltZW91dC4uLmApO1xuICAgICAgICB0cnkge1xuICAgICAgICAgIGxldCB0aW1lcjogYW55O1xuICAgICAgICAgIGNvbnN0IGRvd25sb2FkUHJvbWlzZSA9IChjbGllbnQgYXMgYW55KS5kb3dubG9hZE1lZGlhKG1lc3NhZ2VJZCkuY2F0Y2goKGVycjogYW55KSA9PiB7XG4gICAgICAgICAgICByZXEubG9nZ2VyLndhcm4oYGNsaWVudC5kb3dubG9hZE1lZGlhIGNhdWdodCBpbm5lciBlcnJvcjogJHtlcnJ9YCk7XG4gICAgICAgICAgICByZXR1cm4gbnVsbDtcbiAgICAgICAgICB9KS5maW5hbGx5KCgpID0+IHtcbiAgICAgICAgICAgIGlmICh0aW1lcikgY2xlYXJUaW1lb3V0KHRpbWVyKTtcbiAgICAgICAgICB9KTtcbiAgICAgICAgICBjb25zdCB0aW1lb3V0UHJvbWlzZSA9IG5ldyBQcm9taXNlPG51bGw+KChyZXNvbHZlKSA9PiB7XG4gICAgICAgICAgICB0aW1lciA9IHNldFRpbWVvdXQoKCkgPT4ge1xuICAgICAgICAgICAgICByZXEubG9nZ2VyLndhcm4oYFRpbWVvdXQgNTAwMG1zIHJlYWNoZWQgZm9yIGNsaWVudC5kb3dubG9hZE1lZGlhICgke21lc3NhZ2VJZH0pYCk7XG4gICAgICAgICAgICAgIHJlc29sdmUobnVsbCk7XG4gICAgICAgICAgICB9LCA1MDAwKTtcbiAgICAgICAgICB9KTtcbiAgICAgICAgICBsZXQgYmFzZTY0OiBzdHJpbmcgfCBudWxsID0gYXdhaXQgUHJvbWlzZS5yYWNlKFtkb3dubG9hZFByb21pc2UsIHRpbWVvdXRQcm9taXNlXSk7XG4gICAgICAgICAgaWYgKGJhc2U2NCkge1xuICAgICAgICAgICAgbGV0IG1pbWV0eXBlID0gbWVzc2FnZS5taW1ldHlwZSB8fCAnYXVkaW8vb2dnJztcbiAgICAgICAgICAgIGlmIChiYXNlNjQuc3RhcnRzV2l0aCgnZGF0YTonKSkge1xuICAgICAgICAgICAgICBjb25zdCBtYXRjaGVzID0gYmFzZTY0Lm1hdGNoKC9eZGF0YTooLio/KTtiYXNlNjQsKC4qKSQvKTtcbiAgICAgICAgICAgICAgaWYgKG1hdGNoZXMpIHtcbiAgICAgICAgICAgICAgICBtaW1ldHlwZSA9IG1hdGNoZXNbMV07XG4gICAgICAgICAgICAgICAgYmFzZTY0ID0gbWF0Y2hlc1syXTtcbiAgICAgICAgICAgICAgfVxuICAgICAgICAgICAgfVxuICAgICAgICAgICAgcmV0dXJuIHJlcy5zdGF0dXMoMjAwKS5qc29uKHsgYmFzZTY0LCBtaW1ldHlwZSB9KTtcbiAgICAgICAgICB9XG4gICAgICAgIH0gY2F0Y2ggKGRvd25sb2FkRXJyKSB7XG4gICAgICAgICAgcmVxLmxvZ2dlci5lcnJvcihgRXJyb3IgaW4gY2xpZW50LmRvd25sb2FkTWVkaWEgZmFsbGJhY2s6ICR7ZG93bmxvYWRFcnJ9YCk7XG4gICAgICAgIH1cbiAgICAgIH1cbiAgICAgIHJldHVybiByZXMuc3RhdHVzKDQwMCkuanNvbih7XG4gICAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgICAgbWVzc2FnZTogJ01lc3NhZ2UgZG9lcyBub3QgY29udGFpbiBtZWRpYSBkb3dubG9hZCBVUkwnLFxuICAgICAgfSk7XG4gICAgfVxuXG4gICAgdHJ5IHtcbiAgICAgIGNvbnN0IGJ1ZmZlciA9IGF3YWl0IGNsaWVudC5kZWNyeXB0RmlsZShtZXNzYWdlKTtcbiAgICAgIHJlc1xuICAgICAgICAuc3RhdHVzKDIwMClcbiAgICAgICAgLmpzb24oeyBiYXNlNjQ6IGJ1ZmZlci50b1N0cmluZygnYmFzZTY0JyksIG1pbWV0eXBlOiBtZXNzYWdlLm1pbWV0eXBlIHx8ICdhdWRpby9vZ2cnIH0pO1xuICAgIH0gY2F0Y2ggKGRlY3J5cHRFcnIpIHtcbiAgICAgIHJlcS5sb2dnZXIuZXJyb3IoYGRlY3J5cHRGaWxlIGZhaWxlZCwgdHJ5aW5nIGJyb3dzZXItc2lkZSByZWNvdmVyeTogJHtkZWNyeXB0RXJyfWApO1xuICAgICAgXG4gICAgICAvLyBBdHRlbXB0IGJyb3dzZXItc2lkZSByZWNvdmVyeTogZmV0Y2ggdGhlIG1lc3NhZ2UgZnJlc2ggZnJvbSBXaGF0c0FwcCBXZWIgdG8gZ2V0IHVwZGF0ZWQgQ0ROIFVSTHNcbiAgICAgIGxldCBmcmVzaE1lc3NhZ2U6IGFueSA9IG51bGw7XG4gICAgICBpZiAoY2xpZW50LnBhZ2UgJiYgIWNsaWVudC5wYWdlLmlzQ2xvc2VkKCkpIHtcbiAgICAgICAgdHJ5IHtcbiAgICAgICAgICBmcmVzaE1lc3NhZ2UgPSBhd2FpdCBjbGllbnQuZ2V0TWVzc2FnZUJ5SWQobWVzc2FnZUlkKTtcbiAgICAgICAgfSBjYXRjaCAoZXJyKSB7fVxuXG4gICAgICAgIGlmICghZnJlc2hNZXNzYWdlICYmIG1lc3NhZ2VJZCkge1xuICAgICAgICAgIGNvbnN0IHBhcnRzID0gbWVzc2FnZUlkLnNwbGl0KCdfJyk7XG4gICAgICAgICAgaWYgKHBhcnRzLmxlbmd0aCA+PSAyKSB7XG4gICAgICAgICAgICBjb25zdCBjaGF0SWQgPSBwYXJ0c1sxXTtcbiAgICAgICAgICAgIGlmIChjaGF0SWQgJiYgdHlwZW9mIGNsaWVudC5sb2FkRWFybGllck1lc3NhZ2VzID09PSAnZnVuY3Rpb24nKSB7XG4gICAgICAgICAgICAgIHRyeSB7XG4gICAgICAgICAgICAgICAgYXdhaXQgY2xpZW50LmxvYWRFYXJsaWVyTWVzc2FnZXMoY2hhdElkKTtcbiAgICAgICAgICAgICAgICBmcmVzaE1lc3NhZ2UgPSBhd2FpdCBjbGllbnQuZ2V0TWVzc2FnZUJ5SWQobWVzc2FnZUlkKTtcbiAgICAgICAgICAgICAgfSBjYXRjaCAoZXJyKSB7fVxuICAgICAgICAgICAgfVxuICAgICAgICAgIH1cbiAgICAgICAgfVxuICAgICAgfVxuXG4gICAgICBpZiAoZnJlc2hNZXNzYWdlKSB7XG4gICAgICAgIHRyeSB7XG4gICAgICAgICAgcmVxLmxvZ2dlci5pbmZvKGBGb3VuZCBmcmVzaCBtZXNzYWdlIGluIGJyb3dzZXIgZm9yICR7bWVzc2FnZUlkfSwgYXR0ZW1wdGluZyBkZWNyeXB0aW9uLi4uYCk7XG4gICAgICAgICAgY29uc3QgYnVmZmVyID0gYXdhaXQgY2xpZW50LmRlY3J5cHRGaWxlKGZyZXNoTWVzc2FnZSk7XG4gICAgICAgICAgcmV0dXJuIHJlcy5zdGF0dXMoMjAwKS5qc29uKHtcbiAgICAgICAgICAgIGJhc2U2NDogYnVmZmVyLnRvU3RyaW5nKCdiYXNlNjQnKSxcbiAgICAgICAgICAgIG1pbWV0eXBlOiBmcmVzaE1lc3NhZ2UubWltZXR5cGUgfHwgJ2F1ZGlvL29nZydcbiAgICAgICAgICB9KTtcbiAgICAgICAgfSBjYXRjaCAoZnJlc2hEZWNyeXB0RXJyKSB7XG4gICAgICAgICAgcmVxLmxvZ2dlci5lcnJvcihgRGVjcnlwdGlvbiBvZiBmcmVzaCBicm93c2VyIG1lc3NhZ2UgZmFpbGVkOiAke2ZyZXNoRGVjcnlwdEVycn1gKTtcbiAgICAgICAgfVxuICAgICAgfVxuXG4gICAgICAvLyBGaW5hbCBmYWxsYmFjayB0byBXUFBDb25uZWN0J3MgZG93bmxvYWRNZWRpYVxuICAgICAgaWYgKHR5cGVvZiAoY2xpZW50IGFzIGFueSkuZG93bmxvYWRNZWRpYSA9PT0gJ2Z1bmN0aW9uJyAmJiBjbGllbnQucGFnZSAmJiAhY2xpZW50LnBhZ2UuaXNDbG9zZWQoKSkge1xuICAgICAgICB0cnkge1xuICAgICAgICAgIGxldCB0aW1lcjogYW55O1xuICAgICAgICAgIGNvbnN0IGRvd25sb2FkUHJvbWlzZSA9IChjbGllbnQgYXMgYW55KS5kb3dubG9hZE1lZGlhKG1lc3NhZ2VJZCkuY2F0Y2goKGVycjogYW55KSA9PiB7XG4gICAgICAgICAgICByZXEubG9nZ2VyLndhcm4oYGNsaWVudC5kb3dubG9hZE1lZGlhIGNhdWdodCBpbm5lciBlcnJvcjogJHtlcnJ9YCk7XG4gICAgICAgICAgICByZXR1cm4gbnVsbDtcbiAgICAgICAgICB9KS5maW5hbGx5KCgpID0+IHtcbiAgICAgICAgICAgIGlmICh0aW1lcikgY2xlYXJUaW1lb3V0KHRpbWVyKTtcbiAgICAgICAgICB9KTtcbiAgICAgICAgICBjb25zdCB0aW1lb3V0UHJvbWlzZSA9IG5ldyBQcm9taXNlPG51bGw+KChyZXNvbHZlKSA9PiB7XG4gICAgICAgICAgICB0aW1lciA9IHNldFRpbWVvdXQoKCkgPT4ge1xuICAgICAgICAgICAgICByZXEubG9nZ2VyLndhcm4oYFRpbWVvdXQgNTAwMG1zIHJlYWNoZWQgZm9yIGNsaWVudC5kb3dubG9hZE1lZGlhICgke21lc3NhZ2VJZH0pYCk7XG4gICAgICAgICAgICAgIHJlc29sdmUobnVsbCk7XG4gICAgICAgICAgICB9LCA1MDAwKTtcbiAgICAgICAgICB9KTtcbiAgICAgICAgICBsZXQgYmFzZTY0OiBzdHJpbmcgfCBudWxsID0gYXdhaXQgUHJvbWlzZS5yYWNlKFtkb3dubG9hZFByb21pc2UsIHRpbWVvdXRQcm9taXNlXSk7XG4gICAgICAgICAgaWYgKGJhc2U2NCkge1xuICAgICAgICAgICAgbGV0IG1pbWV0eXBlID0gKGZyZXNoTWVzc2FnZSB8fCBtZXNzYWdlKS5taW1ldHlwZSB8fCAnYXVkaW8vb2dnJztcbiAgICAgICAgICAgIGlmIChiYXNlNjQuc3RhcnRzV2l0aCgnZGF0YTonKSkge1xuICAgICAgICAgICAgICBjb25zdCBtYXRjaGVzID0gYmFzZTY0Lm1hdGNoKC9eZGF0YTooLio/KTtiYXNlNjQsKC4qKSQvKTtcbiAgICAgICAgICAgICAgaWYgKG1hdGNoZXMpIHtcbiAgICAgICAgICAgICAgICBtaW1ldHlwZSA9IG1hdGNoZXNbMV07XG4gICAgICAgICAgICAgICAgYmFzZTY0ID0gbWF0Y2hlc1syXTtcbiAgICAgICAgICAgICAgfVxuICAgICAgICAgICAgfVxuICAgICAgICAgICAgcmV0dXJuIHJlcy5zdGF0dXMoMjAwKS5qc29uKHsgYmFzZTY0LCBtaW1ldHlwZSB9KTtcbiAgICAgICAgICB9XG4gICAgICAgIH0gY2F0Y2ggKGRvd25sb2FkRXJyKSB7XG4gICAgICAgICAgcmVxLmxvZ2dlci5lcnJvcihgRXJyb3IgaW4gY2xpZW50LmRvd25sb2FkTWVkaWEgZmFsbGJhY2sgYWZ0ZXIgZGVjcnlwdGlvbiBlcnJvcjogJHtkb3dubG9hZEVycn1gKTtcbiAgICAgICAgfVxuICAgICAgfVxuICAgICAgdGhyb3cgZGVjcnlwdEVycjsgLy8gcmV0aHJvdyB0byB0cmlnZ2VyIHRoZSA1MDAgYmxvY2sgaWYgYm90aCBmYWlsZWRcbiAgICB9XG4gIH0gY2F0Y2ggKGV4KSB7XG4gICAgcmVxLmxvZ2dlci5lcnJvcihleCk7XG4gICAgcmVzLnN0YXR1cyg1MDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgbWVzc2FnZTogJ0ZhaWxlZCB0byBkZWNyeXB0IGZpbGUnLFxuICAgICAgZXJyb3I6IGV4IGluc3RhbmNlb2YgRXJyb3IgPyBleC5tZXNzYWdlIDogZXgsXG4gICAgfSk7XG4gIH1cbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIGdldFNlc3Npb25TdGF0ZShyZXE6IFJlcXVlc3QsIHJlczogUmVzcG9uc2UpIHtcbiAgLyoqXG4gICAgICNzd2FnZ2VyLnRhZ3MgPSBbXCJBdXRoXCJdXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ2dldFNlc3Npb25TdGF0ZSdcbiAgICAgI3N3YWdnZXIuc3VtbWFyeSA9ICdSZXRyaWV2ZSBzdGF0dXMgb2YgYSBzZXNzaW9uJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keSA9IGZhbHNlXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAqL1xuICB0cnkge1xuICAgIGNvbnN0IHsgd2FpdFFyQ29kZSA9IGZhbHNlIH0gPSByZXEuYm9keTtcbiAgICBjb25zdCBjbGllbnQgPSByZXEuY2xpZW50O1xuICAgIGNvbnN0IHFyID1cbiAgICAgIGNsaWVudD8udXJsY29kZSAhPSBudWxsICYmIGNsaWVudD8udXJsY29kZSAhPSAnJ1xuICAgICAgICA/IGF3YWl0IFFSQ29kZS50b0RhdGFVUkwoY2xpZW50LnVybGNvZGUpXG4gICAgICAgIDogbnVsbDtcblxuICAgIGlmICgoY2xpZW50ID09IG51bGwgfHwgY2xpZW50LnN0YXR1cyA9PSBudWxsKSAmJiAhd2FpdFFyQ29kZSlcbiAgICAgIHJlcy5zdGF0dXMoMjAwKS5qc29uKHsgc3RhdHVzOiAnQ0xPU0VEJywgcXJjb2RlOiBudWxsIH0pO1xuICAgIGVsc2UgaWYgKGNsaWVudCAhPSBudWxsKVxuICAgICAgcmVzLnN0YXR1cygyMDApLmpzb24oe1xuICAgICAgICBzdGF0dXM6IGNsaWVudC5zdGF0dXMsXG4gICAgICAgIHFyY29kZTogcXIsXG4gICAgICAgIHVybGNvZGU6IGNsaWVudC51cmxjb2RlLFxuICAgICAgICB2ZXJzaW9uOiB2ZXJzaW9uLFxuICAgICAgfSk7XG4gIH0gY2F0Y2ggKGV4KSB7XG4gICAgcmVxLmxvZ2dlci5lcnJvcihleCk7XG4gICAgcmVzLnN0YXR1cyg1MDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgbWVzc2FnZTogJ1RoZSBzZXNzaW9uIGlzIG5vdCBhY3RpdmUnLFxuICAgICAgZXJyb3I6IGV4LFxuICAgIH0pO1xuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBnZXRRckNvZGUocmVxOiBSZXF1ZXN0LCByZXM6IFJlc3BvbnNlKSB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiQXV0aFwiXVxuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5vcGVyYXRpb25JZCA9ICdnZXRRckNvZGUnXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAqL1xuICB0cnkge1xuICAgIGlmIChyZXE/LmNsaWVudD8udXJsY29kZSkge1xuICAgICAgLy8gV2UgYWRkIG9wdGlvbnMgdG8gZ2VuZXJhdGUgdGhlIFFSIGNvZGUgaW4gaGlnaGVyIHJlc29sdXRpb25cbiAgICAgIC8vIFRoZSAvcXJjb2RlLXNlc3Npb24gcmVxdWVzdCB3aWxsIG5vdyByZXR1cm4gYSByZWFkYWJsZSBxcmNvZGUuXG4gICAgICBjb25zdCBxck9wdGlvbnMgPSB7XG4gICAgICAgIGVycm9yQ29ycmVjdGlvbkxldmVsOiAnTScgYXMgY29uc3QsXG4gICAgICAgIHR5cGU6ICdpbWFnZS9wbmcnIGFzIGNvbnN0LFxuICAgICAgICBzY2FsZTogNSxcbiAgICAgICAgd2lkdGg6IDUwMCxcbiAgICAgIH07XG4gICAgICBjb25zdCBxciA9IHJlcS5jbGllbnQudXJsY29kZVxuICAgICAgICA/IGF3YWl0IFFSQ29kZS50b0RhdGFVUkwocmVxLmNsaWVudC51cmxjb2RlLCBxck9wdGlvbnMpXG4gICAgICAgIDogbnVsbDtcbiAgICAgIGNvbnN0IGltZyA9IEJ1ZmZlci5mcm9tKFxuICAgICAgICAocXIgYXMgYW55KS5yZXBsYWNlKC9eZGF0YTppbWFnZVxcLyhwbmd8anBlZ3xqcGcpO2Jhc2U2NCwvLCAnJyksXG4gICAgICAgICdiYXNlNjQnXG4gICAgICApO1xuICAgICAgcmVzLndyaXRlSGVhZCgyMDAsIHtcbiAgICAgICAgJ0NvbnRlbnQtVHlwZSc6ICdpbWFnZS9wbmcnLFxuICAgICAgICAnQ29udGVudC1MZW5ndGgnOiBpbWcubGVuZ3RoLFxuICAgICAgfSk7XG4gICAgICByZXMuZW5kKGltZyk7XG4gICAgfSBlbHNlIGlmICh0eXBlb2YgcmVxLmNsaWVudCA9PT0gJ3VuZGVmaW5lZCcpIHtcbiAgICAgIHJlcy5zdGF0dXMoMjAwKS5qc29uKHtcbiAgICAgICAgc3RhdHVzOiBudWxsLFxuICAgICAgICBtZXNzYWdlOlxuICAgICAgICAgICdTZXNzaW9uIG5vdCBzdGFydGVkLiBQbGVhc2UsIHVzZSB0aGUgL3N0YXJ0LXNlc3Npb24gcm91dGUsIGZvciBpbml0aWFsaXphdGlvbiB5b3VyIHNlc3Npb24nLFxuICAgICAgfSk7XG4gICAgfSBlbHNlIHtcbiAgICAgIHJlcy5zdGF0dXMoMjAwKS5qc29uKHtcbiAgICAgICAgc3RhdHVzOiByZXEuY2xpZW50LnN0YXR1cyxcbiAgICAgICAgbWVzc2FnZTogJ1FSQ29kZSBpcyBub3QgYXZhaWxhYmxlLi4uJyxcbiAgICAgIH0pO1xuICAgIH1cbiAgfSBjYXRjaCAoZXgpIHtcbiAgICByZXEubG9nZ2VyLmVycm9yKGV4KTtcbiAgICByZXNcbiAgICAgIC5zdGF0dXMoNTAwKVxuICAgICAgLmpzb24oeyBzdGF0dXM6ICdlcnJvcicsIG1lc3NhZ2U6ICdFcnJvciByZXRyaWV2aW5nIFFSQ29kZScsIGVycm9yOiBleCB9KTtcbiAgfVxufVxuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24ga2lsbFNlcnZpY2VXb3JrZXIocmVxOiBSZXF1ZXN0LCByZXM6IFJlc3BvbnNlKSB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci5pZ25vcmU9dHJ1ZVxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiTWVzc2FnZXNcIl1cbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAna2lsbFNlcnZpY2VXb3JraWVyJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgKi9cbiAgdHJ5IHtcbiAgICByZXMuc3RhdHVzKDIwMCkuanNvbih7IHN0YXR1czogJ2Vycm9yJywgcmVzcG9uc2U6ICdOb3QgaW1wbGVtZW50ZWQgeWV0JyB9KTtcbiAgfSBjYXRjaCAoZXgpIHtcbiAgICByZXEubG9nZ2VyLmVycm9yKGV4KTtcbiAgICByZXMuc3RhdHVzKDUwMCkuanNvbih7XG4gICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICBtZXNzYWdlOiAnVGhlIHNlc3Npb24gaXMgbm90IGFjdGl2ZScsXG4gICAgICBlcnJvcjogZXgsXG4gICAgfSk7XG4gIH1cbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIHJlc3RhcnRTZXJ2aWNlKHJlcTogUmVxdWVzdCwgcmVzOiBSZXNwb25zZSkge1xuICAvKipcbiAgICogI3N3YWdnZXIuaWdub3JlPXRydWVcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIk1lc3NhZ2VzXCJdXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ3Jlc3RhcnRTZXJ2aWNlJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgKi9cbiAgdHJ5IHtcbiAgICByZXMuc3RhdHVzKDIwMCkuanNvbih7IHN0YXR1czogJ2Vycm9yJywgcmVzcG9uc2U6ICdOb3QgaW1wbGVtZW50ZWQgeWV0JyB9KTtcbiAgfSBjYXRjaCAoZXgpIHtcbiAgICByZXEubG9nZ2VyLmVycm9yKGV4KTtcbiAgICByZXMuc3RhdHVzKDUwMCkuanNvbih7XG4gICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICByZXNwb25zZTogeyBtZXNzYWdlOiAnVGhlIHNlc3Npb24gaXMgbm90IGFjdGl2ZScsIGVycm9yOiBleCB9LFxuICAgIH0pO1xuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBzdWJzY3JpYmVQcmVzZW5jZShyZXE6IFJlcXVlc3QsIHJlczogUmVzcG9uc2UpIHtcbiAgLyoqXG4gICAqICNzd2FnZ2VyLnRhZ3MgPSBbXCJNaXNjXCJdXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ3N1YnNjcmliZVByZXNlbmNlJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgICAjc3dhZ2dlci5yZXF1ZXN0Qm9keSA9IHtcbiAgICAgIHJlcXVpcmVkOiB0cnVlLFxuICAgICAgXCJAY29udGVudFwiOiB7XG4gICAgICAgIFwiYXBwbGljYXRpb24vanNvblwiOiB7XG4gICAgICAgICAgc2NoZW1hOiB7XG4gICAgICAgICAgICB0eXBlOiBcIm9iamVjdFwiLFxuICAgICAgICAgICAgcHJvcGVydGllczoge1xuICAgICAgICAgICAgICBwaG9uZTogeyB0eXBlOiBcInN0cmluZ1wiIH0sXG4gICAgICAgICAgICAgIGlzR3JvdXA6IHsgdHlwZTogXCJib29sZWFuXCIgfSxcbiAgICAgICAgICAgICAgYWxsOiB7IHR5cGU6IFwiYm9vbGVhblwiIH0sXG4gICAgICAgICAgICB9XG4gICAgICAgICAgfSxcbiAgICAgICAgICBleGFtcGxlOiB7XG4gICAgICAgICAgICBwaG9uZTogJzU1MjE5OTk5OTk5OTknLFxuICAgICAgICAgICAgaXNHcm91cDogZmFsc2UsXG4gICAgICAgICAgICBhbGw6IGZhbHNlLFxuICAgICAgICAgIH1cbiAgICAgICAgfVxuICAgICAgfVxuICAgICB9XG4gICAqL1xuICB0cnkge1xuICAgIGNvbnN0IHsgcGhvbmUsIGlzR3JvdXAgPSBmYWxzZSwgYWxsID0gZmFsc2UsIGlzTGlkID0gZmFsc2UgfSA9IHJlcS5ib2R5O1xuXG4gICAgY29uc3Qgc3Vic2NyaWJlT25lID0gYXN5bmMgKGNvbnRhdG86IHN0cmluZykgPT4ge1xuICAgICAgLy8gUHJlZmVyIHRoZSBtb2Rlcm4gV1BQLmNvbnRhY3Quc3Vic2NyaWJlUHJlc2VuY2Ugd2hpY2ggd29ya3Mgd2l0aFxuICAgICAgLy8gY3VycmVudCBXaGF0c0FwcCBXZWIuIFRoZSBsZWdhY3kgcmVxLmNsaWVudC5zdWJzY3JpYmVQcmVzZW5jZSB1c2VzXG4gICAgICAvLyB0aGUgaW50ZXJuYWwgV0FQSSB0aGF0IGNhbGxzIFN0b3JlLlByZXNlbmNlLmZpbmQoKSDigJQgYnJva2VuIGluIG5ld2VyXG4gICAgICAvLyBXQSB2ZXJzaW9ucyBhbmQgcmV0dXJucyA1MDAuIFdlIGZhbGwgYmFjayB0byB0aGUgbGVnYWN5IHBhdGggaWYgdGhlXG4gICAgICAvLyBXUFAgQVBJIGlzIG5vdCBhdmFpbGFibGUuXG4gICAgICBjb25zdCBwYWdlID0gKHJlcS5jbGllbnQgYXMgYW55KS5wYWdlO1xuICAgICAgaWYgKHBhZ2UpIHtcbiAgICAgICAgdHJ5IHtcbiAgICAgICAgICBhd2FpdCBwYWdlLmV2YWx1YXRlKChpZDogc3RyaW5nKSA9PiB7XG4gICAgICAgICAgICBjb25zdCB3cHAgPSAod2luZG93IGFzIGFueSkuV1BQO1xuICAgICAgICAgICAgaWYgKHdwcCAmJiB3cHAuY29udGFjdCAmJiB0eXBlb2Ygd3BwLmNvbnRhY3Quc3Vic2NyaWJlUHJlc2VuY2UgPT09ICdmdW5jdGlvbicpIHtcbiAgICAgICAgICAgICAgcmV0dXJuIHdwcC5jb250YWN0LnN1YnNjcmliZVByZXNlbmNlKGlkKTtcbiAgICAgICAgICAgIH1cbiAgICAgICAgICAgIC8vIEZhbGxiYWNrIHRvIFdQUC53aGF0c2FwcC5QcmVzZW5jZVV0aWxzIGlmIGF2YWlsYWJsZVxuICAgICAgICAgICAgaWYgKHdwcCAmJiB3cHAud2hhdHNhcHAgJiYgd3BwLndoYXRzYXBwLlByZXNlbmNlVXRpbHMpIHtcbiAgICAgICAgICAgICAgcmV0dXJuIHdwcC53aGF0c2FwcC5QcmVzZW5jZVV0aWxzLnN1YnNjcmliZVRvUHJlc2VuY2UoaWQpO1xuICAgICAgICAgICAgfVxuICAgICAgICAgICAgdGhyb3cgbmV3IEVycm9yKCdXUFAuY29udGFjdC5zdWJzY3JpYmVQcmVzZW5jZSBub3QgYXZhaWxhYmxlJyk7XG4gICAgICAgICAgfSwgY29udGF0byk7XG4gICAgICAgICAgcmVxLmxvZ2dlci5pbmZvKGBbc3Vic2NyaWJlUHJlc2VuY2VdIFdQUCBzdWJzY3JpYmVkOiAke2NvbnRhdG99YCk7XG4gICAgICAgICAgcmV0dXJuO1xuICAgICAgICB9IGNhdGNoICh3cHBFcnIpIHtcbiAgICAgICAgICByZXEubG9nZ2VyLndhcm4oYFtzdWJzY3JpYmVQcmVzZW5jZV0gV1BQIGZhbGxiYWNrIGZvciAke2NvbnRhdG99OiAke3dwcEVycn1gKTtcbiAgICAgICAgfVxuICAgICAgfVxuICAgICAgLy8gTGVnYWN5IGZhbGxiYWNrXG4gICAgICBhd2FpdCByZXEuY2xpZW50LnN1YnNjcmliZVByZXNlbmNlKGNvbnRhdG8pO1xuICAgIH07XG5cbiAgICBpZiAoYWxsKSB7XG4gICAgICBsZXQgY29udGFjdHM7XG4gICAgICBpZiAoaXNHcm91cCkge1xuICAgICAgICBjb25zdCBncm91cHMgPSBhd2FpdCByZXEuY2xpZW50LmdldEFsbEdyb3VwcyhmYWxzZSk7XG4gICAgICAgIGNvbnRhY3RzID0gZ3JvdXBzLm1hcCgocDogYW55KSA9PiBwLmlkLl9zZXJpYWxpemVkKTtcbiAgICAgIH0gZWxzZSB7XG4gICAgICAgIGNvbnN0IGNoYXRzID0gYXdhaXQgcmVxLmNsaWVudC5nZXRBbGxDb250YWN0cygpO1xuICAgICAgICBjb250YWN0cyA9IGNoYXRzLm1hcCgoYzogYW55KSA9PiBjLmlkLl9zZXJpYWxpemVkKTtcbiAgICAgIH1cbiAgICAgIGZvciAoY29uc3QgY29udGF0byBvZiBjb250YWN0cykge1xuICAgICAgICBhd2FpdCBzdWJzY3JpYmVPbmUoY29udGF0byk7XG4gICAgICB9XG4gICAgfSBlbHNlIHtcbiAgICAgIGZvciAoY29uc3QgY29udGF0byBvZiBjb250YWN0VG9BcnJheShwaG9uZSwgaXNHcm91cCwgZmFsc2UsIGlzTGlkKSkge1xuICAgICAgICBhd2FpdCBzdWJzY3JpYmVPbmUoY29udGF0byk7XG4gICAgICB9XG4gICAgfVxuXG4gICAgcmVzLnN0YXR1cygyMDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnc3VjY2VzcycsXG4gICAgICByZXNwb25zZTogeyBtZXNzYWdlOiAnU3Vic2NyaWJlIHByZXNlbmNlIGV4ZWN1dGVkJyB9LFxuICAgIH0pO1xuICB9IGNhdGNoIChlcnJvcikge1xuICAgIHJlcS5sb2dnZXIuZXJyb3IoZXJyb3IpO1xuICAgIHJlcy5zdGF0dXMoNTAwKS5qc29uKHtcbiAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgIG1lc3NhZ2U6ICdFcnJvciBvbiBzdWJzY3JpYmUgcHJlc2VuY2UnLFxuICAgICAgZXJyb3I6IGVycm9yLFxuICAgIH0pO1xuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBzZXRPbmxpbmVQcmVzZW5jZShyZXE6IFJlcXVlc3QsIHJlczogUmVzcG9uc2UpIHtcbiAgLyoqXG4gICAqICNzd2FnZ2VyLnRhZ3MgPSBbXCJNaXNjXCJdXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ3NldE9ubGluZVByZXNlbmNlJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgICAjc3dhZ2dlci5yZXF1ZXN0Qm9keSA9IHtcbiAgICAgIHJlcXVpcmVkOiB0cnVlLFxuICAgICAgXCJAY29udGVudFwiOiB7XG4gICAgICAgIFwiYXBwbGljYXRpb24vanNvblwiOiB7XG4gICAgICAgICAgc2NoZW1hOiB7XG4gICAgICAgICAgICB0eXBlOiBcIm9iamVjdFwiLFxuICAgICAgICAgICAgcHJvcGVydGllczoge1xuICAgICAgICAgICAgICBpc09ubGluZTogeyB0eXBlOiBcImJvb2xlYW5cIiB9LFxuICAgICAgICAgICAgfVxuICAgICAgICAgIH0sXG4gICAgICAgICAgZXhhbXBsZToge1xuICAgaXNPbmxpbmU6IGZhbHNlLFxuICAgICAgICAgIH1cbiAgICAgICAgfVxuICAgICAgfVxuICAgICB9XG4gICAqL1xuICB0cnkge1xuICAgIGNvbnN0IHsgaXNPbmxpbmUgPSB0cnVlIH0gPSByZXEuYm9keTtcblxuICAgIGF3YWl0IHJlcS5jbGllbnQuc2V0T25saW5lUHJlc2VuY2UoaXNPbmxpbmUpO1xuXG4gICAgcmVzLnN0YXR1cygyMDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnc3VjY2VzcycsXG4gICAgICByZXNwb25zZTogeyBtZXNzYWdlOiAnU2V0IE9ubGluZSBQcmVzZW5jZSBTdWNjZXNzZnVsbHknIH0sXG4gICAgfSk7XG4gIH0gY2F0Y2ggKGVycm9yKSB7XG4gICAgcmVzLnN0YXR1cyg1MDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgbWVzc2FnZTogJ0Vycm9yIG9uIHNldCBvbmxpbmUgcHJlc2VuY2UnLFxuICAgICAgZXJyb3I6IGVycm9yLFxuICAgIH0pO1xuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBlZGl0QnVzaW5lc3NQcm9maWxlKHJlcTogUmVxdWVzdCwgcmVzOiBSZXNwb25zZSkge1xuICAvKipcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIlByb2ZpbGVcIl1cbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAnZWRpdEJ1c2luZXNzUHJvZmlsZSdcbiAgICogI3N3YWdnZXIuZGVzY3JpcHRpb24gPSAnRWRpdCB5b3VyIGJ1c3NpbmVzcyBwcm9maWxlJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wib2JqXCJdID0ge1xuICAgICAgaW46ICdib2R5JyxcbiAgICAgIHNjaGVtYToge1xuICAgICAgICAkYWRyZXNzOiAnQXYuIE5vc3NhIFNlbmhvcmEgZGUgQ29wYWNhYmFuYSwgMzE1JyxcbiAgICAgICAgJGVtYWlsOiAndGVzdEB0ZXN0LmNvbS5icicsXG4gICAgICAgICRjYXRlZ29yaWVzOiB7XG4gICAgICAgICAgJGlkOiBcIjEzMzQzNjc0MzM4ODIxN1wiLFxuICAgICAgICAgICRsb2NhbGl6ZWRfZGlzcGxheV9uYW1lOiBcIkFydGVzIGUgZW50cmV0ZW5pbWVudG9cIixcbiAgICAgICAgICAkbm90X2FfYml6OiBmYWxzZSxcbiAgICAgICAgfSxcbiAgICAgICAgJHdlYnNpdGU6IFtcbiAgICAgICAgICBcImh0dHBzOi8vd3d3LndwcGNvbm5lY3QuaW9cIixcbiAgICAgICAgICBcImh0dHBzOi8vd3d3LnRlc3RlMi5jb20uYnJcIixcbiAgICAgICAgXSxcbiAgICAgIH1cbiAgICAgfVxuICAgICBcbiAgICAgI3N3YWdnZXIucmVxdWVzdEJvZHkgPSB7XG4gICAgICByZXF1aXJlZDogdHJ1ZSxcbiAgICAgIFwiQGNvbnRlbnRcIjoge1xuICAgICAgICBcImFwcGxpY2F0aW9uL2pzb25cIjoge1xuICAgICAgICAgIHNjaGVtYToge1xuICAgICAgICAgICAgdHlwZTogXCJvYmplY3RcIixcbiAgICAgICAgICAgIHByb3BlcnRpZXM6IHtcbiAgICAgICAgICAgICAgYWRyZXNzOiB7IHR5cGU6IFwic3RyaW5nXCIgfSxcbiAgICAgICAgICAgICAgZW1haWw6IHsgdHlwZTogXCJzdHJpbmdcIiB9LFxuICAgICAgICAgICAgICBjYXRlZ29yaWVzOiB7IHR5cGU6IFwib2JqZWN0XCIgfSxcbiAgICAgICAgICAgICAgd2Vic2l0ZXM6IHsgdHlwZTogXCJhcnJheVwiIH0sXG4gICAgICAgICAgICB9XG4gICAgICAgICAgfSxcbiAgICAgICAgICBleGFtcGxlOiB7XG4gICAgICAgICAgICBhZHJlc3M6ICdBdi4gTm9zc2EgU2VuaG9yYSBkZSBDb3BhY2FiYW5hLCAzMTUnLFxuICAgICAgICAgICAgZW1haWw6ICd0ZXN0QHRlc3QuY29tLmJyJyxcbiAgICAgICAgICAgIGNhdGVnb3JpZXM6IHtcbiAgICAgICAgICAgICAgJGlkOiBcIjEzMzQzNjc0MzM4ODIxN1wiLFxuICAgICAgICAgICAgICAkbG9jYWxpemVkX2Rpc3BsYXlfbmFtZTogXCJBcnRlcyBlIGVudHJldGVuaW1lbnRvXCIsXG4gICAgICAgICAgICAgICRub3RfYV9iaXo6IGZhbHNlLFxuICAgICAgICAgICAgfSxcbiAgICAgICAgICAgIHdlYnNpdGU6IFtcbiAgICAgICAgICAgICAgXCJodHRwczovL3d3dy53cHBjb25uZWN0LmlvXCIsXG4gICAgICAgICAgICAgIFwiaHR0cHM6Ly93d3cudGVzdGUyLmNvbS5iclwiLFxuICAgICAgICAgICAgXSxcbiAgICAgICAgICB9XG4gICAgICAgIH1cbiAgICAgIH1cbiAgICAgfVxuICAgKi9cbiAgdHJ5IHtcbiAgICByZXMuc3RhdHVzKDIwMCkuanNvbihhd2FpdCByZXEuY2xpZW50LmVkaXRCdXNpbmVzc1Byb2ZpbGUocmVxLmJvZHkpKTtcbiAgfSBjYXRjaCAoZXJyb3IpIHtcbiAgICByZXMuc3RhdHVzKDUwMCkuanNvbih7XG4gICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICBtZXNzYWdlOiAnRXJyb3Igb24gZWRpdCBidXNpbmVzcyBwcm9maWxlJyxcbiAgICAgIGVycm9yOiBlcnJvcixcbiAgICB9KTtcbiAgfVxufVxuIl0sIm1hcHBpbmdzIjoiOzs7Ozs7Ozs7Ozs7Ozs7OztBQWlCQSxJQUFBQSxHQUFBLEdBQUFDLHNCQUFBLENBQUFDLE9BQUE7QUFDQSxJQUFBQyxVQUFBLEdBQUFGLHNCQUFBLENBQUFDLE9BQUE7QUFDQSxJQUFBRSxPQUFBLEdBQUFILHNCQUFBLENBQUFDLE9BQUE7OztBQUdBLElBQUFHLFFBQUEsR0FBQUgsT0FBQTtBQUNBLElBQUFJLE9BQUEsR0FBQUwsc0JBQUEsQ0FBQUMsT0FBQTtBQUNBLElBQUFLLGtCQUFBLEdBQUFOLHNCQUFBLENBQUFDLE9BQUE7QUFDQSxJQUFBTSxVQUFBLEdBQUFOLE9BQUE7QUFDQSxJQUFBTyxhQUFBLEdBQUFSLHNCQUFBLENBQUFDLE9BQUE7QUFDQSxJQUFBUSxZQUFBLEdBQUFSLE9BQUEsd0JBQXlFLENBM0J6RTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FB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