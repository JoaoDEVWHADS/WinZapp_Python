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

    // If details are provided in the request body (e.g. POST request with local cache AND download URL), use them directly.
    const hasDownloadUrl = req.body && (req.body.clientUrl || req.body.deprecatedMms3Url || req.body.url || req.body.directPath);
    if (req.body && req.body.mediaKey && hasDownloadUrl) {
      req.logger.info(`Received full decryption keys and download URL in body for message ${messageId}. Bypassing Puppeteer lookup.`);
      message = req.body;
      if (!message.clientUrl && (message.url || message.deprecatedMms3Url)) {
        message.clientUrl = message.clientUrl || message.url || message.deprecatedMms3Url;
      }
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
//# sourceMappingURL=data:application/json;charset=utf-8;base64,eyJ2ZXJzaW9uIjozLCJuYW1lcyI6WyJfZnMiLCJfaW50ZXJvcFJlcXVpcmVEZWZhdWx0IiwicmVxdWlyZSIsIl9taW1lVHlwZXMiLCJfcXJjb2RlIiwiX3BhY2thZ2UiLCJfY29uZmlnIiwiX2NyZWF0ZVNlc3Npb25VdGlsIiwiX2Z1bmN0aW9ucyIsIl9nZXRBbGxUb2tlbnMiLCJfc2Vzc2lvblV0aWwiLCJTZXNzaW9uVXRpbCIsIkNyZWF0ZVNlc3Npb25VdGlsIiwiZG93bmxvYWRGaWxlRnVuY3Rpb24iLCJtZXNzYWdlIiwiY2xpZW50IiwibG9nZ2VyIiwiYnVmZmVyIiwiZGVjcnlwdEZpbGUiLCJmaWxlbmFtZSIsInQiLCJmcyIsImV4aXN0c1N5bmMiLCJyZXN1bHQiLCJ0eXBlIiwibWltZSIsImV4dGVuc2lvbiIsIm1pbWV0eXBlIiwid3JpdGVGaWxlIiwiZXJyIiwiZXJyb3IiLCJlIiwid2FybiIsImRvd25sb2FkTWVkaWEiLCJkb3dubG9hZCIsInBhdGgiLCJyZXBsYWNlIiwic3RhcnRBbGxTZXNzaW9ucyIsInJlcSIsInJlcyIsInNlY3JldGtleSIsInBhcmFtcyIsImF1dGhvcml6YXRpb24iLCJ0b2tlbiIsImhlYWRlcnMiLCJ0b2tlbkRlY3J5cHQiLCJ1bmRlZmluZWQiLCJzcGxpdCIsImFsbFNlc3Npb25zIiwiZ2V0QWxsVG9rZW5zIiwic2VydmVyT3B0aW9ucyIsInNlY3JldEtleSIsInN0YXR1cyIsImpzb24iLCJyZXNwb25zZSIsIm1hcCIsInNlc3Npb24iLCJ1dGlsIiwib3BlbmRhdGEiLCJzaG93QWxsU2Vzc2lvbnMiLCJhcnIiLCJPYmplY3QiLCJrZXlzIiwiY2xpZW50c0FycmF5IiwiZm9yRWFjaCIsIml0ZW0iLCJwdXNoIiwic3RhcnRTZXNzaW9uIiwid2FpdFFyQ29kZSIsImJvZHkiLCJnZXRTZXNzaW9uU3RhdGUiLCJjbG9zZVNlc3Npb24iLCJpbmZvIiwic2hvdWxkQ2xvc2UiLCJmb3JjZUtpbGxTZXNzaW9uIiwiY2xvc2UiLCJpbyIsImVtaXQiLCJjYWxsV2ViSG9vayIsImNvbm5lY3RlZCIsImxvZ091dFNlc3Npb24iLCJsb2dvdXQiLCJkZWxldGVTZXNzaW9uT25BcnJheSIsInNldFRpbWVvdXQiLCJwYXRoVXNlckRhdGEiLCJjb25maWciLCJjdXN0b21Vc2VyRGF0YURpciIsInBhdGhUb2tlbnMiLCJfX2Rpcm5hbWUiLCJwcm9taXNlcyIsInJtIiwicmVjdXJzaXZlIiwibWF4UmV0cmllcyIsImZvcmNlIiwicmV0cnlEZWxheSIsImNoZWNrQ29ubmVjdGlvblNlc3Npb24iLCJpc0Nvbm5lY3RlZCIsInJlY29ubmVjdFNvY2tldFN0cmVhbSIsInBhZ2UiLCJpc0Nsb3NlZCIsImV2YWx1YXRlIiwid3BwIiwid2luZG93IiwiV1BQIiwid2hhdHNhcHAiLCJDbWQiLCJvcGVuU29ja2V0U3RyZWFtIiwib2siLCJTdHJpbmciLCJkb3dubG9hZE1lZGlhQnlNZXNzYWdlIiwibWVzc2FnZUlkIiwiZ2V0TWVzc2FnZUJ5SWQiLCJpc01lZGlhIiwiaXNNTVMiLCJiYXNlNjQiLCJ0b1N0cmluZyIsImdldE1lZGlhQnlNZXNzYWdlIiwiaGFzRG93bmxvYWRVcmwiLCJjbGllbnRVcmwiLCJkZXByZWNhdGVkTW1zM1VybCIsInVybCIsImRpcmVjdFBhdGgiLCJtZWRpYUtleSIsImRhdGEiLCJCdWZmZXIiLCJmcm9tIiwicGFydHMiLCJsZW5ndGgiLCJjaGF0SWQiLCJtc2dJZCIsInRhcmdldENoYXRJZCIsIlN0b3JlIiwidGFyZ2V0V2lkIiwiV2lkRmFjdG9yeSIsImNyZWF0ZSIsImNoYXQiLCJmaW5kIiwiaW5jbHVkZXMiLCJsb2FkRWFybGllck1lc3NhZ2VzIiwiZ2V0TXNnU2FmZSIsIm1JZCIsIm0iLCJyYXdJZCIsIk1zZyIsIm1vZGVscyIsImZvdW5kIiwiaWQiLCJzZXIiLCJfc2VyaWFsaXplZCIsIml0ZW1JZCIsImNvbnNvbGUiLCJsb2ciLCJyZXRyeUVyciIsImxvYWRFcnIiLCJtZWRpYVVybCIsInRpbWVyIiwiZG93bmxvYWRQcm9taXNlIiwiY2F0Y2giLCJmaW5hbGx5IiwiY2xlYXJUaW1lb3V0IiwidGltZW91dFByb21pc2UiLCJQcm9taXNlIiwicmVzb2x2ZSIsInJhY2UiLCJzdGFydHNXaXRoIiwibWF0Y2hlcyIsIm1hdGNoIiwiZG93bmxvYWRFcnIiLCJkZWNyeXB0RXJyIiwiZnJlc2hNZXNzYWdlIiwiZnJlc2hEZWNyeXB0RXJyIiwiZXgiLCJFcnJvciIsInFyIiwidXJsY29kZSIsIlFSQ29kZSIsInRvRGF0YVVSTCIsInFyY29kZSIsInZlcnNpb24iLCJnZXRRckNvZGUiLCJxck9wdGlvbnMiLCJlcnJvckNvcnJlY3Rpb25MZXZlbCIsInNjYWxlIiwid2lkdGgiLCJpbWciLCJ3cml0ZUhlYWQiLCJlbmQiLCJraWxsU2VydmljZVdvcmtlciIsInJlc3RhcnRTZXJ2aWNlIiwic3Vic2NyaWJlUHJlc2VuY2UiLCJwaG9uZSIsImlzR3JvdXAiLCJhbGwiLCJpc0xpZCIsInN1YnNjcmliZU9uZSIsImNvbnRhdG8iLCJjb250YWN0IiwiUHJlc2VuY2VVdGlscyIsInN1YnNjcmliZVRvUHJlc2VuY2UiLCJ3cHBFcnIiLCJjb250YWN0cyIsImdyb3VwcyIsImdldEFsbEdyb3VwcyIsInAiLCJjaGF0cyIsImdldEFsbENvbnRhY3RzIiwiYyIsImNvbnRhY3RUb0FycmF5Iiwic2V0T25saW5lUHJlc2VuY2UiLCJpc09ubGluZSIsImVkaXRCdXNpbmVzc1Byb2ZpbGUiXSwic291cmNlcyI6WyIuLi8uLi9zcmMvY29udHJvbGxlci9zZXNzaW9uQ29udHJvbGxlci50cyJdLCJzb3VyY2VzQ29udGVudCI6WyIvKlxuICogQ29weXJpZ2h0IDIwMjEgV1BQQ29ubmVjdCBUZWFtXG4gKlxuICogTGljZW5zZWQgdW5kZXIgdGhlIEFwYWNoZSBMaWNlbnNlLCBWZXJzaW9uIDIuMCAodGhlIFwiTGljZW5zZVwiKTtcbiAqIHlvdSBtYXkgbm90IHVzZSB0aGlzIGZpbGUgZXhjZXB0IGluIGNvbXBsaWFuY2Ugd2l0aCB0aGUgTGljZW5zZS5cbiAqIFlvdSBtYXkgb2J0YWluIGEgY29weSBvZiB0aGUgTGljZW5zZSBhdFxuICpcbiAqICAgICBodHRwOi8vd3d3LmFwYWNoZS5vcmcvbGljZW5zZXMvTElDRU5TRS0yLjBcbiAqXG4gKiBVbmxlc3MgcmVxdWlyZWQgYnkgYXBwbGljYWJsZSBsYXcgb3IgYWdyZWVkIHRvIGluIHdyaXRpbmcsIHNvZnR3YXJlXG4gKiBkaXN0cmlidXRlZCB1bmRlciB0aGUgTGljZW5zZSBpcyBkaXN0cmlidXRlZCBvbiBhbiBcIkFTIElTXCIgQkFTSVMsXG4gKiBXSVRIT1VUIFdBUlJBTlRJRVMgT1IgQ09ORElUSU9OUyBPRiBBTlkgS0lORCwgZWl0aGVyIGV4cHJlc3Mgb3IgaW1wbGllZC5cbiAqIFNlZSB0aGUgTGljZW5zZSBmb3IgdGhlIHNwZWNpZmljIGxhbmd1YWdlIGdvdmVybmluZyBwZXJtY2xlYXJTZXNzaW9uaXNzaW9ucyBhbmRcbiAqIGxpbWl0YXRpb25zIHVuZGVyIHRoZSBMaWNlbnNlLlxuICovXG5pbXBvcnQgeyBNZXNzYWdlLCBXaGF0c2FwcCB9IGZyb20gJ0B3cHBjb25uZWN0LXRlYW0vd3BwY29ubmVjdCc7XG5pbXBvcnQgeyBSZXF1ZXN0LCBSZXNwb25zZSB9IGZyb20gJ2V4cHJlc3MnO1xuaW1wb3J0IGZzIGZyb20gJ2ZzJztcbmltcG9ydCBtaW1lIGZyb20gJ21pbWUtdHlwZXMnO1xuaW1wb3J0IFFSQ29kZSBmcm9tICdxcmNvZGUnO1xuaW1wb3J0IHsgTG9nZ2VyIH0gZnJvbSAnd2luc3Rvbic7XG5cbmltcG9ydCB7IHZlcnNpb24gfSBmcm9tICcuLi8uLi9wYWNrYWdlLmpzb24nO1xuaW1wb3J0IGNvbmZpZyBmcm9tICcuLi9jb25maWcnO1xuaW1wb3J0IENyZWF0ZVNlc3Npb25VdGlsIGZyb20gJy4uL3V0aWwvY3JlYXRlU2Vzc2lvblV0aWwnO1xuaW1wb3J0IHsgY2FsbFdlYkhvb2ssIGNvbnRhY3RUb0FycmF5IH0gZnJvbSAnLi4vdXRpbC9mdW5jdGlvbnMnO1xuaW1wb3J0IGdldEFsbFRva2VucyBmcm9tICcuLi91dGlsL2dldEFsbFRva2Vucyc7XG5pbXBvcnQgeyBjbGllbnRzQXJyYXksIGRlbGV0ZVNlc3Npb25PbkFycmF5IH0gZnJvbSAnLi4vdXRpbC9zZXNzaW9uVXRpbCc7XG5cbmNvbnN0IFNlc3Npb25VdGlsID0gbmV3IENyZWF0ZVNlc3Npb25VdGlsKCk7XG5cbmFzeW5jIGZ1bmN0aW9uIGRvd25sb2FkRmlsZUZ1bmN0aW9uKFxuICBtZXNzYWdlOiBNZXNzYWdlLFxuICBjbGllbnQ6IFdoYXRzYXBwLFxuICBsb2dnZXI6IExvZ2dlclxuKSB7XG4gIHRyeSB7XG4gICAgY29uc3QgYnVmZmVyID0gYXdhaXQgY2xpZW50LmRlY3J5cHRGaWxlKG1lc3NhZ2UpO1xuXG4gICAgY29uc3QgZmlsZW5hbWUgPSBgLi9XaGF0c0FwcEltYWdlcy9maWxlJHttZXNzYWdlLnR9YDtcbiAgICBpZiAoIWZzLmV4aXN0c1N5bmMoZmlsZW5hbWUpKSB7XG4gICAgICBsZXQgcmVzdWx0ID0gJyc7XG4gICAgICBpZiAobWVzc2FnZS50eXBlID09PSAncHR0Jykge1xuICAgICAgICByZXN1bHQgPSBgJHtmaWxlbmFtZX0ub2dhYDtcbiAgICAgIH0gZWxzZSB7XG4gICAgICAgIHJlc3VsdCA9IGAke2ZpbGVuYW1lfS4ke21pbWUuZXh0ZW5zaW9uKG1lc3NhZ2UubWltZXR5cGUpfWA7XG4gICAgICB9XG5cbiAgICAgIGF3YWl0IGZzLndyaXRlRmlsZShyZXN1bHQsIGJ1ZmZlciwgKGVycikgPT4ge1xuICAgICAgICBpZiAoZXJyKSB7XG4gICAgICAgICAgbG9nZ2VyLmVycm9yKGVycik7XG4gICAgICAgIH1cbiAgICAgIH0pO1xuXG4gICAgICByZXR1cm4gcmVzdWx0O1xuICAgIH0gZWxzZSB7XG4gICAgICByZXR1cm4gYCR7ZmlsZW5hbWV9LiR7bWltZS5leHRlbnNpb24obWVzc2FnZS5taW1ldHlwZSl9YDtcbiAgICB9XG4gIH0gY2F0Y2ggKGUpIHtcbiAgICBsb2dnZXIuZXJyb3IoZSk7XG4gICAgbG9nZ2VyLndhcm4oXG4gICAgICAnRXJybyBhbyBkZXNjcmlwdG9ncmFmYXIgYSBtaWRpYSwgdGVudGFuZG8gZmF6ZXIgbyBkb3dubG9hZCBkaXJldG8uLi4nXG4gICAgKTtcbiAgICB0cnkge1xuICAgICAgY29uc3QgYnVmZmVyID0gYXdhaXQgY2xpZW50LmRvd25sb2FkTWVkaWEobWVzc2FnZSk7XG4gICAgICBjb25zdCBmaWxlbmFtZSA9IGAuL1doYXRzQXBwSW1hZ2VzL2ZpbGUke21lc3NhZ2UudH1gO1xuICAgICAgaWYgKCFmcy5leGlzdHNTeW5jKGZpbGVuYW1lKSkge1xuICAgICAgICBsZXQgcmVzdWx0ID0gJyc7XG4gICAgICAgIGlmIChtZXNzYWdlLnR5cGUgPT09ICdwdHQnKSB7XG4gICAgICAgICAgcmVzdWx0ID0gYCR7ZmlsZW5hbWV9Lm9nYWA7XG4gICAgICAgIH0gZWxzZSB7XG4gICAgICAgICAgcmVzdWx0ID0gYCR7ZmlsZW5hbWV9LiR7bWltZS5leHRlbnNpb24obWVzc2FnZS5taW1ldHlwZSl9YDtcbiAgICAgICAgfVxuXG4gICAgICAgIGF3YWl0IGZzLndyaXRlRmlsZShyZXN1bHQsIGJ1ZmZlciwgKGVycikgPT4ge1xuICAgICAgICAgIGlmIChlcnIpIHtcbiAgICAgICAgICAgIGxvZ2dlci5lcnJvcihlcnIpO1xuICAgICAgICAgIH1cbiAgICAgICAgfSk7XG5cbiAgICAgICAgcmV0dXJuIHJlc3VsdDtcbiAgICAgIH0gZWxzZSB7XG4gICAgICAgIHJldHVybiBgJHtmaWxlbmFtZX0uJHttaW1lLmV4dGVuc2lvbihtZXNzYWdlLm1pbWV0eXBlKX1gO1xuICAgICAgfVxuICAgIH0gY2F0Y2ggKGUpIHtcbiAgICAgIGxvZ2dlci5lcnJvcihlKTtcbiAgICAgIGxvZ2dlci53YXJuKCdOw6NvIGZvaSBwb3Nzw612ZWwgYmFpeGFyIGEgbcOtZGlhLi4uJyk7XG4gICAgfVxuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBkb3dubG9hZChtZXNzYWdlOiBhbnksIGNsaWVudDogYW55LCBsb2dnZXI6IGFueSkge1xuICB0cnkge1xuICAgIGNvbnN0IHBhdGggPSBhd2FpdCBkb3dubG9hZEZpbGVGdW5jdGlvbihtZXNzYWdlLCBjbGllbnQsIGxvZ2dlcik7XG4gICAgcmV0dXJuIHBhdGg/LnJlcGxhY2UoJy4vJywgJycpO1xuICB9IGNhdGNoIChlKSB7XG4gICAgbG9nZ2VyLmVycm9yKGUpO1xuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBzdGFydEFsbFNlc3Npb25zKFxuICByZXE6IFJlcXVlc3QsXG4gIHJlczogUmVzcG9uc2Vcbik6IFByb21pc2U8YW55PiB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiQXV0aFwiXVxuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5vcGVyYXRpb25JZCA9ICdzdGFydEFsbFNlc3Npb25zJ1xuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2VjcmV0a2V5XCJdID0ge1xuICAgICAgc2NoZW1hOiAnVEhJU0lTTVlTRUNVUkVDT0RFJ1xuICAgICB9XG4gICAqL1xuICBjb25zdCB7IHNlY3JldGtleSB9ID0gcmVxLnBhcmFtcztcbiAgY29uc3QgeyBhdXRob3JpemF0aW9uOiB0b2tlbiB9ID0gcmVxLmhlYWRlcnM7XG5cbiAgbGV0IHRva2VuRGVjcnlwdCA9ICcnO1xuXG4gIGlmIChzZWNyZXRrZXkgPT09IHVuZGVmaW5lZCkge1xuICAgIHRva2VuRGVjcnlwdCA9ICh0b2tlbiBhcyBhbnkpLnNwbGl0KCcgJylbMF07XG4gIH0gZWxzZSB7XG4gICAgdG9rZW5EZWNyeXB0ID0gc2VjcmV0a2V5O1xuICB9XG5cbiAgY29uc3QgYWxsU2Vzc2lvbnMgPSBhd2FpdCBnZXRBbGxUb2tlbnMocmVxKTtcblxuICBpZiAodG9rZW5EZWNyeXB0ICE9PSByZXEuc2VydmVyT3B0aW9ucy5zZWNyZXRLZXkpIHtcbiAgICByZXMuc3RhdHVzKDQwMCkuanNvbih7XG4gICAgICByZXNwb25zZTogJ2Vycm9yJyxcbiAgICAgIG1lc3NhZ2U6ICdUaGUgdG9rZW4gaXMgaW5jb3JyZWN0JyxcbiAgICB9KTtcbiAgfVxuXG4gIGFsbFNlc3Npb25zLm1hcChhc3luYyAoc2Vzc2lvbjogc3RyaW5nKSA9PiB7XG4gICAgY29uc3QgdXRpbCA9IG5ldyBDcmVhdGVTZXNzaW9uVXRpbCgpO1xuICAgIGF3YWl0IHV0aWwub3BlbmRhdGEocmVxLCBzZXNzaW9uKTtcbiAgfSk7XG5cbiAgcmV0dXJuIGF3YWl0IHJlc1xuICAgIC5zdGF0dXMoMjAxKVxuICAgIC5qc29uKHsgc3RhdHVzOiAnc3VjY2VzcycsIG1lc3NhZ2U6ICdTdGFydGluZyBhbGwgc2Vzc2lvbnMnIH0pO1xufVxuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24gc2hvd0FsbFNlc3Npb25zKFxuICByZXE6IFJlcXVlc3QsXG4gIHJlczogUmVzcG9uc2Vcbik6IFByb21pc2U8YW55PiB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiQXV0aFwiXVxuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5vcGVyYXRpb25JZCA9ICdzaG93QWxsU2Vzc2lvbnMnXG4gICAgICNzd2FnZ2VyLmF1dG9RdWVyeT1mYWxzZVxuICAgICAjc3dhZ2dlci5hdXRvSGVhZGVycz1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlY3JldGtleVwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ1RISVNJU01ZU0VDVVJFVE9LRU4nXG4gICAgIH1cbiAgICovXG4gIGNvbnN0IHsgc2VjcmV0a2V5IH0gPSByZXEucGFyYW1zO1xuICBjb25zdCB7IGF1dGhvcml6YXRpb246IHRva2VuIH0gPSByZXEuaGVhZGVycztcblxuICBsZXQgdG9rZW5EZWNyeXB0OiBhbnkgPSAnJztcblxuICBpZiAoc2VjcmV0a2V5ID09PSB1bmRlZmluZWQpIHtcbiAgICB0b2tlbkRlY3J5cHQgPSB0b2tlbj8uc3BsaXQoJyAnKVswXTtcbiAgfSBlbHNlIHtcbiAgICB0b2tlbkRlY3J5cHQgPSBzZWNyZXRrZXk7XG4gIH1cblxuICBjb25zdCBhcnI6IGFueSA9IFtdO1xuXG4gIGlmICh0b2tlbkRlY3J5cHQgIT09IHJlcS5zZXJ2ZXJPcHRpb25zLnNlY3JldEtleSkge1xuICAgIHJlcy5zdGF0dXMoNDAwKS5qc29uKHtcbiAgICAgIHJlc3BvbnNlOiBmYWxzZSxcbiAgICAgIG1lc3NhZ2U6ICdUaGUgdG9rZW4gaXMgaW5jb3JyZWN0JyxcbiAgICB9KTtcbiAgfVxuXG4gIE9iamVjdC5rZXlzKGNsaWVudHNBcnJheSkuZm9yRWFjaCgoaXRlbSkgPT4ge1xuICAgIGFyci5wdXNoKHsgc2Vzc2lvbjogaXRlbSB9KTtcbiAgfSk7XG5cbiAgcmVzLnN0YXR1cygyMDApLmpzb24oeyByZXNwb25zZTogYXdhaXQgZ2V0QWxsVG9rZW5zKHJlcSkgfSk7XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBzdGFydFNlc3Npb24ocmVxOiBSZXF1ZXN0LCByZXM6IFJlc3BvbnNlKTogUHJvbWlzZTxhbnk+IHtcbiAgLyoqXG4gICAqICNzd2FnZ2VyLnRhZ3MgPSBbXCJBdXRoXCJdXG4gICAgICNzd2FnZ2VyLmF1dG9Cb2R5PWZhbHNlXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ3N0YXJ0U2Vzc2lvbidcbiAgICAgI3N3YWdnZXIuc2VjdXJpdHkgPSBbe1xuICAgICAgICAgICAgXCJiZWFyZXJBdXRoXCI6IFtdXG4gICAgIH1dXG4gICAgICNzd2FnZ2VyLnBhcmFtZXRlcnNbXCJzZXNzaW9uXCJdID0ge1xuICAgICAgc2NoZW1hOiAnTkVSRFdIQVRTX0FNRVJJQ0EnXG4gICAgIH1cbiAgICAgI3N3YWdnZXIucmVxdWVzdEJvZHkgPSB7XG4gICAgICByZXF1aXJlZDogdHJ1ZSxcbiAgICAgIFwiQGNvbnRlbnRcIjoge1xuICAgICAgICBcImFwcGxpY2F0aW9uL2pzb25cIjoge1xuICAgICAgICAgIHNjaGVtYToge1xuICAgICAgICAgICAgdHlwZTogXCJvYmplY3RcIixcbiAgICAgICAgICAgIHByb3BlcnRpZXM6IHtcbiAgICAgICAgICAgICAgd2ViaG9vazogeyB0eXBlOiBcInN0cmluZ1wiIH0sXG4gICAgICAgICAgICAgIHdhaXRRckNvZGU6IHsgdHlwZTogXCJib29sZWFuXCIgfSxcbiAgICAgICAgICAgICAgcHJveHk6IHtcbiAgICAgICAgICAgICAgICB0eXBlOiBcIm9iamVjdFwiLFxuICAgICAgICAgICAgICAgIHByb3BlcnRpZXM6IHtcbiAgICAgICAgICAgICAgICAgIHVybDogeyB0eXBlOiBcInN0cmluZ1wiIH0sXG4gICAgICAgICAgICAgICAgICB1c2VybmFtZTogeyB0eXBlOiBcInN0cmluZ1wiIH0sXG4gICAgICAgICAgICAgICAgICBwYXNzd29yZDogeyB0eXBlOiBcInN0cmluZ1wiIH0sXG4gICAgICAgICAgICAgICAgfVxuICAgICAgICAgICAgICB9XG4gICAgICAgICAgICB9XG4gICAgICAgICAgfSxcbiAgICAgICAgICBleGFtcGxlOiB7XG4gICAgICAgICAgICB3ZWJob29rOiBcIlwiLFxuICAgICAgICAgICAgd2FpdFFyQ29kZTogZmFsc2UsXG4gICAgICAgICAgICBwcm94eToge1xuICAgICAgICAgICAgICB1cmw6IFwiaHR0cDovL215cHJveHkuY29tOjgwODBcIixcbiAgICAgICAgICAgICAgdXNlcm5hbWU6IFwibXl1c2VyXCIsXG4gICAgICAgICAgICAgIHBhc3N3b3JkOiBcIm15cGFzc3dvcmRcIlxuICAgICAgICAgICAgfVxuICAgICAgICAgIH1cbiAgICAgICAgfVxuICAgICAgfVxuICAgICB9XG4gICAqL1xuICBjb25zdCBzZXNzaW9uID0gcmVxLnNlc3Npb247XG4gIGNvbnN0IHsgd2FpdFFyQ29kZSA9IGZhbHNlIH0gPSByZXEuYm9keTtcblxuICBhd2FpdCBnZXRTZXNzaW9uU3RhdGUocmVxLCByZXMpO1xuICBhd2FpdCBTZXNzaW9uVXRpbC5vcGVuZGF0YShyZXEsIHNlc3Npb24sIHdhaXRRckNvZGUgPyByZXMgOiBudWxsKTtcbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIGNsb3NlU2Vzc2lvbihyZXE6IFJlcXVlc3QsIHJlczogUmVzcG9uc2UpOiBQcm9taXNlPGFueT4ge1xuICAvKipcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIkF1dGhcIl1cbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAnY2xvc2VTZXNzaW9uJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT10cnVlXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAqL1xuICBjb25zdCBzZXNzaW9uID0gcmVxLnNlc3Npb247XG4gIHRyeSB7XG4gICAgY29uc3QgY2xpZW50ID0gKGNsaWVudHNBcnJheSBhcyBhbnkpW3Nlc3Npb25dO1xuICAgIGlmICghY2xpZW50KSB7XG4gICAgICByZXR1cm4gYXdhaXQgcmVzXG4gICAgICAgIC5zdGF0dXMoMjAwKVxuICAgICAgICAuanNvbih7IHN0YXR1czogdHJ1ZSwgbWVzc2FnZTogJ1Nlc3Npb24gc3VjY2Vzc2Z1bGx5IGNsb3NlZCcgfSk7XG4gICAgfVxuXG4gICAgaWYgKGNsaWVudC5zdGF0dXMgIT09ICdDT05ORUNURUQnICYmIGNsaWVudC5zdGF0dXMgIT09ICdvcGVuJykge1xuICAgICAgcmVxLmxvZ2dlci5pbmZvKGBbJHtzZXNzaW9ufV0gRm9yY2Uga2lsbGluZyBzZXNzaW9uIGJlY2F1c2Ugc3RhdHVzIGlzICR7Y2xpZW50LnN0YXR1c31gKTtcbiAgICAgIGNsaWVudC5zaG91bGRDbG9zZSA9IHRydWU7XG4gICAgICB0cnkge1xuICAgICAgICBTZXNzaW9uVXRpbC5mb3JjZUtpbGxTZXNzaW9uKHNlc3Npb24sIHJlcS5sb2dnZXIpO1xuICAgICAgfSBjYXRjaCAoZSkge31cbiAgICAgIChjbGllbnRzQXJyYXkgYXMgYW55KVtzZXNzaW9uXSA9IHVuZGVmaW5lZDtcbiAgICAgIHJldHVybiBhd2FpdCByZXNcbiAgICAgICAgLnN0YXR1cygyMDApXG4gICAgICAgIC5qc29uKHsgc3RhdHVzOiB0cnVlLCBtZXNzYWdlOiAnU2Vzc2lvbiBmb3JjZSBjbG9zZWQnIH0pO1xuICAgIH1cblxuICAgIChjbGllbnRzQXJyYXkgYXMgYW55KVtzZXNzaW9uXSA9IHsgc3RhdHVzOiBudWxsIH07XG5cbiAgICBpZiAocmVxLmNsaWVudCAmJiB0eXBlb2YgcmVxLmNsaWVudC5jbG9zZSA9PT0gJ2Z1bmN0aW9uJykge1xuICAgICAgYXdhaXQgcmVxLmNsaWVudC5jbG9zZSgpO1xuICAgIH1cbiAgICAgIHJlcS5pby5lbWl0KCd3aGF0c2FwcC1zdGF0dXMnLCBmYWxzZSk7XG4gICAgICBjYWxsV2ViSG9vayhyZXEuY2xpZW50LCByZXEsICdjbG9zZXNlc3Npb24nLCB7XG4gICAgICAgIG1lc3NhZ2U6IGBTZXNzaW9uOiAke3Nlc3Npb259IGRpc2Nvbm5lY3RlZGAsXG4gICAgICAgIGNvbm5lY3RlZDogZmFsc2UsXG4gICAgICB9KTtcblxuICAgICAgcmV0dXJuIGF3YWl0IHJlc1xuICAgICAgICAuc3RhdHVzKDIwMClcbiAgICAgICAgLmpzb24oeyBzdGF0dXM6IHRydWUsIG1lc3NhZ2U6ICdTZXNzaW9uIHN1Y2Nlc3NmdWxseSBjbG9zZWQnIH0pO1xuICB9IGNhdGNoIChlcnJvcikge1xuICAgIHJlcS5sb2dnZXIuZXJyb3IoZXJyb3IpO1xuICAgIHJldHVybiBhd2FpdCByZXNcbiAgICAgIC5zdGF0dXMoNTAwKVxuICAgICAgLmpzb24oeyBzdGF0dXM6IGZhbHNlLCBtZXNzYWdlOiAnRXJyb3IgY2xvc2luZyBzZXNzaW9uJywgZXJyb3IgfSk7XG4gIH1cbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIGxvZ091dFNlc3Npb24ocmVxOiBSZXF1ZXN0LCByZXM6IFJlc3BvbnNlKTogUHJvbWlzZTxhbnk+IHtcbiAgLyoqXG4gICAqICNzd2FnZ2VyLnRhZ3MgPSBbXCJBdXRoXCJdXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ2xvZ291dFNlc3Npb24nXG4gICAqICNzd2FnZ2VyLmRlc2NyaXB0aW9uID0gJ1RoaXMgcm91dGUgbG9nb3V0IGFuZCBkZWxldGUgc2Vzc2lvbiBkYXRhJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgKi9cbiAgdHJ5IHtcbiAgICBjb25zdCBzZXNzaW9uID0gcmVxLnNlc3Npb247XG4gICAgYXdhaXQgcmVxLmNsaWVudC5sb2dvdXQoKTtcbiAgICBkZWxldGVTZXNzaW9uT25BcnJheShyZXEuc2Vzc2lvbik7XG5cbiAgICBzZXRUaW1lb3V0KGFzeW5jICgpID0+IHtcbiAgICAgIGNvbnN0IHBhdGhVc2VyRGF0YSA9IGNvbmZpZy5jdXN0b21Vc2VyRGF0YURpciArIHJlcS5zZXNzaW9uO1xuICAgICAgY29uc3QgcGF0aFRva2VucyA9IF9fZGlybmFtZSArIGAuLi8uLi8uLi90b2tlbnMvJHtyZXEuc2Vzc2lvbn0uZGF0YS5qc29uYDtcblxuICAgICAgaWYgKGZzLmV4aXN0c1N5bmMocGF0aFVzZXJEYXRhKSkge1xuICAgICAgICBhd2FpdCBmcy5wcm9taXNlcy5ybShwYXRoVXNlckRhdGEsIHtcbiAgICAgICAgICByZWN1cnNpdmU6IHRydWUsXG4gICAgICAgICAgbWF4UmV0cmllczogNSxcbiAgICAgICAgICBmb3JjZTogdHJ1ZSxcbiAgICAgICAgICByZXRyeURlbGF5OiAxMDAwLFxuICAgICAgICB9KTtcbiAgICAgIH1cbiAgICAgIGlmIChmcy5leGlzdHNTeW5jKHBhdGhUb2tlbnMpKSB7XG4gICAgICAgIGF3YWl0IGZzLnByb21pc2VzLnJtKHBhdGhUb2tlbnMsIHtcbiAgICAgICAgICByZWN1cnNpdmU6IHRydWUsXG4gICAgICAgICAgbWF4UmV0cmllczogNSxcbiAgICAgICAgICBmb3JjZTogdHJ1ZSxcbiAgICAgICAgICByZXRyeURlbGF5OiAxMDAwLFxuICAgICAgICB9KTtcbiAgICAgIH1cblxuICAgICAgcmVxLmlvLmVtaXQoJ3doYXRzYXBwLXN0YXR1cycsIGZhbHNlKTtcbiAgICAgIGNhbGxXZWJIb29rKHJlcS5jbGllbnQsIHJlcSwgJ2xvZ291dHNlc3Npb24nLCB7XG4gICAgICAgIG1lc3NhZ2U6IGBTZXNzaW9uOiAke3Nlc3Npb259IGxvZ2dlZCBvdXRgLFxuICAgICAgICBjb25uZWN0ZWQ6IGZhbHNlLFxuICAgICAgfSk7XG5cbiAgICAgIHJldHVybiBhd2FpdCByZXNcbiAgICAgICAgLnN0YXR1cygyMDApXG4gICAgICAgIC5qc29uKHsgc3RhdHVzOiB0cnVlLCBtZXNzYWdlOiAnU2Vzc2lvbiBzdWNjZXNzZnVsbHkgY2xvc2VkJyB9KTtcbiAgICB9LCA1MDApO1xuICAgIC8qdHJ5IHtcbiAgICAgIGF3YWl0IHJlcS5jbGllbnQuY2xvc2UoKTtcbiAgICB9IGNhdGNoIChlcnJvcikge30qL1xuICB9IGNhdGNoIChlcnJvcikge1xuICAgIHJlcS5sb2dnZXIuZXJyb3IoZXJyb3IpO1xuICAgIHJlc1xuICAgICAgLnN0YXR1cyg1MDApXG4gICAgICAuanNvbih7IHN0YXR1czogZmFsc2UsIG1lc3NhZ2U6ICdFcnJvciBjbG9zaW5nIHNlc3Npb24nLCBlcnJvciB9KTtcbiAgfVxufVxuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24gY2hlY2tDb25uZWN0aW9uU2Vzc2lvbihcbiAgcmVxOiBSZXF1ZXN0LFxuICByZXM6IFJlc3BvbnNlXG4pOiBQcm9taXNlPGFueT4ge1xuICAvKipcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIkF1dGhcIl1cbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAnQ2hlY2tDb25uZWN0aW9uU3RhdGUnXG4gICAgICNzd2FnZ2VyLmF1dG9Cb2R5PWZhbHNlXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAqL1xuICB0cnkge1xuICAgIGF3YWl0IHJlcS5jbGllbnQuaXNDb25uZWN0ZWQoKTtcblxuICAgIHJlcy5zdGF0dXMoMjAwKS5qc29uKHsgc3RhdHVzOiB0cnVlLCBtZXNzYWdlOiAnQ29ubmVjdGVkJyB9KTtcbiAgfSBjYXRjaCAoZXJyb3IpIHtcbiAgICByZXMuc3RhdHVzKDIwMCkuanNvbih7IHN0YXR1czogZmFsc2UsIG1lc3NhZ2U6ICdEaXNjb25uZWN0ZWQnIH0pO1xuICB9XG59XG5cbi8vIFdpblphcHAgcGF0Y2g6IG51ZGdlIFdoYXRzQXBwIFdlYidzIG93biBtdWx0aS1kZXZpY2Ugc29ja2V0IGJhY2sgb3Blbi5cbi8vXG4vLyBSZXBvcnRlZCBsaXZlOiBhZnRlciB0aGUgT1MgcmVzdW1lcyBmcm9tIHNsZWVwLCBXaW5aYXBwJ3Mgc3RhdHVzLXNlc3Npb25cbi8vIHByb2JlIGtlZXBzIHJlcG9ydGluZyB0aGUgV1BQQ29ubmVjdCBzZXNzaW9uIG9iamVjdCBhcyBcIkNPTk5FQ1RFRFwiICh0aGF0XG4vLyBzdHJpbmcgaXMganVzdCBjYWNoZWQgYXQgc2Vzc2lvbiBjcmVhdGlvbiDigJQgc2VlIGNoZWNrQ29ubmVjdGlvblNlc3Npb24nc1xuLy8gb3duIGNvbW1lbnQgYWJvdmUgaXQpLCBidXQgdGhlICpsaXZlKiBpc0Nvbm5lY3RlZCgpIHByb2JlIG5ldmVyIGNvbWVzIGJhY2tcbi8vIHRydWUgYWdhaW4sIGZvcmV2ZXIg4oCUIHRoZSBhcHAgaXMgc3R1Y2sgb2ZmbGluZSB1bnRpbCB0aGUgd2hvbGUgcHJvZ3JhbSBpc1xuLy8gcmVzdGFydGVkIChhIGZyZXNoIFB1cHBldGVlci9DaHJvbWUgKyBmcmVzaCBwYWdlKS5cbi8vXG4vLyBUaGUgcmVhbCBXaGF0c0FwcCBXZWIgY2xpZW50IHJlLW9wZW5zIGl0cyBzb2NrZXQgc3RyZWFtIHZpYVxuLy8gV1BQLndoYXRzYXBwLkNtZC5vcGVuU29ja2V0U3RyZWFtKCkg4oCUIG5vcm1hbGx5IHRyaWdnZXJlZCBieSB0aGUgcGFnZSdzIG93blxuLy8gdmlzaWJpbGl0eS9mb2N1cy9vbmxpbmUgRE9NIGV2ZW50cy4gVGhpcyBzZXNzaW9uJ3MgQ2hyb21lIHBhZ2UgcnVuc1xuLy8gaGVhZGxlc3MgYW5kIGlzIG5ldmVyIGZvY3VzZWQgb3IgYnJvdWdodCB0byB0aGUgZm9yZWdyb3VuZCwgc28gbm90aGluZ1xuLy8gZXZlciBmaXJlcyB0aG9zZSBldmVudHMgYWZ0ZXIgYSBzdXNwZW5kL3Jlc3VtZSBjeWNsZSDigJQgdGhlIHNvY2tldCB0aGF0XG4vLyB3ZW50IGRvd24gZHVyaW5nIHNsZWVwIGhhcyBubyB0cmlnZ2VyIGxlZnQgdG8gcmVjb25uZWN0IGl0LCB1bmxpa2UgYSByZWFsLFxuLy8gdmlzaWJsZSBicm93c2VyIHRhYiBhIHVzZXIgbWlnaHQgY2xpY2sgYmFjayBpbnRvLiBDYWxsaW5nIHRoZSBzYW1lXG4vLyBpbnRlcm5hbCBjb21tYW5kIGRpcmVjdGx5IHJlcHJvZHVjZXMgd2hhdGV2ZXIgYSBmb2N1cy92aXNpYmlsaXR5IGV2ZW50XG4vLyB3b3VsZCBoYXZlIHRyaWdnZXJlZCBvbiBhIG5vcm1hbCB0YWIuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24gcmVjb25uZWN0U29ja2V0U3RyZWFtKHJlcTogUmVxdWVzdCwgcmVzOiBSZXNwb25zZSkge1xuICAvKipcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIkF1dGhcIl1cbiAgICAgI3N3YWdnZXIuYXV0b0JvZHk9ZmFsc2VcbiAgICAgI3N3YWdnZXIuc2VjdXJpdHkgPSBbe1xuICAgICAgICAgICAgXCJiZWFyZXJBdXRoXCI6IFtdXG4gICAgIH1dXG4gICAgICNzd2FnZ2VyLnBhcmFtZXRlcnNbXCJzZXNzaW9uXCJdID0ge1xuICAgICAgc2NoZW1hOiAnTkVSRFdIQVRTX0FNRVJJQ0EnXG4gICAgIH1cbiAgICovXG4gIHRyeSB7XG4gICAgY29uc3QgcGFnZSA9IChyZXEuY2xpZW50IGFzIGFueSk/LnBhZ2U7XG4gICAgaWYgKCFwYWdlIHx8IHBhZ2UuaXNDbG9zZWQoKSkge1xuICAgICAgcmV0dXJuIHJlcy5zdGF0dXMoNDAwKS5qc29uKHtcbiAgICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgICBtZXNzYWdlOiAnVGhlIFdoYXRzQXBwIHNlc3Npb24gaXMgbm90IGFjdGl2ZS4nLFxuICAgICAgfSk7XG4gICAgfVxuICAgIGNvbnN0IHJlc3VsdCA9IGF3YWl0IHBhZ2UuZXZhbHVhdGUoKCkgPT4ge1xuICAgICAgdHJ5IHtcbiAgICAgICAgY29uc3Qgd3BwID0gKHdpbmRvdyBhcyBhbnkpLldQUDtcbiAgICAgICAgaWYgKHdwcD8ud2hhdHNhcHA/LkNtZD8ub3BlblNvY2tldFN0cmVhbSkge1xuICAgICAgICAgIHdwcC53aGF0c2FwcC5DbWQub3BlblNvY2tldFN0cmVhbSgpO1xuICAgICAgICAgIHJldHVybiB7IG9rOiB0cnVlIH07XG4gICAgICAgIH1cbiAgICAgICAgcmV0dXJuIHsgb2s6IGZhbHNlLCBlcnJvcjogJ1dQUC53aGF0c2FwcC5DbWQub3BlblNvY2tldFN0cmVhbSBub3QgYXZhaWxhYmxlJyB9O1xuICAgICAgfSBjYXRjaCAoZTogYW55KSB7XG4gICAgICAgIHJldHVybiB7IG9rOiBmYWxzZSwgZXJyb3I6IGU/Lm1lc3NhZ2UgfHwgU3RyaW5nKGUpIH07XG4gICAgICB9XG4gICAgfSk7XG4gICAgaWYgKCFyZXN1bHQ/Lm9rKSB7XG4gICAgICByZXEubG9nZ2VyLndhcm4oYFtyZWNvbm5lY3RTb2NrZXRTdHJlYW1dICR7cmVzdWx0Py5lcnJvciB8fCAndW5rbm93biBmYWlsdXJlJ31gKTtcbiAgICB9XG4gICAgcmVzLnN0YXR1cygyMDApLmpzb24oeyBzdGF0dXM6ICdzdWNjZXNzJywgcmVzcG9uc2U6IHJlc3VsdCB9KTtcbiAgfSBjYXRjaCAoZXJyb3I6IGFueSkge1xuICAgIHJlcS5sb2dnZXIuZXJyb3IoZXJyb3IpO1xuICAgIHJlcy5zdGF0dXMoNTAwKS5qc29uKHtcbiAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgIG1lc3NhZ2U6IGVycm9yPy5tZXNzYWdlIHx8IFN0cmluZyhlcnJvciksXG4gICAgfSk7XG4gIH1cbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIGRvd25sb2FkTWVkaWFCeU1lc3NhZ2UocmVxOiBSZXF1ZXN0LCByZXM6IFJlc3BvbnNlKSB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiTWVzc2FnZXNcIl1cbiAgICAgI3N3YWdnZXIuYXV0b0JvZHk9ZmFsc2VcbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAnZG93bmxvYWRNZWRpYWJ5TWVzc2FnZSdcbiAgICAgI3N3YWdnZXIuc2VjdXJpdHkgPSBbe1xuICAgICAgICAgICAgXCJiZWFyZXJBdXRoXCI6IFtdXG4gICAgIH1dXG4gICAgICNzd2FnZ2VyLnBhcmFtZXRlcnNbXCJzZXNzaW9uXCJdID0ge1xuICAgICAgc2NoZW1hOiAnTkVSRFdIQVRTX0FNRVJJQ0EnXG4gICAgIH1cbiAgICAgI3N3YWdnZXIucmVxdWVzdEJvZHkgPSB7XG4gICAgICByZXF1aXJlZDogdHJ1ZSxcbiAgICAgIFwiQGNvbnRlbnRcIjoge1xuICAgICAgICBcImFwcGxpY2F0aW9uL2pzb25cIjoge1xuICAgICAgICAgIHNjaGVtYToge1xuICAgICAgICAgICAgdHlwZTogXCJvYmplY3RcIixcbiAgICAgICAgICAgIHByb3BlcnRpZXM6IHtcbiAgICAgICAgICAgICAgbWVzc2FnZUlkOiB7IHR5cGU6IFwic3RyaW5nXCIgfSxcbiAgICAgICAgICAgIH1cbiAgICAgICAgICB9LFxuICAgICAgICAgIGV4YW1wbGU6IHtcbiAgICAgICAgICAgIG1lc3NhZ2VJZDogJzxtZXNzYWdlSWQ+J1xuICAgICAgICAgIH1cbiAgICAgICAgfVxuICAgICAgfVxuICAgICB9XG4gICAqL1xuICBjb25zdCBjbGllbnQgPSByZXEuY2xpZW50O1xuICBjb25zdCB7IG1lc3NhZ2VJZCB9ID0gcmVxLmJvZHk7XG5cbiAgaWYgKCFjbGllbnQgfHwgdHlwZW9mIGNsaWVudC5nZXRNZXNzYWdlQnlJZCAhPT0gJ2Z1bmN0aW9uJykge1xuICAgIHJldHVybiByZXMuc3RhdHVzKDQwMCkuanNvbih7XG4gICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICBtZXNzYWdlOiAnVGhlIFdoYXRzQXBwIHNlc3Npb24gaXMgbm90IGFjdGl2ZS4nLFxuICAgIH0pO1xuICB9XG5cbiAgbGV0IG1lc3NhZ2U7XG5cbiAgdHJ5IHtcbiAgICBpZiAoIW1lc3NhZ2VJZC5pc01lZGlhIHx8ICFtZXNzYWdlSWQudHlwZSkge1xuICAgICAgbWVzc2FnZSA9IGF3YWl0IGNsaWVudC5nZXRNZXNzYWdlQnlJZChtZXNzYWdlSWQpO1xuICAgIH0gZWxzZSB7XG4gICAgICBtZXNzYWdlID0gbWVzc2FnZUlkO1xuICAgIH1cblxuICAgIGlmICghbWVzc2FnZSlcbiAgICAgIHJlcy5zdGF0dXMoNDAwKS5qc29uKHtcbiAgICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgICBtZXNzYWdlOiAnTWVzc2FnZSBub3QgZm91bmQnLFxuICAgICAgfSk7XG5cbiAgICBpZiAoIShtZXNzYWdlWydtaW1ldHlwZSddIHx8IG1lc3NhZ2UuaXNNZWRpYSB8fCBtZXNzYWdlLmlzTU1TKSlcbiAgICAgIHJlcy5zdGF0dXMoNDAwKS5qc29uKHtcbiAgICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgICBtZXNzYWdlOiAnTWVzc2FnZSBkb2VzIG5vdCBjb250YWluIG1lZGlhJyxcbiAgICAgIH0pO1xuXG4gICAgY29uc3QgYnVmZmVyID0gYXdhaXQgY2xpZW50LmRlY3J5cHRGaWxlKG1lc3NhZ2UpO1xuXG4gICAgcmVzXG4gICAgICAuc3RhdHVzKDIwMClcbiAgICAgIC5qc29uKHsgYmFzZTY0OiBidWZmZXIudG9TdHJpbmcoJ2Jhc2U2NCcpLCBtaW1ldHlwZTogbWVzc2FnZS5taW1ldHlwZSB9KTtcbiAgfSBjYXRjaCAoZSkge1xuICAgIHJlcS5sb2dnZXIuZXJyb3IoZSk7XG4gICAgcmVzLnN0YXR1cyg0MDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgbWVzc2FnZTogJ0RlY3J5cHQgZmlsZSBlcnJvcicsXG4gICAgICBlcnJvcjogZSxcbiAgICB9KTtcbiAgfVxufVxuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24gZ2V0TWVkaWFCeU1lc3NhZ2UocmVxOiBSZXF1ZXN0LCByZXM6IFJlc3BvbnNlKSB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiTWVzc2FnZXNcIl1cbiAgICAgI3N3YWdnZXIuYXV0b0JvZHk9ZmFsc2VcbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAnZ2V0TWVkaWFCeU1lc3NhZ2UnXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAgICNzd2FnZ2VyLnBhcmFtZXRlcnNbXCJzZXNzaW9uXCJdID0ge1xuICAgICAgc2NoZW1hOiAnbWVzc2FnZUlkJ1xuICAgICB9XG4gICAqL1xuICBjb25zdCBjbGllbnQgPSByZXEuY2xpZW50O1xuICBjb25zdCB7IG1lc3NhZ2VJZCB9ID0gcmVxLnBhcmFtcztcblxuICBpZiAoIWNsaWVudCB8fCB0eXBlb2YgY2xpZW50LmdldE1lc3NhZ2VCeUlkICE9PSAnZnVuY3Rpb24nKSB7XG4gICAgcmV0dXJuIHJlcy5zdGF0dXMoNDAwKS5qc29uKHtcbiAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgIG1lc3NhZ2U6ICdUaGUgV2hhdHNBcHAgc2Vzc2lvbiBpcyBub3QgYWN0aXZlLicsXG4gICAgfSk7XG4gIH1cblxuICB0cnkge1xuICAgIGxldCBtZXNzYWdlOiBhbnkgPSBudWxsO1xuXG4gICAgLy8gSWYgZGV0YWlscyBhcmUgcHJvdmlkZWQgaW4gdGhlIHJlcXVlc3QgYm9keSAoZS5nLiBQT1NUIHJlcXVlc3Qgd2l0aCBsb2NhbCBjYWNoZSBBTkQgZG93bmxvYWQgVVJMKSwgdXNlIHRoZW0gZGlyZWN0bHkuXG4gICAgY29uc3QgaGFzRG93bmxvYWRVcmwgPSByZXEuYm9keSAmJiAocmVxLmJvZHkuY2xpZW50VXJsIHx8IHJlcS5ib2R5LmRlcHJlY2F0ZWRNbXMzVXJsIHx8IHJlcS5ib2R5LnVybCB8fCByZXEuYm9keS5kaXJlY3RQYXRoKTtcbiAgICBpZiAocmVxLmJvZHkgJiYgcmVxLmJvZHkubWVkaWFLZXkgJiYgaGFzRG93bmxvYWRVcmwpIHtcbiAgICAgIHJlcS5sb2dnZXIuaW5mbyhgUmVjZWl2ZWQgZnVsbCBkZWNyeXB0aW9uIGtleXMgYW5kIGRvd25sb2FkIFVSTCBpbiBib2R5IGZvciBtZXNzYWdlICR7bWVzc2FnZUlkfS4gQnlwYXNzaW5nIFB1cHBldGVlciBsb29rdXAuYCk7XG4gICAgICBtZXNzYWdlID0gcmVxLmJvZHk7XG4gICAgICBpZiAoIW1lc3NhZ2UuY2xpZW50VXJsICYmIChtZXNzYWdlLnVybCB8fCBtZXNzYWdlLmRlcHJlY2F0ZWRNbXMzVXJsKSkge1xuICAgICAgICBtZXNzYWdlLmNsaWVudFVybCA9IG1lc3NhZ2UuY2xpZW50VXJsIHx8IG1lc3NhZ2UudXJsIHx8IG1lc3NhZ2UuZGVwcmVjYXRlZE1tczNVcmw7XG4gICAgICB9XG4gICAgICAvLyBOb3JtYWxpc2Uga2V5IHR5cGVzIGFuZCBzdHJ1Y3R1cmVzIGlmIG5lZWRlZCBieSBkZWNyeXB0RmlsZVxuICAgICAgaWYgKHR5cGVvZiBtZXNzYWdlLm1lZGlhS2V5ID09PSAnb2JqZWN0JyAmJiBtZXNzYWdlLm1lZGlhS2V5LmRhdGEpIHtcbiAgICAgICAgbWVzc2FnZS5tZWRpYUtleSA9IEJ1ZmZlci5mcm9tKG1lc3NhZ2UubWVkaWFLZXkuZGF0YSk7XG4gICAgICB9IGVsc2UgaWYgKHR5cGVvZiBtZXNzYWdlLm1lZGlhS2V5ID09PSAnc3RyaW5nJykge1xuICAgICAgICBtZXNzYWdlLm1lZGlhS2V5ID0gQnVmZmVyLmZyb20obWVzc2FnZS5tZWRpYUtleSwgJ2Jhc2U2NCcpO1xuICAgICAgfVxuICAgIH0gZWxzZSB7XG4gICAgICB0cnkge1xuICAgICAgICBtZXNzYWdlID0gYXdhaXQgY2xpZW50LmdldE1lc3NhZ2VCeUlkKG1lc3NhZ2VJZCk7XG4gICAgICB9IGNhdGNoIChlcnI6IGFueSkge1xuICAgICAgICByZXEubG9nZ2VyLndhcm4oYGNsaWVudC5nZXRNZXNzYWdlQnlJZCB0aHJldyBlcnJvcjogJHtlcnIubWVzc2FnZSB8fCBlcnJ9LiBUcnlpbmcgZmFsbGJhY2suLi5gKTtcbiAgICAgIH1cblxuICAgICAgLy8gRmFsbGJhY2s6IElmIG1lc3NhZ2UgaXMgbm90IGZvdW5kLCBpdCBtaWdodCBub3QgYmUgbG9hZGVkIGluIHRoZSBXaGF0c0FwcCBXZWIgY2FjaGUuXG4gICAgICAvLyBUcnkgdG8gcGFyc2UgdGhlIGNoYXRJZCBmcm9tIHRoZSBzZXJpYWxpemVkIG1lc3NhZ2VJZCAoZm9ybWF0OiBmcm9tTWVfY2hhdElkX21zZ0lkX3BhcnRpY2lwYW50KVxuICAgICAgLy8gYW5kIGxvYWQgZWFybGllciBtZXNzYWdlcyB0byBmb3JjZSBzeW5jIGl0LlxuICAgICAgaWYgKCFtZXNzYWdlICYmIG1lc3NhZ2VJZCkge1xuICAgICAgICBjb25zdCBwYXJ0cyA9IG1lc3NhZ2VJZC5zcGxpdCgnXycpO1xuICAgICAgICBpZiAocGFydHMubGVuZ3RoID49IDIpIHtcbiAgICAgICAgICBjb25zdCBjaGF0SWQgPSBwYXJ0c1sxXTsgLy8gZS5nLiAxMjAzNjM0MjA5NDgxMzQwNjVAZy51cyBvciBwaG9uZUBjLnVzXG4gICAgICAgICAgaWYgKGNoYXRJZCkge1xuICAgICAgICAgICAgcmVxLmxvZ2dlci5pbmZvKGBNZXNzYWdlICR7bWVzc2FnZUlkfSBub3QgZm91bmQgaW4gY2FjaGUuIEF0dGVtcHRpbmcgV1BQLmNoYXQuZmluZCAmIGxvYWRFYXJsaWVyTWVzc2FnZXMgZm9yICR7Y2hhdElkfWApO1xuICAgICAgICAgICAgdHJ5IHtcbiAgICAgICAgICAgICAgaWYgKGNsaWVudC5wYWdlICYmICFjbGllbnQucGFnZS5pc0Nsb3NlZCgpKSB7XG4gICAgICAgICAgICAgICAgbWVzc2FnZSA9IGF3YWl0IGNsaWVudC5wYWdlLmV2YWx1YXRlKGFzeW5jICh7IG1zZ0lkLCB0YXJnZXRDaGF0SWQgfSkgPT4ge1xuICAgICAgICAgICAgICAgICAgdHJ5IHtcbiAgICAgICAgICAgICAgICAgICAgY29uc3QgV1BQID0gKHdpbmRvdyBhcyBhbnkpLldQUDtcbiAgICAgICAgICAgICAgICAgICAgY29uc3QgU3RvcmUgPSAod2luZG93IGFzIGFueSkuU3RvcmU7XG5cbiAgICAgICAgICAgICAgICAgICAgLy8gSGVscGVyIDE6IENvbnZlcnQgc3RyaW5nIEpJRCB0byBXaWQgaWYgcG9zc2libGVcbiAgICAgICAgICAgICAgICAgICAgbGV0IHRhcmdldFdpZCA9IHRhcmdldENoYXRJZDtcbiAgICAgICAgICAgICAgICAgICAgaWYgKFdQUD8ud2hhdHNhcHA/LldpZEZhY3Rvcnk/LmNyZWF0ZSkge1xuICAgICAgICAgICAgICAgICAgICAgIHRyeSB7XG4gICAgICAgICAgICAgICAgICAgICAgICB0YXJnZXRXaWQgPSBXUFAud2hhdHNhcHAuV2lkRmFjdG9yeS5jcmVhdGUodGFyZ2V0Q2hhdElkKTtcbiAgICAgICAgICAgICAgICAgICAgICB9IGNhdGNoIChlKSB7fVxuICAgICAgICAgICAgICAgICAgICB9XG5cbiAgICAgICAgICAgICAgICAgICAgLy8gSGVscGVyIDI6IEVuc3VyZSBjaGF0IGlzIGxvYWRlZFxuICAgICAgICAgICAgICAgICAgICBpZiAoV1BQPy5jaGF0Py5maW5kKSB7XG4gICAgICAgICAgICAgICAgICAgICAgdHJ5IHsgYXdhaXQgV1BQLmNoYXQuZmluZCh0YXJnZXRDaGF0SWQpOyB9IGNhdGNoIChlKSB7fVxuICAgICAgICAgICAgICAgICAgICAgIHRyeSB7IGlmICh0YXJnZXRXaWQgIT09IHRhcmdldENoYXRJZCkgYXdhaXQgV1BQLmNoYXQuZmluZCh0YXJnZXRXaWQpOyB9IGNhdGNoIChlKSB7fVxuICAgICAgICAgICAgICAgICAgICAgIHRyeSB7XG4gICAgICAgICAgICAgICAgICAgICAgICBpZiAodGFyZ2V0Q2hhdElkLmluY2x1ZGVzKCdAYy51cycpKSB7XG4gICAgICAgICAgICAgICAgICAgICAgICAgIGF3YWl0IFdQUC5jaGF0LmZpbmQodGFyZ2V0Q2hhdElkLnJlcGxhY2UoL0BjXFwudXMvZywgJ0BzLndoYXRzYXBwLm5ldCcpKTtcbiAgICAgICAgICAgICAgICAgICAgICAgIH1cbiAgICAgICAgICAgICAgICAgICAgICB9IGNhdGNoIChlKSB7fVxuICAgICAgICAgICAgICAgICAgICB9XG5cbiAgICAgICAgICAgICAgICAgICAgaWYgKFdQUD8uY2hhdD8ubG9hZEVhcmxpZXJNZXNzYWdlcykge1xuICAgICAgICAgICAgICAgICAgICAgIHRyeSB7IGF3YWl0IFdQUC5jaGF0LmxvYWRFYXJsaWVyTWVzc2FnZXModGFyZ2V0Q2hhdElkKTsgfSBjYXRjaCAoZSkge31cbiAgICAgICAgICAgICAgICAgICAgfVxuXG4gICAgICAgICAgICAgICAgICAgIC8vIEhlbHBlciAzOiBEZWVwIHNlYXJjaCBtZXNzYWdlXG4gICAgICAgICAgICAgICAgICAgIGNvbnN0IGdldE1zZ1NhZmUgPSBhc3luYyAobUlkOiBzdHJpbmcpID0+IHtcbiAgICAgICAgICAgICAgICAgICAgICBpZiAoIW1JZCkgcmV0dXJuIG51bGw7XG4gICAgICAgICAgICAgICAgICAgICAgaWYgKFdQUD8uY2hhdD8uZ2V0TWVzc2FnZUJ5SWQpIHtcbiAgICAgICAgICAgICAgICAgICAgICAgIHRyeSB7XG4gICAgICAgICAgICAgICAgICAgICAgICAgIGNvbnN0IG0gPSBhd2FpdCBXUFAuY2hhdC5nZXRNZXNzYWdlQnlJZChtSWQpO1xuICAgICAgICAgICAgICAgICAgICAgICAgICBpZiAobSkgcmV0dXJuIG07XG4gICAgICAgICAgICAgICAgICAgICAgICB9IGNhdGNoIChlKSB7fVxuICAgICAgICAgICAgICAgICAgICAgICAgdHJ5IHtcbiAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgKG1JZC5pbmNsdWRlcygnQGMudXMnKSkge1xuICAgICAgICAgICAgICAgICAgICAgICAgICAgIGNvbnN0IG0gPSBhd2FpdCBXUFAuY2hhdC5nZXRNZXNzYWdlQnlJZChtSWQucmVwbGFjZSgvQGNcXC51cy9nLCAnQHMud2hhdHNhcHAubmV0JykpO1xuICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIChtKSByZXR1cm4gbTtcbiAgICAgICAgICAgICAgICAgICAgICAgICAgfSBlbHNlIGlmIChtSWQuaW5jbHVkZXMoJ0BzLndoYXRzYXBwLm5ldCcpKSB7XG4gICAgICAgICAgICAgICAgICAgICAgICAgICAgY29uc3QgbSA9IGF3YWl0IFdQUC5jaGF0LmdldE1lc3NhZ2VCeUlkKG1JZC5yZXBsYWNlKC9Ac1xcLndoYXRzYXBwXFwubmV0L2csICdAYy51cycpKTtcbiAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiAobSkgcmV0dXJuIG07XG4gICAgICAgICAgICAgICAgICAgICAgICAgIH1cbiAgICAgICAgICAgICAgICAgICAgICAgIH0gY2F0Y2ggKGUpIHt9XG4gICAgICAgICAgICAgICAgICAgICAgfVxuXG4gICAgICAgICAgICAgICAgICAgICAgLy8gRmFsbGJhY2s6IHNlYXJjaCBTdG9yZS5Nc2cubW9kZWxzIGJ5IHJhdyBtZXNzYWdlIElEXG4gICAgICAgICAgICAgICAgICAgICAgY29uc3QgcGFydHMgPSBtSWQuc3BsaXQoJ18nKTtcbiAgICAgICAgICAgICAgICAgICAgICBjb25zdCByYXdJZCA9IHBhcnRzLmxlbmd0aCA+IDIgPyBwYXJ0c1syXSA6IG1JZDtcbiAgICAgICAgICAgICAgICAgICAgICBpZiAoU3RvcmU/Lk1zZz8ubW9kZWxzKSB7XG4gICAgICAgICAgICAgICAgICAgICAgICBjb25zdCBmb3VuZCA9IFN0b3JlLk1zZy5tb2RlbHMuZmluZCgoaXRlbTogYW55KSA9PiB7XG4gICAgICAgICAgICAgICAgICAgICAgICAgIGlmICghaXRlbSB8fCAhaXRlbS5pZCkgcmV0dXJuIGZhbHNlO1xuICAgICAgICAgICAgICAgICAgICAgICAgICBjb25zdCBzZXIgPSBpdGVtLmlkLl9zZXJpYWxpemVkIHx8ICcnO1xuICAgICAgICAgICAgICAgICAgICAgICAgICBjb25zdCBpdGVtSWQgPSBpdGVtLmlkLmlkIHx8ICcnO1xuICAgICAgICAgICAgICAgICAgICAgICAgICByZXR1cm4gaXRlbUlkID09PSByYXdJZCB8fCBzZXIgPT09IG1JZCB8fCAocmF3SWQgJiYgc2VyLmluY2x1ZGVzKHJhd0lkKSk7XG4gICAgICAgICAgICAgICAgICAgICAgICB9KTtcbiAgICAgICAgICAgICAgICAgICAgICAgIGlmIChmb3VuZCkgcmV0dXJuIGZvdW5kO1xuICAgICAgICAgICAgICAgICAgICAgIH1cbiAgICAgICAgICAgICAgICAgICAgICByZXR1cm4gbnVsbDtcbiAgICAgICAgICAgICAgICAgICAgfTtcblxuICAgICAgICAgICAgICAgICAgICByZXR1cm4gYXdhaXQgZ2V0TXNnU2FmZShtc2dJZCk7XG4gICAgICAgICAgICAgICAgICB9IGNhdGNoIChlKSB7XG4gICAgICAgICAgICAgICAgICAgIGNvbnNvbGUubG9nKGBbYnJvd3Nlci1ldmFsdWF0ZSBnZXRNZWRpYUJ5TWVzc2FnZSBmYWxsYmFjayBlcnJvcl06ICR7ZX1gKTtcbiAgICAgICAgICAgICAgICAgICAgcmV0dXJuIG51bGw7XG4gICAgICAgICAgICAgICAgICB9XG4gICAgICAgICAgICAgICAgfSwgeyBtc2dJZDogbWVzc2FnZUlkLCB0YXJnZXRDaGF0SWQ6IGNoYXRJZCB9KTtcbiAgICAgICAgICAgICAgfVxuXG4gICAgICAgICAgICAgIC8vIFNlY29uZCBjaGVjayBpZiBldmFsdWF0ZSByZXR1cm5lZCBudWxsIGJ1dCBjbGllbnQuZ2V0TWVzc2FnZUJ5SWQgbWlnaHQgd29yayBub3dcbiAgICAgICAgICAgICAgaWYgKCFtZXNzYWdlICYmIHR5cGVvZiBjbGllbnQuZ2V0TWVzc2FnZUJ5SWQgPT09ICdmdW5jdGlvbicpIHtcbiAgICAgICAgICAgICAgICB0cnkge1xuICAgICAgICAgICAgICAgICAgbWVzc2FnZSA9IGF3YWl0IGNsaWVudC5nZXRNZXNzYWdlQnlJZChtZXNzYWdlSWQpO1xuICAgICAgICAgICAgICAgIH0gY2F0Y2ggKHJldHJ5RXJyOiBhbnkpIHtcbiAgICAgICAgICAgICAgICAgIHJlcS5sb2dnZXIuZXJyb3IoYFJldHJ5IGdldE1lc3NhZ2VCeUlkIGZhaWxlZDogJHtyZXRyeUVyci5tZXNzYWdlIHx8IHJldHJ5RXJyfWApO1xuICAgICAgICAgICAgICAgIH1cbiAgICAgICAgICAgICAgfVxuICAgICAgICAgICAgfSBjYXRjaCAobG9hZEVycikge1xuICAgICAgICAgICAgICByZXEubG9nZ2VyLmVycm9yKGBFcnJvciBleGVjdXRpbmcgZ2V0TWVkaWFCeU1lc3NhZ2UgZmFsbGJhY2s6ICR7bG9hZEVycn1gKTtcbiAgICAgICAgICAgIH1cbiAgICAgICAgICB9XG4gICAgICAgIH1cbiAgICAgIH1cbiAgICB9XG5cbiAgICBpZiAoIW1lc3NhZ2UpIHtcbiAgICAgIHJldHVybiByZXMuc3RhdHVzKDQwMCkuanNvbih7XG4gICAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgICAgbWVzc2FnZTogYE1lc3NhZ2UgJHttZXNzYWdlSWR9IG5vdCBmb3VuZGAsXG4gICAgICB9KTtcbiAgICB9XG5cbiAgICAvLyBFbnN1cmUgY2xpZW50IGJyb3dzZXIgY29udGV4dCBpcyBhbGl2ZVxuICAgIGlmIChjbGllbnQucGFnZSAmJiBjbGllbnQucGFnZS5pc0Nsb3NlZCgpKSB7XG4gICAgICByZXEubG9nZ2VyLndhcm4oYEJyb3dzZXIgcGFnZSBpcyBjbG9zZWQgZm9yIHNlc3Npb24gd2hlbiBkb3dubG9hZGluZyBtZWRpYSAke21lc3NhZ2VJZH1gKTtcbiAgICAgIHJldHVybiByZXMuc3RhdHVzKDUwMykuanNvbih7XG4gICAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgICAgbWVzc2FnZTogJ0Jyb3dzZXIgc2Vzc2lvbiBpcyBjbG9zZWQgb3IgcmUtY29ubmVjdGluZycsXG4gICAgICB9KTtcbiAgICB9XG5cbiAgICAvLyBFbnN1cmUgaXQgY29udGFpbnMgbWVkaWEgcHJvcGVydGllcyBvciBoYXMgbWltZXR5cGVcbiAgICBjb25zdCBtZWRpYVVybCA9IG1lc3NhZ2UuY2xpZW50VXJsIHx8IG1lc3NhZ2UuZGVwcmVjYXRlZE1tczNVcmw7XG4gICAgaWYgKCFtZWRpYVVybCkge1xuICAgICAgaWYgKHR5cGVvZiAoY2xpZW50IGFzIGFueSkuZG93bmxvYWRNZWRpYSA9PT0gJ2Z1bmN0aW9uJyAmJiBjbGllbnQucGFnZSAmJiAhY2xpZW50LnBhZ2UuaXNDbG9zZWQoKSkge1xuICAgICAgICByZXEubG9nZ2VyLmluZm8oYE1lc3NhZ2UgJHttZXNzYWdlSWR9IGRvZXMgbm90IGhhdmUgY2xpZW50VXJsLiBUcnlpbmcgY2xpZW50LmRvd25sb2FkTWVkaWEgd2l0aCA1cyB0aW1lb3V0Li4uYCk7XG4gICAgICAgIHRyeSB7XG4gICAgICAgICAgbGV0IHRpbWVyOiBhbnk7XG4gICAgICAgICAgY29uc3QgZG93bmxvYWRQcm9taXNlID0gKGNsaWVudCBhcyBhbnkpLmRvd25sb2FkTWVkaWEobWVzc2FnZUlkKS5jYXRjaCgoZXJyOiBhbnkpID0+IHtcbiAgICAgICAgICAgIHJlcS5sb2dnZXIud2FybihgY2xpZW50LmRvd25sb2FkTWVkaWEgY2F1Z2h0IGlubmVyIGVycm9yOiAke2Vycn1gKTtcbiAgICAgICAgICAgIHJldHVybiBudWxsO1xuICAgICAgICAgIH0pLmZpbmFsbHkoKCkgPT4ge1xuICAgICAgICAgICAgaWYgKHRpbWVyKSBjbGVhclRpbWVvdXQodGltZXIpO1xuICAgICAgICAgIH0pO1xuICAgICAgICAgIGNvbnN0IHRpbWVvdXRQcm9taXNlID0gbmV3IFByb21pc2U8bnVsbD4oKHJlc29sdmUpID0+IHtcbiAgICAgICAgICAgIHRpbWVyID0gc2V0VGltZW91dCgoKSA9PiB7XG4gICAgICAgICAgICAgIHJlcS5sb2dnZXIud2FybihgVGltZW91dCA1MDAwbXMgcmVhY2hlZCBmb3IgY2xpZW50LmRvd25sb2FkTWVkaWEgKCR7bWVzc2FnZUlkfSlgKTtcbiAgICAgICAgICAgICAgcmVzb2x2ZShudWxsKTtcbiAgICAgICAgICAgIH0sIDUwMDApO1xuICAgICAgICAgIH0pO1xuICAgICAgICAgIGxldCBiYXNlNjQ6IHN0cmluZyB8IG51bGwgPSBhd2FpdCBQcm9taXNlLnJhY2UoW2Rvd25sb2FkUHJvbWlzZSwgdGltZW91dFByb21pc2VdKTtcbiAgICAgICAgICBpZiAoYmFzZTY0KSB7XG4gICAgICAgICAgICBsZXQgbWltZXR5cGUgPSBtZXNzYWdlLm1pbWV0eXBlIHx8ICdhdWRpby9vZ2cnO1xuICAgICAgICAgICAgaWYgKGJhc2U2NC5zdGFydHNXaXRoKCdkYXRhOicpKSB7XG4gICAgICAgICAgICAgIGNvbnN0IG1hdGNoZXMgPSBiYXNlNjQubWF0Y2goL15kYXRhOiguKj8pO2Jhc2U2NCwoLiopJC8pO1xuICAgICAgICAgICAgICBpZiAobWF0Y2hlcykge1xuICAgICAgICAgICAgICAgIG1pbWV0eXBlID0gbWF0Y2hlc1sxXTtcbiAgICAgICAgICAgICAgICBiYXNlNjQgPSBtYXRjaGVzWzJdO1xuICAgICAgICAgICAgICB9XG4gICAgICAgICAgICB9XG4gICAgICAgICAgICByZXR1cm4gcmVzLnN0YXR1cygyMDApLmpzb24oeyBiYXNlNjQsIG1pbWV0eXBlIH0pO1xuICAgICAgICAgIH1cbiAgICAgICAgfSBjYXRjaCAoZG93bmxvYWRFcnIpIHtcbiAgICAgICAgICByZXEubG9nZ2VyLmVycm9yKGBFcnJvciBpbiBjbGllbnQuZG93bmxvYWRNZWRpYSBmYWxsYmFjazogJHtkb3dubG9hZEVycn1gKTtcbiAgICAgICAgfVxuICAgICAgfVxuICAgICAgcmV0dXJuIHJlcy5zdGF0dXMoNDAwKS5qc29uKHtcbiAgICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgICBtZXNzYWdlOiAnTWVzc2FnZSBkb2VzIG5vdCBjb250YWluIG1lZGlhIGRvd25sb2FkIFVSTCcsXG4gICAgICB9KTtcbiAgICB9XG5cbiAgICB0cnkge1xuICAgICAgY29uc3QgYnVmZmVyID0gYXdhaXQgY2xpZW50LmRlY3J5cHRGaWxlKG1lc3NhZ2UpO1xuICAgICAgcmVzXG4gICAgICAgIC5zdGF0dXMoMjAwKVxuICAgICAgICAuanNvbih7IGJhc2U2NDogYnVmZmVyLnRvU3RyaW5nKCdiYXNlNjQnKSwgbWltZXR5cGU6IG1lc3NhZ2UubWltZXR5cGUgfHwgJ2F1ZGlvL29nZycgfSk7XG4gICAgfSBjYXRjaCAoZGVjcnlwdEVycikge1xuICAgICAgcmVxLmxvZ2dlci5lcnJvcihgZGVjcnlwdEZpbGUgZmFpbGVkLCB0cnlpbmcgYnJvd3Nlci1zaWRlIHJlY292ZXJ5OiAke2RlY3J5cHRFcnJ9YCk7XG4gICAgICBcbiAgICAgIC8vIEF0dGVtcHQgYnJvd3Nlci1zaWRlIHJlY292ZXJ5OiBmZXRjaCB0aGUgbWVzc2FnZSBmcmVzaCBmcm9tIFdoYXRzQXBwIFdlYiB0byBnZXQgdXBkYXRlZCBDRE4gVVJMc1xuICAgICAgbGV0IGZyZXNoTWVzc2FnZTogYW55ID0gbnVsbDtcbiAgICAgIGlmIChjbGllbnQucGFnZSAmJiAhY2xpZW50LnBhZ2UuaXNDbG9zZWQoKSkge1xuICAgICAgICB0cnkge1xuICAgICAgICAgIGZyZXNoTWVzc2FnZSA9IGF3YWl0IGNsaWVudC5nZXRNZXNzYWdlQnlJZChtZXNzYWdlSWQpO1xuICAgICAgICB9IGNhdGNoIChlcnIpIHt9XG5cbiAgICAgICAgaWYgKCFmcmVzaE1lc3NhZ2UgJiYgbWVzc2FnZUlkKSB7XG4gICAgICAgICAgY29uc3QgcGFydHMgPSBtZXNzYWdlSWQuc3BsaXQoJ18nKTtcbiAgICAgICAgICBpZiAocGFydHMubGVuZ3RoID49IDIpIHtcbiAgICAgICAgICAgIGNvbnN0IGNoYXRJZCA9IHBhcnRzWzFdO1xuICAgICAgICAgICAgaWYgKGNoYXRJZCAmJiB0eXBlb2YgY2xpZW50LmxvYWRFYXJsaWVyTWVzc2FnZXMgPT09ICdmdW5jdGlvbicpIHtcbiAgICAgICAgICAgICAgdHJ5IHtcbiAgICAgICAgICAgICAgICBhd2FpdCBjbGllbnQubG9hZEVhcmxpZXJNZXNzYWdlcyhjaGF0SWQpO1xuICAgICAgICAgICAgICAgIGZyZXNoTWVzc2FnZSA9IGF3YWl0IGNsaWVudC5nZXRNZXNzYWdlQnlJZChtZXNzYWdlSWQpO1xuICAgICAgICAgICAgICB9IGNhdGNoIChlcnIpIHt9XG4gICAgICAgICAgICB9XG4gICAgICAgICAgfVxuICAgICAgICB9XG4gICAgICB9XG5cbiAgICAgIGlmIChmcmVzaE1lc3NhZ2UpIHtcbiAgICAgICAgdHJ5IHtcbiAgICAgICAgICByZXEubG9nZ2VyLmluZm8oYEZvdW5kIGZyZXNoIG1lc3NhZ2UgaW4gYnJvd3NlciBmb3IgJHttZXNzYWdlSWR9LCBhdHRlbXB0aW5nIGRlY3J5cHRpb24uLi5gKTtcbiAgICAgICAgICBjb25zdCBidWZmZXIgPSBhd2FpdCBjbGllbnQuZGVjcnlwdEZpbGUoZnJlc2hNZXNzYWdlKTtcbiAgICAgICAgICByZXR1cm4gcmVzLnN0YXR1cygyMDApLmpzb24oe1xuICAgICAgICAgICAgYmFzZTY0OiBidWZmZXIudG9TdHJpbmcoJ2Jhc2U2NCcpLFxuICAgICAgICAgICAgbWltZXR5cGU6IGZyZXNoTWVzc2FnZS5taW1ldHlwZSB8fCAnYXVkaW8vb2dnJ1xuICAgICAgICAgIH0pO1xuICAgICAgICB9IGNhdGNoIChmcmVzaERlY3J5cHRFcnIpIHtcbiAgICAgICAgICByZXEubG9nZ2VyLmVycm9yKGBEZWNyeXB0aW9uIG9mIGZyZXNoIGJyb3dzZXIgbWVzc2FnZSBmYWlsZWQ6ICR7ZnJlc2hEZWNyeXB0RXJyfWApO1xuICAgICAgICB9XG4gICAgICB9XG5cbiAgICAgIC8vIEZpbmFsIGZhbGxiYWNrIHRvIFdQUENvbm5lY3QncyBkb3dubG9hZE1lZGlhXG4gICAgICBpZiAodHlwZW9mIChjbGllbnQgYXMgYW55KS5kb3dubG9hZE1lZGlhID09PSAnZnVuY3Rpb24nICYmIGNsaWVudC5wYWdlICYmICFjbGllbnQucGFnZS5pc0Nsb3NlZCgpKSB7XG4gICAgICAgIHRyeSB7XG4gICAgICAgICAgbGV0IHRpbWVyOiBhbnk7XG4gICAgICAgICAgY29uc3QgZG93bmxvYWRQcm9taXNlID0gKGNsaWVudCBhcyBhbnkpLmRvd25sb2FkTWVkaWEobWVzc2FnZUlkKS5jYXRjaCgoZXJyOiBhbnkpID0+IHtcbiAgICAgICAgICAgIHJlcS5sb2dnZXIud2FybihgY2xpZW50LmRvd25sb2FkTWVkaWEgY2F1Z2h0IGlubmVyIGVycm9yOiAke2Vycn1gKTtcbiAgICAgICAgICAgIHJldHVybiBudWxsO1xuICAgICAgICAgIH0pLmZpbmFsbHkoKCkgPT4ge1xuICAgICAgICAgICAgaWYgKHRpbWVyKSBjbGVhclRpbWVvdXQodGltZXIpO1xuICAgICAgICAgIH0pO1xuICAgICAgICAgIGNvbnN0IHRpbWVvdXRQcm9taXNlID0gbmV3IFByb21pc2U8bnVsbD4oKHJlc29sdmUpID0+IHtcbiAgICAgICAgICAgIHRpbWVyID0gc2V0VGltZW91dCgoKSA9PiB7XG4gICAgICAgICAgICAgIHJlcS5sb2dnZXIud2FybihgVGltZW91dCA1MDAwbXMgcmVhY2hlZCBmb3IgY2xpZW50LmRvd25sb2FkTWVkaWEgKCR7bWVzc2FnZUlkfSlgKTtcbiAgICAgICAgICAgICAgcmVzb2x2ZShudWxsKTtcbiAgICAgICAgICAgIH0sIDUwMDApO1xuICAgICAgICAgIH0pO1xuICAgICAgICAgIGxldCBiYXNlNjQ6IHN0cmluZyB8IG51bGwgPSBhd2FpdCBQcm9taXNlLnJhY2UoW2Rvd25sb2FkUHJvbWlzZSwgdGltZW91dFByb21pc2VdKTtcbiAgICAgICAgICBpZiAoYmFzZTY0KSB7XG4gICAgICAgICAgICBsZXQgbWltZXR5cGUgPSAoZnJlc2hNZXNzYWdlIHx8IG1lc3NhZ2UpLm1pbWV0eXBlIHx8ICdhdWRpby9vZ2cnO1xuICAgICAgICAgICAgaWYgKGJhc2U2NC5zdGFydHNXaXRoKCdkYXRhOicpKSB7XG4gICAgICAgICAgICAgIGNvbnN0IG1hdGNoZXMgPSBiYXNlNjQubWF0Y2goL15kYXRhOiguKj8pO2Jhc2U2NCwoLiopJC8pO1xuICAgICAgICAgICAgICBpZiAobWF0Y2hlcykge1xuICAgICAgICAgICAgICAgIG1pbWV0eXBlID0gbWF0Y2hlc1sxXTtcbiAgICAgICAgICAgICAgICBiYXNlNjQgPSBtYXRjaGVzWzJdO1xuICAgICAgICAgICAgICB9XG4gICAgICAgICAgICB9XG4gICAgICAgICAgICByZXR1cm4gcmVzLnN0YXR1cygyMDApLmpzb24oeyBiYXNlNjQsIG1pbWV0eXBlIH0pO1xuICAgICAgICAgIH1cbiAgICAgICAgfSBjYXRjaCAoZG93bmxvYWRFcnIpIHtcbiAgICAgICAgICByZXEubG9nZ2VyLmVycm9yKGBFcnJvciBpbiBjbGllbnQuZG93bmxvYWRNZWRpYSBmYWxsYmFjayBhZnRlciBkZWNyeXB0aW9uIGVycm9yOiAke2Rvd25sb2FkRXJyfWApO1xuICAgICAgICB9XG4gICAgICB9XG4gICAgICB0aHJvdyBkZWNyeXB0RXJyOyAvLyByZXRocm93IHRvIHRyaWdnZXIgdGhlIDUwMCBibG9jayBpZiBib3RoIGZhaWxlZFxuICAgIH1cbiAgfSBjYXRjaCAoZXgpIHtcbiAgICByZXEubG9nZ2VyLmVycm9yKGV4KTtcbiAgICByZXMuc3RhdHVzKDUwMCkuanNvbih7XG4gICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICBtZXNzYWdlOiAnRmFpbGVkIHRvIGRlY3J5cHQgZmlsZScsXG4gICAgICBlcnJvcjogZXggaW5zdGFuY2VvZiBFcnJvciA/IGV4Lm1lc3NhZ2UgOiBleCxcbiAgICB9KTtcbiAgfVxufVxuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24gZ2V0U2Vzc2lvblN0YXRlKHJlcTogUmVxdWVzdCwgcmVzOiBSZXNwb25zZSkge1xuICAvKipcbiAgICAgI3N3YWdnZXIudGFncyA9IFtcIkF1dGhcIl1cbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAnZ2V0U2Vzc2lvblN0YXRlJ1xuICAgICAjc3dhZ2dlci5zdW1tYXJ5ID0gJ1JldHJpZXZlIHN0YXR1cyBvZiBhIHNlc3Npb24nXG4gICAgICNzd2FnZ2VyLmF1dG9Cb2R5ID0gZmFsc2VcbiAgICAgI3N3YWdnZXIuc2VjdXJpdHkgPSBbe1xuICAgICAgICAgICAgXCJiZWFyZXJBdXRoXCI6IFtdXG4gICAgIH1dXG4gICAgICNzd2FnZ2VyLnBhcmFtZXRlcnNbXCJzZXNzaW9uXCJdID0ge1xuICAgICAgc2NoZW1hOiAnTkVSRFdIQVRTX0FNRVJJQ0EnXG4gICAgIH1cbiAgICovXG4gIHRyeSB7XG4gICAgY29uc3QgeyB3YWl0UXJDb2RlID0gZmFsc2UgfSA9IHJlcS5ib2R5O1xuICAgIGNvbnN0IGNsaWVudCA9IHJlcS5jbGllbnQ7XG4gICAgY29uc3QgcXIgPVxuICAgICAgY2xpZW50Py51cmxjb2RlICE9IG51bGwgJiYgY2xpZW50Py51cmxjb2RlICE9ICcnXG4gICAgICAgID8gYXdhaXQgUVJDb2RlLnRvRGF0YVVSTChjbGllbnQudXJsY29kZSlcbiAgICAgICAgOiBudWxsO1xuXG4gICAgaWYgKChjbGllbnQgPT0gbnVsbCB8fCBjbGllbnQuc3RhdHVzID09IG51bGwpICYmICF3YWl0UXJDb2RlKVxuICAgICAgcmVzLnN0YXR1cygyMDApLmpzb24oeyBzdGF0dXM6ICdDTE9TRUQnLCBxcmNvZGU6IG51bGwgfSk7XG4gICAgZWxzZSBpZiAoY2xpZW50ICE9IG51bGwpXG4gICAgICByZXMuc3RhdHVzKDIwMCkuanNvbih7XG4gICAgICAgIHN0YXR1czogY2xpZW50LnN0YXR1cyxcbiAgICAgICAgcXJjb2RlOiBxcixcbiAgICAgICAgdXJsY29kZTogY2xpZW50LnVybGNvZGUsXG4gICAgICAgIHZlcnNpb246IHZlcnNpb24sXG4gICAgICB9KTtcbiAgfSBjYXRjaCAoZXgpIHtcbiAgICByZXEubG9nZ2VyLmVycm9yKGV4KTtcbiAgICByZXMuc3RhdHVzKDUwMCkuanNvbih7XG4gICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICBtZXNzYWdlOiAnVGhlIHNlc3Npb24gaXMgbm90IGFjdGl2ZScsXG4gICAgICBlcnJvcjogZXgsXG4gICAgfSk7XG4gIH1cbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIGdldFFyQ29kZShyZXE6IFJlcXVlc3QsIHJlczogUmVzcG9uc2UpIHtcbiAgLyoqXG4gICAqICNzd2FnZ2VyLnRhZ3MgPSBbXCJBdXRoXCJdXG4gICAgICNzd2FnZ2VyLmF1dG9Cb2R5PWZhbHNlXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ2dldFFyQ29kZSdcbiAgICAgI3N3YWdnZXIuc2VjdXJpdHkgPSBbe1xuICAgICAgICAgICAgXCJiZWFyZXJBdXRoXCI6IFtdXG4gICAgIH1dXG4gICAgICNzd2FnZ2VyLnBhcmFtZXRlcnNbXCJzZXNzaW9uXCJdID0ge1xuICAgICAgc2NoZW1hOiAnTkVSRFdIQVRTX0FNRVJJQ0EnXG4gICAgIH1cbiAgICovXG4gIHRyeSB7XG4gICAgaWYgKHJlcT8uY2xpZW50Py51cmxjb2RlKSB7XG4gICAgICAvLyBXZSBhZGQgb3B0aW9ucyB0byBnZW5lcmF0ZSB0aGUgUVIgY29kZSBpbiBoaWdoZXIgcmVzb2x1dGlvblxuICAgICAgLy8gVGhlIC9xcmNvZGUtc2Vzc2lvbiByZXF1ZXN0IHdpbGwgbm93IHJldHVybiBhIHJlYWRhYmxlIHFyY29kZS5cbiAgICAgIGNvbnN0IHFyT3B0aW9ucyA9IHtcbiAgICAgICAgZXJyb3JDb3JyZWN0aW9uTGV2ZWw6ICdNJyBhcyBjb25zdCxcbiAgICAgICAgdHlwZTogJ2ltYWdlL3BuZycgYXMgY29uc3QsXG4gICAgICAgIHNjYWxlOiA1LFxuICAgICAgICB3aWR0aDogNTAwLFxuICAgICAgfTtcbiAgICAgIGNvbnN0IHFyID0gcmVxLmNsaWVudC51cmxjb2RlXG4gICAgICAgID8gYXdhaXQgUVJDb2RlLnRvRGF0YVVSTChyZXEuY2xpZW50LnVybGNvZGUsIHFyT3B0aW9ucylcbiAgICAgICAgOiBudWxsO1xuICAgICAgY29uc3QgaW1nID0gQnVmZmVyLmZyb20oXG4gICAgICAgIChxciBhcyBhbnkpLnJlcGxhY2UoL15kYXRhOmltYWdlXFwvKHBuZ3xqcGVnfGpwZyk7YmFzZTY0LC8sICcnKSxcbiAgICAgICAgJ2Jhc2U2NCdcbiAgICAgICk7XG4gICAgICByZXMud3JpdGVIZWFkKDIwMCwge1xuICAgICAgICAnQ29udGVudC1UeXBlJzogJ2ltYWdlL3BuZycsXG4gICAgICAgICdDb250ZW50LUxlbmd0aCc6IGltZy5sZW5ndGgsXG4gICAgICB9KTtcbiAgICAgIHJlcy5lbmQoaW1nKTtcbiAgICB9IGVsc2UgaWYgKHR5cGVvZiByZXEuY2xpZW50ID09PSAndW5kZWZpbmVkJykge1xuICAgICAgcmVzLnN0YXR1cygyMDApLmpzb24oe1xuICAgICAgICBzdGF0dXM6IG51bGwsXG4gICAgICAgIG1lc3NhZ2U6XG4gICAgICAgICAgJ1Nlc3Npb24gbm90IHN0YXJ0ZWQuIFBsZWFzZSwgdXNlIHRoZSAvc3RhcnQtc2Vzc2lvbiByb3V0ZSwgZm9yIGluaXRpYWxpemF0aW9uIHlvdXIgc2Vzc2lvbicsXG4gICAgICB9KTtcbiAgICB9IGVsc2Uge1xuICAgICAgcmVzLnN0YXR1cygyMDApLmpzb24oe1xuICAgICAgICBzdGF0dXM6IHJlcS5jbGllbnQuc3RhdHVzLFxuICAgICAgICBtZXNzYWdlOiAnUVJDb2RlIGlzIG5vdCBhdmFpbGFibGUuLi4nLFxuICAgICAgfSk7XG4gICAgfVxuICB9IGNhdGNoIChleCkge1xuICAgIHJlcS5sb2dnZXIuZXJyb3IoZXgpO1xuICAgIHJlc1xuICAgICAgLnN0YXR1cyg1MDApXG4gICAgICAuanNvbih7IHN0YXR1czogJ2Vycm9yJywgbWVzc2FnZTogJ0Vycm9yIHJldHJpZXZpbmcgUVJDb2RlJywgZXJyb3I6IGV4IH0pO1xuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBraWxsU2VydmljZVdvcmtlcihyZXE6IFJlcXVlc3QsIHJlczogUmVzcG9uc2UpIHtcbiAgLyoqXG4gICAqICNzd2FnZ2VyLmlnbm9yZT10cnVlXG4gICAqICNzd2FnZ2VyLnRhZ3MgPSBbXCJNZXNzYWdlc1wiXVxuICAgICAjc3dhZ2dlci5vcGVyYXRpb25JZCA9ICdraWxsU2VydmljZVdvcmtpZXInXG4gICAgICNzd2FnZ2VyLmF1dG9Cb2R5PWZhbHNlXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAqL1xuICB0cnkge1xuICAgIHJlcy5zdGF0dXMoMjAwKS5qc29uKHsgc3RhdHVzOiAnZXJyb3InLCByZXNwb25zZTogJ05vdCBpbXBsZW1lbnRlZCB5ZXQnIH0pO1xuICB9IGNhdGNoIChleCkge1xuICAgIHJlcS5sb2dnZXIuZXJyb3IoZXgpO1xuICAgIHJlcy5zdGF0dXMoNTAwKS5qc29uKHtcbiAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgIG1lc3NhZ2U6ICdUaGUgc2Vzc2lvbiBpcyBub3QgYWN0aXZlJyxcbiAgICAgIGVycm9yOiBleCxcbiAgICB9KTtcbiAgfVxufVxuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24gcmVzdGFydFNlcnZpY2UocmVxOiBSZXF1ZXN0LCByZXM6IFJlc3BvbnNlKSB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci5pZ25vcmU9dHJ1ZVxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiTWVzc2FnZXNcIl1cbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAncmVzdGFydFNlcnZpY2UnXG4gICAgICNzd2FnZ2VyLmF1dG9Cb2R5PWZhbHNlXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAqL1xuICB0cnkge1xuICAgIHJlcy5zdGF0dXMoMjAwKS5qc29uKHsgc3RhdHVzOiAnZXJyb3InLCByZXNwb25zZTogJ05vdCBpbXBsZW1lbnRlZCB5ZXQnIH0pO1xuICB9IGNhdGNoIChleCkge1xuICAgIHJlcS5sb2dnZXIuZXJyb3IoZXgpO1xuICAgIHJlcy5zdGF0dXMoNTAwKS5qc29uKHtcbiAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgIHJlc3BvbnNlOiB7IG1lc3NhZ2U6ICdUaGUgc2Vzc2lvbiBpcyBub3QgYWN0aXZlJywgZXJyb3I6IGV4IH0sXG4gICAgfSk7XG4gIH1cbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIHN1YnNjcmliZVByZXNlbmNlKHJlcTogUmVxdWVzdCwgcmVzOiBSZXNwb25zZSkge1xuICAvKipcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIk1pc2NcIl1cbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAnc3Vic2NyaWJlUHJlc2VuY2UnXG4gICAgICNzd2FnZ2VyLmF1dG9Cb2R5PWZhbHNlXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAgICNzd2FnZ2VyLnJlcXVlc3RCb2R5ID0ge1xuICAgICAgcmVxdWlyZWQ6IHRydWUsXG4gICAgICBcIkBjb250ZW50XCI6IHtcbiAgICAgICAgXCJhcHBsaWNhdGlvbi9qc29uXCI6IHtcbiAgICAgICAgICBzY2hlbWE6IHtcbiAgICAgICAgICAgIHR5cGU6IFwib2JqZWN0XCIsXG4gICAgICAgICAgICBwcm9wZXJ0aWVzOiB7XG4gICAgICAgICAgICAgIHBob25lOiB7IHR5cGU6IFwic3RyaW5nXCIgfSxcbiAgICAgICAgICAgICAgaXNHcm91cDogeyB0eXBlOiBcImJvb2xlYW5cIiB9LFxuICAgICAgICAgICAgICBhbGw6IHsgdHlwZTogXCJib29sZWFuXCIgfSxcbiAgICAgICAgICAgIH1cbiAgICAgICAgICB9LFxuICAgICAgICAgIGV4YW1wbGU6IHtcbiAgICAgICAgICAgIHBob25lOiAnNTUyMTk5OTk5OTk5OScsXG4gICAgICAgICAgICBpc0dyb3VwOiBmYWxzZSxcbiAgICAgICAgICAgIGFsbDogZmFsc2UsXG4gICAgICAgICAgfVxuICAgICAgICB9XG4gICAgICB9XG4gICAgIH1cbiAgICovXG4gIHRyeSB7XG4gICAgY29uc3QgeyBwaG9uZSwgaXNHcm91cCA9IGZhbHNlLCBhbGwgPSBmYWxzZSwgaXNMaWQgPSBmYWxzZSB9ID0gcmVxLmJvZHk7XG5cbiAgICBjb25zdCBzdWJzY3JpYmVPbmUgPSBhc3luYyAoY29udGF0bzogc3RyaW5nKSA9PiB7XG4gICAgICAvLyBQcmVmZXIgdGhlIG1vZGVybiBXUFAuY29udGFjdC5zdWJzY3JpYmVQcmVzZW5jZSB3aGljaCB3b3JrcyB3aXRoXG4gICAgICAvLyBjdXJyZW50IFdoYXRzQXBwIFdlYi4gVGhlIGxlZ2FjeSByZXEuY2xpZW50LnN1YnNjcmliZVByZXNlbmNlIHVzZXNcbiAgICAgIC8vIHRoZSBpbnRlcm5hbCBXQVBJIHRoYXQgY2FsbHMgU3RvcmUuUHJlc2VuY2UuZmluZCgpIOKAlCBicm9rZW4gaW4gbmV3ZXJcbiAgICAgIC8vIFdBIHZlcnNpb25zIGFuZCByZXR1cm5zIDUwMC4gV2UgZmFsbCBiYWNrIHRvIHRoZSBsZWdhY3kgcGF0aCBpZiB0aGVcbiAgICAgIC8vIFdQUCBBUEkgaXMgbm90IGF2YWlsYWJsZS5cbiAgICAgIGNvbnN0IHBhZ2UgPSAocmVxLmNsaWVudCBhcyBhbnkpLnBhZ2U7XG4gICAgICBpZiAocGFnZSkge1xuICAgICAgICB0cnkge1xuICAgICAgICAgIGF3YWl0IHBhZ2UuZXZhbHVhdGUoKGlkOiBzdHJpbmcpID0+IHtcbiAgICAgICAgICAgIGNvbnN0IHdwcCA9ICh3aW5kb3cgYXMgYW55KS5XUFA7XG4gICAgICAgICAgICBpZiAod3BwICYmIHdwcC5jb250YWN0ICYmIHR5cGVvZiB3cHAuY29udGFjdC5zdWJzY3JpYmVQcmVzZW5jZSA9PT0gJ2Z1bmN0aW9uJykge1xuICAgICAgICAgICAgICByZXR1cm4gd3BwLmNvbnRhY3Quc3Vic2NyaWJlUHJlc2VuY2UoaWQpO1xuICAgICAgICAgICAgfVxuICAgICAgICAgICAgLy8gRmFsbGJhY2sgdG8gV1BQLndoYXRzYXBwLlByZXNlbmNlVXRpbHMgaWYgYXZhaWxhYmxlXG4gICAgICAgICAgICBpZiAod3BwICYmIHdwcC53aGF0c2FwcCAmJiB3cHAud2hhdHNhcHAuUHJlc2VuY2VVdGlscykge1xuICAgICAgICAgICAgICByZXR1cm4gd3BwLndoYXRzYXBwLlByZXNlbmNlVXRpbHMuc3Vic2NyaWJlVG9QcmVzZW5jZShpZCk7XG4gICAgICAgICAgICB9XG4gICAgICAgICAgICB0aHJvdyBuZXcgRXJyb3IoJ1dQUC5jb250YWN0LnN1YnNjcmliZVByZXNlbmNlIG5vdCBhdmFpbGFibGUnKTtcbiAgICAgICAgICB9LCBjb250YXRvKTtcbiAgICAgICAgICByZXEubG9nZ2VyLmluZm8oYFtzdWJzY3JpYmVQcmVzZW5jZV0gV1BQIHN1YnNjcmliZWQ6ICR7Y29udGF0b31gKTtcbiAgICAgICAgICByZXR1cm47XG4gICAgICAgIH0gY2F0Y2ggKHdwcEVycikge1xuICAgICAgICAgIHJlcS5sb2dnZXIud2FybihgW3N1YnNjcmliZVByZXNlbmNlXSBXUFAgZmFsbGJhY2sgZm9yICR7Y29udGF0b306ICR7d3BwRXJyfWApO1xuICAgICAgICB9XG4gICAgICB9XG4gICAgICAvLyBMZWdhY3kgZmFsbGJhY2tcbiAgICAgIGF3YWl0IHJlcS5jbGllbnQuc3Vic2NyaWJlUHJlc2VuY2UoY29udGF0byk7XG4gICAgfTtcblxuICAgIGlmIChhbGwpIHtcbiAgICAgIGxldCBjb250YWN0cztcbiAgICAgIGlmIChpc0dyb3VwKSB7XG4gICAgICAgIGNvbnN0IGdyb3VwcyA9IGF3YWl0IHJlcS5jbGllbnQuZ2V0QWxsR3JvdXBzKGZhbHNlKTtcbiAgICAgICAgY29udGFjdHMgPSBncm91cHMubWFwKChwOiBhbnkpID0+IHAuaWQuX3NlcmlhbGl6ZWQpO1xuICAgICAgfSBlbHNlIHtcbiAgICAgICAgY29uc3QgY2hhdHMgPSBhd2FpdCByZXEuY2xpZW50LmdldEFsbENvbnRhY3RzKCk7XG4gICAgICAgIGNvbnRhY3RzID0gY2hhdHMubWFwKChjOiBhbnkpID0+IGMuaWQuX3NlcmlhbGl6ZWQpO1xuICAgICAgfVxuICAgICAgZm9yIChjb25zdCBjb250YXRvIG9mIGNvbnRhY3RzKSB7XG4gICAgICAgIGF3YWl0IHN1YnNjcmliZU9uZShjb250YXRvKTtcbiAgICAgIH1cbiAgICB9IGVsc2Uge1xuICAgICAgZm9yIChjb25zdCBjb250YXRvIG9mIGNvbnRhY3RUb0FycmF5KHBob25lLCBpc0dyb3VwLCBmYWxzZSwgaXNMaWQpKSB7XG4gICAgICAgIGF3YWl0IHN1YnNjcmliZU9uZShjb250YXRvKTtcbiAgICAgIH1cbiAgICB9XG5cbiAgICByZXMuc3RhdHVzKDIwMCkuanNvbih7XG4gICAgICBzdGF0dXM6ICdzdWNjZXNzJyxcbiAgICAgIHJlc3BvbnNlOiB7IG1lc3NhZ2U6ICdTdWJzY3JpYmUgcHJlc2VuY2UgZXhlY3V0ZWQnIH0sXG4gICAgfSk7XG4gIH0gY2F0Y2ggKGVycm9yKSB7XG4gICAgcmVxLmxvZ2dlci5lcnJvcihlcnJvcik7XG4gICAgcmVzLnN0YXR1cyg1MDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgbWVzc2FnZTogJ0Vycm9yIG9uIHN1YnNjcmliZSBwcmVzZW5jZScsXG4gICAgICBlcnJvcjogZXJyb3IsXG4gICAgfSk7XG4gIH1cbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIHNldE9ubGluZVByZXNlbmNlKHJlcTogUmVxdWVzdCwgcmVzOiBSZXNwb25zZSkge1xuICAvKipcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIk1pc2NcIl1cbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAnc2V0T25saW5lUHJlc2VuY2UnXG4gICAgICNzd2FnZ2VyLmF1dG9Cb2R5PWZhbHNlXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAgICNzd2FnZ2VyLnJlcXVlc3RCb2R5ID0ge1xuICAgICAgcmVxdWlyZWQ6IHRydWUsXG4gICAgICBcIkBjb250ZW50XCI6IHtcbiAgICAgICAgXCJhcHBsaWNhdGlvbi9qc29uXCI6IHtcbiAgICAgICAgICBzY2hlbWE6IHtcbiAgICAgICAgICAgIHR5cGU6IFwib2JqZWN0XCIsXG4gICAgICAgICAgICBwcm9wZXJ0aWVzOiB7XG4gICAgICAgICAgICAgIGlzT25saW5lOiB7IHR5cGU6IFwiYm9vbGVhblwiIH0sXG4gICAgICAgICAgICB9XG4gICAgICAgICAgfSxcbiAgICAgICAgICBleGFtcGxlOiB7XG4gICBpc09ubGluZTogZmFsc2UsXG4gICAgICAgICAgfVxuICAgICAgICB9XG4gICAgICB9XG4gICAgIH1cbiAgICovXG4gIHRyeSB7XG4gICAgY29uc3QgeyBpc09ubGluZSA9IHRydWUgfSA9IHJlcS5ib2R5O1xuXG4gICAgYXdhaXQgcmVxLmNsaWVudC5zZXRPbmxpbmVQcmVzZW5jZShpc09ubGluZSk7XG5cbiAgICByZXMuc3RhdHVzKDIwMCkuanNvbih7XG4gICAgICBzdGF0dXM6ICdzdWNjZXNzJyxcbiAgICAgIHJlc3BvbnNlOiB7IG1lc3NhZ2U6ICdTZXQgT25saW5lIFByZXNlbmNlIFN1Y2Nlc3NmdWxseScgfSxcbiAgICB9KTtcbiAgfSBjYXRjaCAoZXJyb3IpIHtcbiAgICByZXMuc3RhdHVzKDUwMCkuanNvbih7XG4gICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICBtZXNzYWdlOiAnRXJyb3Igb24gc2V0IG9ubGluZSBwcmVzZW5jZScsXG4gICAgICBlcnJvcjogZXJyb3IsXG4gICAgfSk7XG4gIH1cbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIGVkaXRCdXNpbmVzc1Byb2ZpbGUocmVxOiBSZXF1ZXN0LCByZXM6IFJlc3BvbnNlKSB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiUHJvZmlsZVwiXVxuICAgICAjc3dhZ2dlci5vcGVyYXRpb25JZCA9ICdlZGl0QnVzaW5lc3NQcm9maWxlJ1xuICAgKiAjc3dhZ2dlci5kZXNjcmlwdGlvbiA9ICdFZGl0IHlvdXIgYnVzc2luZXNzIHByb2ZpbGUnXG4gICAgICNzd2FnZ2VyLmF1dG9Cb2R5PWZhbHNlXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAgICNzd2FnZ2VyLnBhcmFtZXRlcnNbXCJvYmpcIl0gPSB7XG4gICAgICBpbjogJ2JvZHknLFxuICAgICAgc2NoZW1hOiB7XG4gICAgICAgICRhZHJlc3M6ICdBdi4gTm9zc2EgU2VuaG9yYSBkZSBDb3BhY2FiYW5hLCAzMTUnLFxuICAgICAgICAkZW1haWw6ICd0ZXN0QHRlc3QuY29tLmJyJyxcbiAgICAgICAgJGNhdGVnb3JpZXM6IHtcbiAgICAgICAgICAkaWQ6IFwiMTMzNDM2NzQzMzg4MjE3XCIsXG4gICAgICAgICAgJGxvY2FsaXplZF9kaXNwbGF5X25hbWU6IFwiQXJ0ZXMgZSBlbnRyZXRlbmltZW50b1wiLFxuICAgICAgICAgICRub3RfYV9iaXo6IGZhbHNlLFxuICAgICAgICB9LFxuICAgICAgICAkd2Vic2l0ZTogW1xuICAgICAgICAgIFwiaHR0cHM6Ly93d3cud3BwY29ubmVjdC5pb1wiLFxuICAgICAgICAgIFwiaHR0cHM6Ly93d3cudGVzdGUyLmNvbS5iclwiLFxuICAgICAgICBdLFxuICAgICAgfVxuICAgICB9XG4gICAgIFxuICAgICAjc3dhZ2dlci5yZXF1ZXN0Qm9keSA9IHtcbiAgICAgIHJlcXVpcmVkOiB0cnVlLFxuICAgICAgXCJAY29udGVudFwiOiB7XG4gICAgICAgIFwiYXBwbGljYXRpb24vanNvblwiOiB7XG4gICAgICAgICAgc2NoZW1hOiB7XG4gICAgICAgICAgICB0eXBlOiBcIm9iamVjdFwiLFxuICAgICAgICAgICAgcHJvcGVydGllczoge1xuICAgICAgICAgICAgICBhZHJlc3M6IHsgdHlwZTogXCJzdHJpbmdcIiB9LFxuICAgICAgICAgICAgICBlbWFpbDogeyB0eXBlOiBcInN0cmluZ1wiIH0sXG4gICAgICAgICAgICAgIGNhdGVnb3JpZXM6IHsgdHlwZTogXCJvYmplY3RcIiB9LFxuICAgICAgICAgICAgICB3ZWJzaXRlczogeyB0eXBlOiBcImFycmF5XCIgfSxcbiAgICAgICAgICAgIH1cbiAgICAgICAgICB9LFxuICAgICAgICAgIGV4YW1wbGU6IHtcbiAgICAgICAgICAgIGFkcmVzczogJ0F2LiBOb3NzYSBTZW5ob3JhIGRlIENvcGFjYWJhbmEsIDMxNScsXG4gICAgICAgICAgICBlbWFpbDogJ3Rlc3RAdGVzdC5jb20uYnInLFxuICAgICAgICAgICAgY2F0ZWdvcmllczoge1xuICAgICAgICAgICAgICAkaWQ6IFwiMTMzNDM2NzQzMzg4MjE3XCIsXG4gICAgICAgICAgICAgICRsb2NhbGl6ZWRfZGlzcGxheV9uYW1lOiBcIkFydGVzIGUgZW50cmV0ZW5pbWVudG9cIixcbiAgICAgICAgICAgICAgJG5vdF9hX2JpejogZmFsc2UsXG4gICAgICAgICAgICB9LFxuICAgICAgICAgICAgd2Vic2l0ZTogW1xuICAgICAgICAgICAgICBcImh0dHBzOi8vd3d3LndwcGNvbm5lY3QuaW9cIixcbiAgICAgICAgICAgICAgXCJodHRwczovL3d3dy50ZXN0ZTIuY29tLmJyXCIsXG4gICAgICAgICAgICBdLFxuICAgICAgICAgIH1cbiAgICAgICAgfVxuICAgICAgfVxuICAgICB9XG4gICAqL1xuICB0cnkge1xuICAgIHJlcy5zdGF0dXMoMjAwKS5qc29uKGF3YWl0IHJlcS5jbGllbnQuZWRpdEJ1c2luZXNzUHJvZmlsZShyZXEuYm9keSkpO1xuICB9IGNhdGNoIChlcnJvcikge1xuICAgIHJlcy5zdGF0dXMoNTAwKS5qc29uKHtcbiAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgIG1lc3NhZ2U6ICdFcnJvciBvbiBlZGl0IGJ1c2luZXNzIHByb2ZpbGUnLFxuICAgICAgZXJyb3I6IGVycm9yLFxuICAgIH0pO1xuICB9XG59XG4iXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7O0FBaUJBLElBQUFBLEdBQUEsR0FB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