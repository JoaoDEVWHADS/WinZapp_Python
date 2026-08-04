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
      req.logger.error(`decryptFile failed (CDN link expired or forbidden), attempting WPP.chat.downloadMedia in browser: ${decryptErr}`);

      if (client.page && !client.page.isClosed()) {
        try {
          const rawBase64 = await client.page.evaluate(async ({ mId }) => {
            try {
              const WPP = window.WPP;
              if (!WPP?.chat?.downloadMedia) return null;
              let blob = null;
              try {
                blob = await WPP.chat.downloadMedia(mId);
              } catch (e) {
                if (mId.includes('@c.us')) {
                  try {blob = await WPP.chat.downloadMedia(mId.replace(/@c\.us/g, '@s.whatsapp.net'));} catch (e2) {}
                } else if (mId.includes('@s.whatsapp.net')) {
                  try {blob = await WPP.chat.downloadMedia(mId.replace(/@s\.whatsapp\.net/g, '@c.us'));} catch (e2) {}
                }
              }
              if (blob) {
                if (WPP?.util?.blobToBase64) {
                  return await WPP.util.blobToBase64(blob);
                }
                return new Promise((resolve) => {
                  const reader = new FileReader();
                  reader.onloadend = () => resolve(reader.result);
                  reader.onerror = () => resolve(null);
                  reader.readAsDataURL(blob);
                });
              }
              return null;
            } catch (e) {
              console.log(`[browser-evaluate downloadMedia error]: ${e}`);
              return null;
            }
          }, { mId: messageId });

          if (rawBase64 && typeof rawBase64 === 'string') {
            let mimetype = message.mimetype || 'audio/ogg';
            let base64 = rawBase64;
            if (rawBase64.startsWith('data:')) {
              const matches = rawBase64.match(/^data:(.*?);base64,(.*)$/);
              if (matches) {
                mimetype = matches[1];
                base64 = matches[2];
              }
            }
            req.logger.info(`Successfully downloaded media via browser WPP.chat.downloadMedia for ${messageId}! base64 len=${base64.length}`);
            return res.status(200).json({ base64, mimetype });
          }
        } catch (browserErr) {
          req.logger.error(`Browser WPP.chat.downloadMedia fallback error: ${browserErr}`);
        }
      }

      // Secondary fallback to WPPConnect's downloadMedia
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
              req.logger.warn(`Timeout 15000ms reached for client.downloadMedia (${messageId})`);
              resolve(null);
            }, 15000);
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
//# sourceMappingURL=data:application/json;charset=utf-8;base64,eyJ2ZXJzaW9uIjozLCJuYW1lcyI6WyJfZnMiLCJfaW50ZXJvcFJlcXVpcmVEZWZhdWx0IiwicmVxdWlyZSIsIl9taW1lVHlwZXMiLCJfcXJjb2RlIiwiX3BhY2thZ2UiLCJfY29uZmlnIiwiX2NyZWF0ZVNlc3Npb25VdGlsIiwiX2Z1bmN0aW9ucyIsIl9nZXRBbGxUb2tlbnMiLCJfc2Vzc2lvblV0aWwiLCJTZXNzaW9uVXRpbCIsIkNyZWF0ZVNlc3Npb25VdGlsIiwiZG93bmxvYWRGaWxlRnVuY3Rpb24iLCJtZXNzYWdlIiwiY2xpZW50IiwibG9nZ2VyIiwiYnVmZmVyIiwiZGVjcnlwdEZpbGUiLCJmaWxlbmFtZSIsInQiLCJmcyIsImV4aXN0c1N5bmMiLCJyZXN1bHQiLCJ0eXBlIiwibWltZSIsImV4dGVuc2lvbiIsIm1pbWV0eXBlIiwid3JpdGVGaWxlIiwiZXJyIiwiZXJyb3IiLCJlIiwid2FybiIsImRvd25sb2FkTWVkaWEiLCJkb3dubG9hZCIsInBhdGgiLCJyZXBsYWNlIiwic3RhcnRBbGxTZXNzaW9ucyIsInJlcSIsInJlcyIsInNlY3JldGtleSIsInBhcmFtcyIsImF1dGhvcml6YXRpb24iLCJ0b2tlbiIsImhlYWRlcnMiLCJ0b2tlbkRlY3J5cHQiLCJ1bmRlZmluZWQiLCJzcGxpdCIsImFsbFNlc3Npb25zIiwiZ2V0QWxsVG9rZW5zIiwic2VydmVyT3B0aW9ucyIsInNlY3JldEtleSIsInN0YXR1cyIsImpzb24iLCJyZXNwb25zZSIsIm1hcCIsInNlc3Npb24iLCJ1dGlsIiwib3BlbmRhdGEiLCJzaG93QWxsU2Vzc2lvbnMiLCJhcnIiLCJPYmplY3QiLCJrZXlzIiwiY2xpZW50c0FycmF5IiwiZm9yRWFjaCIsIml0ZW0iLCJwdXNoIiwic3RhcnRTZXNzaW9uIiwid2FpdFFyQ29kZSIsImJvZHkiLCJnZXRTZXNzaW9uU3RhdGUiLCJjbG9zZVNlc3Npb24iLCJpbmZvIiwic2hvdWxkQ2xvc2UiLCJmb3JjZUtpbGxTZXNzaW9uIiwiY2xvc2UiLCJpbyIsImVtaXQiLCJjYWxsV2ViSG9vayIsImNvbm5lY3RlZCIsImxvZ091dFNlc3Npb24iLCJsb2dvdXQiLCJkZWxldGVTZXNzaW9uT25BcnJheSIsInNldFRpbWVvdXQiLCJwYXRoVXNlckRhdGEiLCJjb25maWciLCJjdXN0b21Vc2VyRGF0YURpciIsInBhdGhUb2tlbnMiLCJfX2Rpcm5hbWUiLCJwcm9taXNlcyIsInJtIiwicmVjdXJzaXZlIiwibWF4UmV0cmllcyIsImZvcmNlIiwicmV0cnlEZWxheSIsImNoZWNrQ29ubmVjdGlvblNlc3Npb24iLCJpc0Nvbm5lY3RlZCIsInJlY29ubmVjdFNvY2tldFN0cmVhbSIsInBhZ2UiLCJpc0Nsb3NlZCIsImV2YWx1YXRlIiwid3BwIiwid2luZG93IiwiV1BQIiwid2hhdHNhcHAiLCJDbWQiLCJvcGVuU29ja2V0U3RyZWFtIiwib2siLCJTdHJpbmciLCJkb3dubG9hZE1lZGlhQnlNZXNzYWdlIiwibWVzc2FnZUlkIiwiZ2V0TWVzc2FnZUJ5SWQiLCJpc01lZGlhIiwiaXNNTVMiLCJiYXNlNjQiLCJ0b1N0cmluZyIsImdldE1lZGlhQnlNZXNzYWdlIiwiaGFzRG93bmxvYWRVcmwiLCJjbGllbnRVcmwiLCJkZXByZWNhdGVkTW1zM1VybCIsInVybCIsImRpcmVjdFBhdGgiLCJtZWRpYUtleSIsImRhdGEiLCJCdWZmZXIiLCJmcm9tIiwicGFydHMiLCJsZW5ndGgiLCJjaGF0SWQiLCJtc2dJZCIsInRhcmdldENoYXRJZCIsIlN0b3JlIiwidGFyZ2V0V2lkIiwiV2lkRmFjdG9yeSIsImNyZWF0ZSIsImNoYXQiLCJmaW5kIiwiaW5jbHVkZXMiLCJsb2FkRWFybGllck1lc3NhZ2VzIiwiZ2V0TXNnU2FmZSIsIm1JZCIsIm0iLCJyYXdJZCIsIk1zZyIsIm1vZGVscyIsImZvdW5kIiwiaWQiLCJzZXIiLCJfc2VyaWFsaXplZCIsIml0ZW1JZCIsImNvbnNvbGUiLCJsb2ciLCJyZXRyeUVyciIsImxvYWRFcnIiLCJtZWRpYVVybCIsInRpbWVyIiwiZG93bmxvYWRQcm9taXNlIiwiY2F0Y2giLCJmaW5hbGx5IiwiY2xlYXJUaW1lb3V0IiwidGltZW91dFByb21pc2UiLCJQcm9taXNlIiwicmVzb2x2ZSIsInJhY2UiLCJzdGFydHNXaXRoIiwibWF0Y2hlcyIsIm1hdGNoIiwiZG93bmxvYWRFcnIiLCJkZWNyeXB0RXJyIiwicmF3QmFzZTY0IiwiYmxvYiIsImUyIiwiYmxvYlRvQmFzZTY0IiwicmVhZGVyIiwiRmlsZVJlYWRlciIsIm9ubG9hZGVuZCIsIm9uZXJyb3IiLCJyZWFkQXNEYXRhVVJMIiwiYnJvd3NlckVyciIsImV4IiwiRXJyb3IiLCJxciIsInVybGNvZGUiLCJRUkNvZGUiLCJ0b0RhdGFVUkwiLCJxcmNvZGUiLCJ2ZXJzaW9uIiwiZ2V0UXJDb2RlIiwicXJPcHRpb25zIiwiZXJyb3JDb3JyZWN0aW9uTGV2ZWwiLCJzY2FsZSIsIndpZHRoIiwiaW1nIiwid3JpdGVIZWFkIiwiZW5kIiwia2lsbFNlcnZpY2VXb3JrZXIiLCJyZXN0YXJ0U2VydmljZSIsInN1YnNjcmliZVByZXNlbmNlIiwicGhvbmUiLCJpc0dyb3VwIiwiYWxsIiwiaXNMaWQiLCJzdWJzY3JpYmVPbmUiLCJjb250YXRvIiwiY29udGFjdCIsIlByZXNlbmNlVXRpbHMiLCJzdWJzY3JpYmVUb1ByZXNlbmNlIiwid3BwRXJyIiwiY29udGFjdHMiLCJncm91cHMiLCJnZXRBbGxHcm91cHMiLCJwIiwiY2hhdHMiLCJnZXRBbGxDb250YWN0cyIsImMiLCJjb250YWN0VG9BcnJheSIsInNldE9ubGluZVByZXNlbmNlIiwiaXNPbmxpbmUiLCJlZGl0QnVzaW5lc3NQcm9maWxlIl0sInNvdXJjZXMiOlsiLi4vLi4vc3JjL2NvbnRyb2xsZXIvc2Vzc2lvbkNvbnRyb2xsZXIudHMiXSwic291cmNlc0NvbnRlbnQiOlsiLypcbiAqIENvcHlyaWdodCAyMDIxIFdQUENvbm5lY3QgVGVhbVxuICpcbiAqIExpY2Vuc2VkIHVuZGVyIHRoZSBBcGFjaGUgTGljZW5zZSwgVmVyc2lvbiAyLjAgKHRoZSBcIkxpY2Vuc2VcIik7XG4gKiB5b3UgbWF5IG5vdCB1c2UgdGhpcyBmaWxlIGV4Y2VwdCBpbiBjb21wbGlhbmNlIHdpdGggdGhlIExpY2Vuc2UuXG4gKiBZb3UgbWF5IG9idGFpbiBhIGNvcHkgb2YgdGhlIExpY2Vuc2UgYXRcbiAqXG4gKiAgICAgaHR0cDovL3d3dy5hcGFjaGUub3JnL2xpY2Vuc2VzL0xJQ0VOU0UtMi4wXG4gKlxuICogVW5sZXNzIHJlcXVpcmVkIGJ5IGFwcGxpY2FibGUgbGF3IG9yIGFncmVlZCB0byBpbiB3cml0aW5nLCBzb2Z0d2FyZVxuICogZGlzdHJpYnV0ZWQgdW5kZXIgdGhlIExpY2Vuc2UgaXMgZGlzdHJpYnV0ZWQgb24gYW4gXCJBUyBJU1wiIEJBU0lTLFxuICogV0lUSE9VVCBXQVJSQU5USUVTIE9SIENPTkRJVElPTlMgT0YgQU5ZIEtJTkQsIGVpdGhlciBleHByZXNzIG9yIGltcGxpZWQuXG4gKiBTZWUgdGhlIExpY2Vuc2UgZm9yIHRoZSBzcGVjaWZpYyBsYW5ndWFnZSBnb3Zlcm5pbmcgcGVybWNsZWFyU2Vzc2lvbmlzc2lvbnMgYW5kXG4gKiBsaW1pdGF0aW9ucyB1bmRlciB0aGUgTGljZW5zZS5cbiAqL1xuaW1wb3J0IHsgTWVzc2FnZSwgV2hhdHNhcHAgfSBmcm9tICdAd3BwY29ubmVjdC10ZWFtL3dwcGNvbm5lY3QnO1xuaW1wb3J0IHsgUmVxdWVzdCwgUmVzcG9uc2UgfSBmcm9tICdleHByZXNzJztcbmltcG9ydCBmcyBmcm9tICdmcyc7XG5pbXBvcnQgbWltZSBmcm9tICdtaW1lLXR5cGVzJztcbmltcG9ydCBRUkNvZGUgZnJvbSAncXJjb2RlJztcbmltcG9ydCB7IExvZ2dlciB9IGZyb20gJ3dpbnN0b24nO1xuXG5pbXBvcnQgeyB2ZXJzaW9uIH0gZnJvbSAnLi4vLi4vcGFja2FnZS5qc29uJztcbmltcG9ydCBjb25maWcgZnJvbSAnLi4vY29uZmlnJztcbmltcG9ydCBDcmVhdGVTZXNzaW9uVXRpbCBmcm9tICcuLi91dGlsL2NyZWF0ZVNlc3Npb25VdGlsJztcbmltcG9ydCB7IGNhbGxXZWJIb29rLCBjb250YWN0VG9BcnJheSB9IGZyb20gJy4uL3V0aWwvZnVuY3Rpb25zJztcbmltcG9ydCBnZXRBbGxUb2tlbnMgZnJvbSAnLi4vdXRpbC9nZXRBbGxUb2tlbnMnO1xuaW1wb3J0IHsgY2xpZW50c0FycmF5LCBkZWxldGVTZXNzaW9uT25BcnJheSB9IGZyb20gJy4uL3V0aWwvc2Vzc2lvblV0aWwnO1xuXG5jb25zdCBTZXNzaW9uVXRpbCA9IG5ldyBDcmVhdGVTZXNzaW9uVXRpbCgpO1xuXG5hc3luYyBmdW5jdGlvbiBkb3dubG9hZEZpbGVGdW5jdGlvbihcbiAgbWVzc2FnZTogTWVzc2FnZSxcbiAgY2xpZW50OiBXaGF0c2FwcCxcbiAgbG9nZ2VyOiBMb2dnZXJcbikge1xuICB0cnkge1xuICAgIGNvbnN0IGJ1ZmZlciA9IGF3YWl0IGNsaWVudC5kZWNyeXB0RmlsZShtZXNzYWdlKTtcblxuICAgIGNvbnN0IGZpbGVuYW1lID0gYC4vV2hhdHNBcHBJbWFnZXMvZmlsZSR7bWVzc2FnZS50fWA7XG4gICAgaWYgKCFmcy5leGlzdHNTeW5jKGZpbGVuYW1lKSkge1xuICAgICAgbGV0IHJlc3VsdCA9ICcnO1xuICAgICAgaWYgKG1lc3NhZ2UudHlwZSA9PT0gJ3B0dCcpIHtcbiAgICAgICAgcmVzdWx0ID0gYCR7ZmlsZW5hbWV9Lm9nYWA7XG4gICAgICB9IGVsc2Uge1xuICAgICAgICByZXN1bHQgPSBgJHtmaWxlbmFtZX0uJHttaW1lLmV4dGVuc2lvbihtZXNzYWdlLm1pbWV0eXBlKX1gO1xuICAgICAgfVxuXG4gICAgICBhd2FpdCBmcy53cml0ZUZpbGUocmVzdWx0LCBidWZmZXIsIChlcnIpID0+IHtcbiAgICAgICAgaWYgKGVycikge1xuICAgICAgICAgIGxvZ2dlci5lcnJvcihlcnIpO1xuICAgICAgICB9XG4gICAgICB9KTtcblxuICAgICAgcmV0dXJuIHJlc3VsdDtcbiAgICB9IGVsc2Uge1xuICAgICAgcmV0dXJuIGAke2ZpbGVuYW1lfS4ke21pbWUuZXh0ZW5zaW9uKG1lc3NhZ2UubWltZXR5cGUpfWA7XG4gICAgfVxuICB9IGNhdGNoIChlKSB7XG4gICAgbG9nZ2VyLmVycm9yKGUpO1xuICAgIGxvZ2dlci53YXJuKFxuICAgICAgJ0Vycm8gYW8gZGVzY3JpcHRvZ3JhZmFyIGEgbWlkaWEsIHRlbnRhbmRvIGZhemVyIG8gZG93bmxvYWQgZGlyZXRvLi4uJ1xuICAgICk7XG4gICAgdHJ5IHtcbiAgICAgIGNvbnN0IGJ1ZmZlciA9IGF3YWl0IGNsaWVudC5kb3dubG9hZE1lZGlhKG1lc3NhZ2UpO1xuICAgICAgY29uc3QgZmlsZW5hbWUgPSBgLi9XaGF0c0FwcEltYWdlcy9maWxlJHttZXNzYWdlLnR9YDtcbiAgICAgIGlmICghZnMuZXhpc3RzU3luYyhmaWxlbmFtZSkpIHtcbiAgICAgICAgbGV0IHJlc3VsdCA9ICcnO1xuICAgICAgICBpZiAobWVzc2FnZS50eXBlID09PSAncHR0Jykge1xuICAgICAgICAgIHJlc3VsdCA9IGAke2ZpbGVuYW1lfS5vZ2FgO1xuICAgICAgICB9IGVsc2Uge1xuICAgICAgICAgIHJlc3VsdCA9IGAke2ZpbGVuYW1lfS4ke21pbWUuZXh0ZW5zaW9uKG1lc3NhZ2UubWltZXR5cGUpfWA7XG4gICAgICAgIH1cblxuICAgICAgICBhd2FpdCBmcy53cml0ZUZpbGUocmVzdWx0LCBidWZmZXIsIChlcnIpID0+IHtcbiAgICAgICAgICBpZiAoZXJyKSB7XG4gICAgICAgICAgICBsb2dnZXIuZXJyb3IoZXJyKTtcbiAgICAgICAgICB9XG4gICAgICAgIH0pO1xuXG4gICAgICAgIHJldHVybiByZXN1bHQ7XG4gICAgICB9IGVsc2Uge1xuICAgICAgICByZXR1cm4gYCR7ZmlsZW5hbWV9LiR7bWltZS5leHRlbnNpb24obWVzc2FnZS5taW1ldHlwZSl9YDtcbiAgICAgIH1cbiAgICB9IGNhdGNoIChlKSB7XG4gICAgICBsb2dnZXIuZXJyb3IoZSk7XG4gICAgICBsb2dnZXIud2FybignTsOjbyBmb2kgcG9zc8OtdmVsIGJhaXhhciBhIG3DrWRpYS4uLicpO1xuICAgIH1cbiAgfVxufVxuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24gZG93bmxvYWQobWVzc2FnZTogYW55LCBjbGllbnQ6IGFueSwgbG9nZ2VyOiBhbnkpIHtcbiAgdHJ5IHtcbiAgICBjb25zdCBwYXRoID0gYXdhaXQgZG93bmxvYWRGaWxlRnVuY3Rpb24obWVzc2FnZSwgY2xpZW50LCBsb2dnZXIpO1xuICAgIHJldHVybiBwYXRoPy5yZXBsYWNlKCcuLycsICcnKTtcbiAgfSBjYXRjaCAoZSkge1xuICAgIGxvZ2dlci5lcnJvcihlKTtcbiAgfVxufVxuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24gc3RhcnRBbGxTZXNzaW9ucyhcbiAgcmVxOiBSZXF1ZXN0LFxuICByZXM6IFJlc3BvbnNlXG4pOiBQcm9taXNlPGFueT4ge1xuICAvKipcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIkF1dGhcIl1cbiAgICAgI3N3YWdnZXIuYXV0b0JvZHk9ZmFsc2VcbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAnc3RhcnRBbGxTZXNzaW9ucydcbiAgICAgI3N3YWdnZXIuc2VjdXJpdHkgPSBbe1xuICAgICAgICAgICAgXCJiZWFyZXJBdXRoXCI6IFtdXG4gICAgIH1dXG4gICAgICNzd2FnZ2VyLnBhcmFtZXRlcnNbXCJzZXNzaW9uXCJdID0ge1xuICAgICAgc2NoZW1hOiAnTkVSRFdIQVRTX0FNRVJJQ0EnXG4gICAgIH1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlY3JldGtleVwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ1RISVNJU01ZU0VDVVJFQ09ERSdcbiAgICAgfVxuICAgKi9cbiAgY29uc3QgeyBzZWNyZXRrZXkgfSA9IHJlcS5wYXJhbXM7XG4gIGNvbnN0IHsgYXV0aG9yaXphdGlvbjogdG9rZW4gfSA9IHJlcS5oZWFkZXJzO1xuXG4gIGxldCB0b2tlbkRlY3J5cHQgPSAnJztcblxuICBpZiAoc2VjcmV0a2V5ID09PSB1bmRlZmluZWQpIHtcbiAgICB0b2tlbkRlY3J5cHQgPSAodG9rZW4gYXMgYW55KS5zcGxpdCgnICcpWzBdO1xuICB9IGVsc2Uge1xuICAgIHRva2VuRGVjcnlwdCA9IHNlY3JldGtleTtcbiAgfVxuXG4gIGNvbnN0IGFsbFNlc3Npb25zID0gYXdhaXQgZ2V0QWxsVG9rZW5zKHJlcSk7XG5cbiAgaWYgKHRva2VuRGVjcnlwdCAhPT0gcmVxLnNlcnZlck9wdGlvbnMuc2VjcmV0S2V5KSB7XG4gICAgcmVzLnN0YXR1cyg0MDApLmpzb24oe1xuICAgICAgcmVzcG9uc2U6ICdlcnJvcicsXG4gICAgICBtZXNzYWdlOiAnVGhlIHRva2VuIGlzIGluY29ycmVjdCcsXG4gICAgfSk7XG4gIH1cblxuICBhbGxTZXNzaW9ucy5tYXAoYXN5bmMgKHNlc3Npb246IHN0cmluZykgPT4ge1xuICAgIGNvbnN0IHV0aWwgPSBuZXcgQ3JlYXRlU2Vzc2lvblV0aWwoKTtcbiAgICBhd2FpdCB1dGlsLm9wZW5kYXRhKHJlcSwgc2Vzc2lvbik7XG4gIH0pO1xuXG4gIHJldHVybiBhd2FpdCByZXNcbiAgICAuc3RhdHVzKDIwMSlcbiAgICAuanNvbih7IHN0YXR1czogJ3N1Y2Nlc3MnLCBtZXNzYWdlOiAnU3RhcnRpbmcgYWxsIHNlc3Npb25zJyB9KTtcbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIHNob3dBbGxTZXNzaW9ucyhcbiAgcmVxOiBSZXF1ZXN0LFxuICByZXM6IFJlc3BvbnNlXG4pOiBQcm9taXNlPGFueT4ge1xuICAvKipcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIkF1dGhcIl1cbiAgICAgI3N3YWdnZXIuYXV0b0JvZHk9ZmFsc2VcbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAnc2hvd0FsbFNlc3Npb25zJ1xuICAgICAjc3dhZ2dlci5hdXRvUXVlcnk9ZmFsc2VcbiAgICAgI3N3YWdnZXIuYXV0b0hlYWRlcnM9ZmFsc2VcbiAgICAgI3N3YWdnZXIuc2VjdXJpdHkgPSBbe1xuICAgICAgICAgICAgXCJiZWFyZXJBdXRoXCI6IFtdXG4gICAgIH1dXG4gICAgICNzd2FnZ2VyLnBhcmFtZXRlcnNbXCJzZWNyZXRrZXlcIl0gPSB7XG4gICAgICBzY2hlbWE6ICdUSElTSVNNWVNFQ1VSRVRPS0VOJ1xuICAgICB9XG4gICAqL1xuICBjb25zdCB7IHNlY3JldGtleSB9ID0gcmVxLnBhcmFtcztcbiAgY29uc3QgeyBhdXRob3JpemF0aW9uOiB0b2tlbiB9ID0gcmVxLmhlYWRlcnM7XG5cbiAgbGV0IHRva2VuRGVjcnlwdDogYW55ID0gJyc7XG5cbiAgaWYgKHNlY3JldGtleSA9PT0gdW5kZWZpbmVkKSB7XG4gICAgdG9rZW5EZWNyeXB0ID0gdG9rZW4/LnNwbGl0KCcgJylbMF07XG4gIH0gZWxzZSB7XG4gICAgdG9rZW5EZWNyeXB0ID0gc2VjcmV0a2V5O1xuICB9XG5cbiAgY29uc3QgYXJyOiBhbnkgPSBbXTtcblxuICBpZiAodG9rZW5EZWNyeXB0ICE9PSByZXEuc2VydmVyT3B0aW9ucy5zZWNyZXRLZXkpIHtcbiAgICByZXMuc3RhdHVzKDQwMCkuanNvbih7XG4gICAgICByZXNwb25zZTogZmFsc2UsXG4gICAgICBtZXNzYWdlOiAnVGhlIHRva2VuIGlzIGluY29ycmVjdCcsXG4gICAgfSk7XG4gIH1cblxuICBPYmplY3Qua2V5cyhjbGllbnRzQXJyYXkpLmZvckVhY2goKGl0ZW0pID0+IHtcbiAgICBhcnIucHVzaCh7IHNlc3Npb246IGl0ZW0gfSk7XG4gIH0pO1xuXG4gIHJlcy5zdGF0dXMoMjAwKS5qc29uKHsgcmVzcG9uc2U6IGF3YWl0IGdldEFsbFRva2VucyhyZXEpIH0pO1xufVxuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24gc3RhcnRTZXNzaW9uKHJlcTogUmVxdWVzdCwgcmVzOiBSZXNwb25zZSk6IFByb21pc2U8YW55PiB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiQXV0aFwiXVxuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5vcGVyYXRpb25JZCA9ICdzdGFydFNlc3Npb24nXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAgICNzd2FnZ2VyLnJlcXVlc3RCb2R5ID0ge1xuICAgICAgcmVxdWlyZWQ6IHRydWUsXG4gICAgICBcIkBjb250ZW50XCI6IHtcbiAgICAgICAgXCJhcHBsaWNhdGlvbi9qc29uXCI6IHtcbiAgICAgICAgICBzY2hlbWE6IHtcbiAgICAgICAgICAgIHR5cGU6IFwib2JqZWN0XCIsXG4gICAgICAgICAgICBwcm9wZXJ0aWVzOiB7XG4gICAgICAgICAgICAgIHdlYmhvb2s6IHsgdHlwZTogXCJzdHJpbmdcIiB9LFxuICAgICAgICAgICAgICB3YWl0UXJDb2RlOiB7IHR5cGU6IFwiYm9vbGVhblwiIH0sXG4gICAgICAgICAgICAgIHByb3h5OiB7XG4gICAgICAgICAgICAgICAgdHlwZTogXCJvYmplY3RcIixcbiAgICAgICAgICAgICAgICBwcm9wZXJ0aWVzOiB7XG4gICAgICAgICAgICAgICAgICB1cmw6IHsgdHlwZTogXCJzdHJpbmdcIiB9LFxuICAgICAgICAgICAgICAgICAgdXNlcm5hbWU6IHsgdHlwZTogXCJzdHJpbmdcIiB9LFxuICAgICAgICAgICAgICAgICAgcGFzc3dvcmQ6IHsgdHlwZTogXCJzdHJpbmdcIiB9LFxuICAgICAgICAgICAgICAgIH1cbiAgICAgICAgICAgICAgfVxuICAgICAgICAgICAgfVxuICAgICAgICAgIH0sXG4gICAgICAgICAgZXhhbXBsZToge1xuICAgICAgICAgICAgd2ViaG9vazogXCJcIixcbiAgICAgICAgICAgIHdhaXRRckNvZGU6IGZhbHNlLFxuICAgICAgICAgICAgcHJveHk6IHtcbiAgICAgICAgICAgICAgdXJsOiBcImh0dHA6Ly9teXByb3h5LmNvbTo4MDgwXCIsXG4gICAgICAgICAgICAgIHVzZXJuYW1lOiBcIm15dXNlclwiLFxuICAgICAgICAgICAgICBwYXNzd29yZDogXCJteXBhc3N3b3JkXCJcbiAgICAgICAgICAgIH1cbiAgICAgICAgICB9XG4gICAgICAgIH1cbiAgICAgIH1cbiAgICAgfVxuICAgKi9cbiAgY29uc3Qgc2Vzc2lvbiA9IHJlcS5zZXNzaW9uO1xuICBjb25zdCB7IHdhaXRRckNvZGUgPSBmYWxzZSB9ID0gcmVxLmJvZHk7XG5cbiAgYXdhaXQgZ2V0U2Vzc2lvblN0YXRlKHJlcSwgcmVzKTtcbiAgYXdhaXQgU2Vzc2lvblV0aWwub3BlbmRhdGEocmVxLCBzZXNzaW9uLCB3YWl0UXJDb2RlID8gcmVzIDogbnVsbCk7XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBjbG9zZVNlc3Npb24ocmVxOiBSZXF1ZXN0LCByZXM6IFJlc3BvbnNlKTogUHJvbWlzZTxhbnk+IHtcbiAgLyoqXG4gICAqICNzd2FnZ2VyLnRhZ3MgPSBbXCJBdXRoXCJdXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ2Nsb3NlU2Vzc2lvbidcbiAgICAgI3N3YWdnZXIuYXV0b0JvZHk9dHJ1ZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgKi9cbiAgY29uc3Qgc2Vzc2lvbiA9IHJlcS5zZXNzaW9uO1xuICB0cnkge1xuICAgIGNvbnN0IGNsaWVudCA9IChjbGllbnRzQXJyYXkgYXMgYW55KVtzZXNzaW9uXTtcbiAgICBpZiAoIWNsaWVudCkge1xuICAgICAgcmV0dXJuIGF3YWl0IHJlc1xuICAgICAgICAuc3RhdHVzKDIwMClcbiAgICAgICAgLmpzb24oeyBzdGF0dXM6IHRydWUsIG1lc3NhZ2U6ICdTZXNzaW9uIHN1Y2Nlc3NmdWxseSBjbG9zZWQnIH0pO1xuICAgIH1cblxuICAgIGlmIChjbGllbnQuc3RhdHVzICE9PSAnQ09OTkVDVEVEJyAmJiBjbGllbnQuc3RhdHVzICE9PSAnb3BlbicpIHtcbiAgICAgIHJlcS5sb2dnZXIuaW5mbyhgWyR7c2Vzc2lvbn1dIEZvcmNlIGtpbGxpbmcgc2Vzc2lvbiBiZWNhdXNlIHN0YXR1cyBpcyAke2NsaWVudC5zdGF0dXN9YCk7XG4gICAgICBjbGllbnQuc2hvdWxkQ2xvc2UgPSB0cnVlO1xuICAgICAgdHJ5IHtcbiAgICAgICAgU2Vzc2lvblV0aWwuZm9yY2VLaWxsU2Vzc2lvbihzZXNzaW9uLCByZXEubG9nZ2VyKTtcbiAgICAgIH0gY2F0Y2ggKGUpIHt9XG4gICAgICAoY2xpZW50c0FycmF5IGFzIGFueSlbc2Vzc2lvbl0gPSB1bmRlZmluZWQ7XG4gICAgICByZXR1cm4gYXdhaXQgcmVzXG4gICAgICAgIC5zdGF0dXMoMjAwKVxuICAgICAgICAuanNvbih7IHN0YXR1czogdHJ1ZSwgbWVzc2FnZTogJ1Nlc3Npb24gZm9yY2UgY2xvc2VkJyB9KTtcbiAgICB9XG5cbiAgICAoY2xpZW50c0FycmF5IGFzIGFueSlbc2Vzc2lvbl0gPSB7IHN0YXR1czogbnVsbCB9O1xuXG4gICAgaWYgKHJlcS5jbGllbnQgJiYgdHlwZW9mIHJlcS5jbGllbnQuY2xvc2UgPT09ICdmdW5jdGlvbicpIHtcbiAgICAgIGF3YWl0IHJlcS5jbGllbnQuY2xvc2UoKTtcbiAgICB9XG4gICAgICByZXEuaW8uZW1pdCgnd2hhdHNhcHAtc3RhdHVzJywgZmFsc2UpO1xuICAgICAgY2FsbFdlYkhvb2socmVxLmNsaWVudCwgcmVxLCAnY2xvc2VzZXNzaW9uJywge1xuICAgICAgICBtZXNzYWdlOiBgU2Vzc2lvbjogJHtzZXNzaW9ufSBkaXNjb25uZWN0ZWRgLFxuICAgICAgICBjb25uZWN0ZWQ6IGZhbHNlLFxuICAgICAgfSk7XG5cbiAgICAgIHJldHVybiBhd2FpdCByZXNcbiAgICAgICAgLnN0YXR1cygyMDApXG4gICAgICAgIC5qc29uKHsgc3RhdHVzOiB0cnVlLCBtZXNzYWdlOiAnU2Vzc2lvbiBzdWNjZXNzZnVsbHkgY2xvc2VkJyB9KTtcbiAgfSBjYXRjaCAoZXJyb3IpIHtcbiAgICByZXEubG9nZ2VyLmVycm9yKGVycm9yKTtcbiAgICByZXR1cm4gYXdhaXQgcmVzXG4gICAgICAuc3RhdHVzKDUwMClcbiAgICAgIC5qc29uKHsgc3RhdHVzOiBmYWxzZSwgbWVzc2FnZTogJ0Vycm9yIGNsb3Npbmcgc2Vzc2lvbicsIGVycm9yIH0pO1xuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBsb2dPdXRTZXNzaW9uKHJlcTogUmVxdWVzdCwgcmVzOiBSZXNwb25zZSk6IFByb21pc2U8YW55PiB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiQXV0aFwiXVxuICAgICAjc3dhZ2dlci5vcGVyYXRpb25JZCA9ICdsb2dvdXRTZXNzaW9uJ1xuICAgKiAjc3dhZ2dlci5kZXNjcmlwdGlvbiA9ICdUaGlzIHJvdXRlIGxvZ291dCBhbmQgZGVsZXRlIHNlc3Npb24gZGF0YSdcbiAgICAgI3N3YWdnZXIuYXV0b0JvZHk9ZmFsc2VcbiAgICAgI3N3YWdnZXIuc2VjdXJpdHkgPSBbe1xuICAgICAgICAgICAgXCJiZWFyZXJBdXRoXCI6IFtdXG4gICAgIH1dXG4gICAgICNzd2FnZ2VyLnBhcmFtZXRlcnNbXCJzZXNzaW9uXCJdID0ge1xuICAgICAgc2NoZW1hOiAnTkVSRFdIQVRTX0FNRVJJQ0EnXG4gICAgIH1cbiAgICovXG4gIHRyeSB7XG4gICAgY29uc3Qgc2Vzc2lvbiA9IHJlcS5zZXNzaW9uO1xuICAgIGF3YWl0IHJlcS5jbGllbnQubG9nb3V0KCk7XG4gICAgZGVsZXRlU2Vzc2lvbk9uQXJyYXkocmVxLnNlc3Npb24pO1xuXG4gICAgc2V0VGltZW91dChhc3luYyAoKSA9PiB7XG4gICAgICBjb25zdCBwYXRoVXNlckRhdGEgPSBjb25maWcuY3VzdG9tVXNlckRhdGFEaXIgKyByZXEuc2Vzc2lvbjtcbiAgICAgIGNvbnN0IHBhdGhUb2tlbnMgPSBfX2Rpcm5hbWUgKyBgLi4vLi4vLi4vdG9rZW5zLyR7cmVxLnNlc3Npb259LmRhdGEuanNvbmA7XG5cbiAgICAgIGlmIChmcy5leGlzdHNTeW5jKHBhdGhVc2VyRGF0YSkpIHtcbiAgICAgICAgYXdhaXQgZnMucHJvbWlzZXMucm0ocGF0aFVzZXJEYXRhLCB7XG4gICAgICAgICAgcmVjdXJzaXZlOiB0cnVlLFxuICAgICAgICAgIG1heFJldHJpZXM6IDUsXG4gICAgICAgICAgZm9yY2U6IHRydWUsXG4gICAgICAgICAgcmV0cnlEZWxheTogMTAwMCxcbiAgICAgICAgfSk7XG4gICAgICB9XG4gICAgICBpZiAoZnMuZXhpc3RzU3luYyhwYXRoVG9rZW5zKSkge1xuICAgICAgICBhd2FpdCBmcy5wcm9taXNlcy5ybShwYXRoVG9rZW5zLCB7XG4gICAgICAgICAgcmVjdXJzaXZlOiB0cnVlLFxuICAgICAgICAgIG1heFJldHJpZXM6IDUsXG4gICAgICAgICAgZm9yY2U6IHRydWUsXG4gICAgICAgICAgcmV0cnlEZWxheTogMTAwMCxcbiAgICAgICAgfSk7XG4gICAgICB9XG5cbiAgICAgIHJlcS5pby5lbWl0KCd3aGF0c2FwcC1zdGF0dXMnLCBmYWxzZSk7XG4gICAgICBjYWxsV2ViSG9vayhyZXEuY2xpZW50LCByZXEsICdsb2dvdXRzZXNzaW9uJywge1xuICAgICAgICBtZXNzYWdlOiBgU2Vzc2lvbjogJHtzZXNzaW9ufSBsb2dnZWQgb3V0YCxcbiAgICAgICAgY29ubmVjdGVkOiBmYWxzZSxcbiAgICAgIH0pO1xuXG4gICAgICByZXR1cm4gYXdhaXQgcmVzXG4gICAgICAgIC5zdGF0dXMoMjAwKVxuICAgICAgICAuanNvbih7IHN0YXR1czogdHJ1ZSwgbWVzc2FnZTogJ1Nlc3Npb24gc3VjY2Vzc2Z1bGx5IGNsb3NlZCcgfSk7XG4gICAgfSwgNTAwKTtcbiAgICAvKnRyeSB7XG4gICAgICBhd2FpdCByZXEuY2xpZW50LmNsb3NlKCk7XG4gICAgfSBjYXRjaCAoZXJyb3IpIHt9Ki9cbiAgfSBjYXRjaCAoZXJyb3IpIHtcbiAgICByZXEubG9nZ2VyLmVycm9yKGVycm9yKTtcbiAgICByZXNcbiAgICAgIC5zdGF0dXMoNTAwKVxuICAgICAgLmpzb24oeyBzdGF0dXM6IGZhbHNlLCBtZXNzYWdlOiAnRXJyb3IgY2xvc2luZyBzZXNzaW9uJywgZXJyb3IgfSk7XG4gIH1cbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIGNoZWNrQ29ubmVjdGlvblNlc3Npb24oXG4gIHJlcTogUmVxdWVzdCxcbiAgcmVzOiBSZXNwb25zZVxuKTogUHJvbWlzZTxhbnk+IHtcbiAgLyoqXG4gICAqICNzd2FnZ2VyLnRhZ3MgPSBbXCJBdXRoXCJdXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ0NoZWNrQ29ubmVjdGlvblN0YXRlJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgKi9cbiAgdHJ5IHtcbiAgICBhd2FpdCByZXEuY2xpZW50LmlzQ29ubmVjdGVkKCk7XG5cbiAgICByZXMuc3RhdHVzKDIwMCkuanNvbih7IHN0YXR1czogdHJ1ZSwgbWVzc2FnZTogJ0Nvbm5lY3RlZCcgfSk7XG4gIH0gY2F0Y2ggKGVycm9yKSB7XG4gICAgcmVzLnN0YXR1cygyMDApLmpzb24oeyBzdGF0dXM6IGZhbHNlLCBtZXNzYWdlOiAnRGlzY29ubmVjdGVkJyB9KTtcbiAgfVxufVxuXG4vLyBXaW5aYXBwIHBhdGNoOiBudWRnZSBXaGF0c0FwcCBXZWIncyBvd24gbXVsdGktZGV2aWNlIHNvY2tldCBiYWNrIG9wZW4uXG4vL1xuLy8gUmVwb3J0ZWQgbGl2ZTogYWZ0ZXIgdGhlIE9TIHJlc3VtZXMgZnJvbSBzbGVlcCwgV2luWmFwcCdzIHN0YXR1cy1zZXNzaW9uXG4vLyBwcm9iZSBrZWVwcyByZXBvcnRpbmcgdGhlIFdQUENvbm5lY3Qgc2Vzc2lvbiBvYmplY3QgYXMgXCJDT05ORUNURURcIiAodGhhdFxuLy8gc3RyaW5nIGlzIGp1c3QgY2FjaGVkIGF0IHNlc3Npb24gY3JlYXRpb24g4oCUIHNlZSBjaGVja0Nvbm5lY3Rpb25TZXNzaW9uJ3Ncbi8vIG93biBjb21tZW50IGFib3ZlIGl0KSwgYnV0IHRoZSAqbGl2ZSogaXNDb25uZWN0ZWQoKSBwcm9iZSBuZXZlciBjb21lcyBiYWNrXG4vLyB0cnVlIGFnYWluLCBmb3JldmVyIOKAlCB0aGUgYXBwIGlzIHN0dWNrIG9mZmxpbmUgdW50aWwgdGhlIHdob2xlIHByb2dyYW0gaXNcbi8vIHJlc3RhcnRlZCAoYSBmcmVzaCBQdXBwZXRlZXIvQ2hyb21lICsgZnJlc2ggcGFnZSkuXG4vL1xuLy8gVGhlIHJlYWwgV2hhdHNBcHAgV2ViIGNsaWVudCByZS1vcGVucyBpdHMgc29ja2V0IHN0cmVhbSB2aWFcbi8vIFdQUC53aGF0c2FwcC5DbWQub3BlblNvY2tldFN0cmVhbSgpIOKAlCBub3JtYWxseSB0cmlnZ2VyZWQgYnkgdGhlIHBhZ2UncyBvd25cbi8vIHZpc2liaWxpdHkvZm9jdXMvb25saW5lIERPTSBldmVudHMuIFRoaXMgc2Vzc2lvbidzIENocm9tZSBwYWdlIHJ1bnNcbi8vIGhlYWRsZXNzIGFuZCBpcyBuZXZlciBmb2N1c2VkIG9yIGJyb3VnaHQgdG8gdGhlIGZvcmVncm91bmQsIHNvIG5vdGhpbmdcbi8vIGV2ZXIgZmlyZXMgdGhvc2UgZXZlbnRzIGFmdGVyIGEgc3VzcGVuZC9yZXN1bWUgY3ljbGUg4oCUIHRoZSBzb2NrZXQgdGhhdFxuLy8gd2VudCBkb3duIGR1cmluZyBzbGVlcCBoYXMgbm8gdHJpZ2dlciBsZWZ0IHRvIHJlY29ubmVjdCBpdCwgdW5saWtlIGEgcmVhbCxcbi8vIHZpc2libGUgYnJvd3NlciB0YWIgYSB1c2VyIG1pZ2h0IGNsaWNrIGJhY2sgaW50by4gQ2FsbGluZyB0aGUgc2FtZVxuLy8gaW50ZXJuYWwgY29tbWFuZCBkaXJlY3RseSByZXByb2R1Y2VzIHdoYXRldmVyIGEgZm9jdXMvdmlzaWJpbGl0eSBldmVudFxuLy8gd291bGQgaGF2ZSB0cmlnZ2VyZWQgb24gYSBub3JtYWwgdGFiLlxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIHJlY29ubmVjdFNvY2tldFN0cmVhbShyZXE6IFJlcXVlc3QsIHJlczogUmVzcG9uc2UpIHtcbiAgLyoqXG4gICAqICNzd2FnZ2VyLnRhZ3MgPSBbXCJBdXRoXCJdXG4gICAgICNzd2FnZ2VyLmF1dG9Cb2R5PWZhbHNlXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAqL1xuICB0cnkge1xuICAgIGNvbnN0IHBhZ2UgPSAocmVxLmNsaWVudCBhcyBhbnkpPy5wYWdlO1xuICAgIGlmICghcGFnZSB8fCBwYWdlLmlzQ2xvc2VkKCkpIHtcbiAgICAgIHJldHVybiByZXMuc3RhdHVzKDQwMCkuanNvbih7XG4gICAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgICAgbWVzc2FnZTogJ1RoZSBXaGF0c0FwcCBzZXNzaW9uIGlzIG5vdCBhY3RpdmUuJyxcbiAgICAgIH0pO1xuICAgIH1cbiAgICBjb25zdCByZXN1bHQgPSBhd2FpdCBwYWdlLmV2YWx1YXRlKCgpID0+IHtcbiAgICAgIHRyeSB7XG4gICAgICAgIGNvbnN0IHdwcCA9ICh3aW5kb3cgYXMgYW55KS5XUFA7XG4gICAgICAgIGlmICh3cHA/LndoYXRzYXBwPy5DbWQ/Lm9wZW5Tb2NrZXRTdHJlYW0pIHtcbiAgICAgICAgICB3cHAud2hhdHNhcHAuQ21kLm9wZW5Tb2NrZXRTdHJlYW0oKTtcbiAgICAgICAgICByZXR1cm4geyBvazogdHJ1ZSB9O1xuICAgICAgICB9XG4gICAgICAgIHJldHVybiB7IG9rOiBmYWxzZSwgZXJyb3I6ICdXUFAud2hhdHNhcHAuQ21kLm9wZW5Tb2NrZXRTdHJlYW0gbm90IGF2YWlsYWJsZScgfTtcbiAgICAgIH0gY2F0Y2ggKGU6IGFueSkge1xuICAgICAgICByZXR1cm4geyBvazogZmFsc2UsIGVycm9yOiBlPy5tZXNzYWdlIHx8IFN0cmluZyhlKSB9O1xuICAgICAgfVxuICAgIH0pO1xuICAgIGlmICghcmVzdWx0Py5vaykge1xuICAgICAgcmVxLmxvZ2dlci53YXJuKGBbcmVjb25uZWN0U29ja2V0U3RyZWFtXSAke3Jlc3VsdD8uZXJyb3IgfHwgJ3Vua25vd24gZmFpbHVyZSd9YCk7XG4gICAgfVxuICAgIHJlcy5zdGF0dXMoMjAwKS5qc29uKHsgc3RhdHVzOiAnc3VjY2VzcycsIHJlc3BvbnNlOiByZXN1bHQgfSk7XG4gIH0gY2F0Y2ggKGVycm9yOiBhbnkpIHtcbiAgICByZXEubG9nZ2VyLmVycm9yKGVycm9yKTtcbiAgICByZXMuc3RhdHVzKDUwMCkuanNvbih7XG4gICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICBtZXNzYWdlOiBlcnJvcj8ubWVzc2FnZSB8fCBTdHJpbmcoZXJyb3IpLFxuICAgIH0pO1xuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBkb3dubG9hZE1lZGlhQnlNZXNzYWdlKHJlcTogUmVxdWVzdCwgcmVzOiBSZXNwb25zZSkge1xuICAvKipcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIk1lc3NhZ2VzXCJdXG4gICAgICNzd2FnZ2VyLmF1dG9Cb2R5PWZhbHNlXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ2Rvd25sb2FkTWVkaWFieU1lc3NhZ2UnXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAgICNzd2FnZ2VyLnJlcXVlc3RCb2R5ID0ge1xuICAgICAgcmVxdWlyZWQ6IHRydWUsXG4gICAgICBcIkBjb250ZW50XCI6IHtcbiAgICAgICAgXCJhcHBsaWNhdGlvbi9qc29uXCI6IHtcbiAgICAgICAgICBzY2hlbWE6IHtcbiAgICAgICAgICAgIHR5cGU6IFwib2JqZWN0XCIsXG4gICAgICAgICAgICBwcm9wZXJ0aWVzOiB7XG4gICAgICAgICAgICAgIG1lc3NhZ2VJZDogeyB0eXBlOiBcInN0cmluZ1wiIH0sXG4gICAgICAgICAgICB9XG4gICAgICAgICAgfSxcbiAgICAgICAgICBleGFtcGxlOiB7XG4gICAgICAgICAgICBtZXNzYWdlSWQ6ICc8bWVzc2FnZUlkPidcbiAgICAgICAgICB9XG4gICAgICAgIH1cbiAgICAgIH1cbiAgICAgfVxuICAgKi9cbiAgY29uc3QgY2xpZW50ID0gcmVxLmNsaWVudDtcbiAgY29uc3QgeyBtZXNzYWdlSWQgfSA9IHJlcS5ib2R5O1xuXG4gIGlmICghY2xpZW50IHx8IHR5cGVvZiBjbGllbnQuZ2V0TWVzc2FnZUJ5SWQgIT09ICdmdW5jdGlvbicpIHtcbiAgICByZXR1cm4gcmVzLnN0YXR1cyg0MDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgbWVzc2FnZTogJ1RoZSBXaGF0c0FwcCBzZXNzaW9uIGlzIG5vdCBhY3RpdmUuJyxcbiAgICB9KTtcbiAgfVxuXG4gIGxldCBtZXNzYWdlO1xuXG4gIHRyeSB7XG4gICAgaWYgKCFtZXNzYWdlSWQuaXNNZWRpYSB8fCAhbWVzc2FnZUlkLnR5cGUpIHtcbiAgICAgIG1lc3NhZ2UgPSBhd2FpdCBjbGllbnQuZ2V0TWVzc2FnZUJ5SWQobWVzc2FnZUlkKTtcbiAgICB9IGVsc2Uge1xuICAgICAgbWVzc2FnZSA9IG1lc3NhZ2VJZDtcbiAgICB9XG5cbiAgICBpZiAoIW1lc3NhZ2UpXG4gICAgICByZXMuc3RhdHVzKDQwMCkuanNvbih7XG4gICAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgICAgbWVzc2FnZTogJ01lc3NhZ2Ugbm90IGZvdW5kJyxcbiAgICAgIH0pO1xuXG4gICAgaWYgKCEobWVzc2FnZVsnbWltZXR5cGUnXSB8fCBtZXNzYWdlLmlzTWVkaWEgfHwgbWVzc2FnZS5pc01NUykpXG4gICAgICByZXMuc3RhdHVzKDQwMCkuanNvbih7XG4gICAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgICAgbWVzc2FnZTogJ01lc3NhZ2UgZG9lcyBub3QgY29udGFpbiBtZWRpYScsXG4gICAgICB9KTtcblxuICAgIGNvbnN0IGJ1ZmZlciA9IGF3YWl0IGNsaWVudC5kZWNyeXB0RmlsZShtZXNzYWdlKTtcblxuICAgIHJlc1xuICAgICAgLnN0YXR1cygyMDApXG4gICAgICAuanNvbih7IGJhc2U2NDogYnVmZmVyLnRvU3RyaW5nKCdiYXNlNjQnKSwgbWltZXR5cGU6IG1lc3NhZ2UubWltZXR5cGUgfSk7XG4gIH0gY2F0Y2ggKGUpIHtcbiAgICByZXEubG9nZ2VyLmVycm9yKGUpO1xuICAgIHJlcy5zdGF0dXMoNDAwKS5qc29uKHtcbiAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgIG1lc3NhZ2U6ICdEZWNyeXB0IGZpbGUgZXJyb3InLFxuICAgICAgZXJyb3I6IGUsXG4gICAgfSk7XG4gIH1cbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIGdldE1lZGlhQnlNZXNzYWdlKHJlcTogUmVxdWVzdCwgcmVzOiBSZXNwb25zZSkge1xuICAvKipcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIk1lc3NhZ2VzXCJdXG4gICAgICNzd2FnZ2VyLmF1dG9Cb2R5PWZhbHNlXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ2dldE1lZGlhQnlNZXNzYWdlJ1xuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ21lc3NhZ2VJZCdcbiAgICAgfVxuICAgKi9cbiAgY29uc3QgY2xpZW50ID0gcmVxLmNsaWVudDtcbiAgY29uc3QgeyBtZXNzYWdlSWQgfSA9IHJlcS5wYXJhbXM7XG5cbiAgaWYgKCFjbGllbnQgfHwgdHlwZW9mIGNsaWVudC5nZXRNZXNzYWdlQnlJZCAhPT0gJ2Z1bmN0aW9uJykge1xuICAgIHJldHVybiByZXMuc3RhdHVzKDQwMCkuanNvbih7XG4gICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICBtZXNzYWdlOiAnVGhlIFdoYXRzQXBwIHNlc3Npb24gaXMgbm90IGFjdGl2ZS4nLFxuICAgIH0pO1xuICB9XG5cbiAgdHJ5IHtcbiAgICBsZXQgbWVzc2FnZTogYW55ID0gbnVsbDtcblxuICAgIC8vIElmIGRldGFpbHMgYXJlIHByb3ZpZGVkIGluIHRoZSByZXF1ZXN0IGJvZHkgKGUuZy4gUE9TVCByZXF1ZXN0IHdpdGggbG9jYWwgY2FjaGUgQU5EIGRvd25sb2FkIFVSTCksIHVzZSB0aGVtIGRpcmVjdGx5LlxuICAgIGNvbnN0IGhhc0Rvd25sb2FkVXJsID0gcmVxLmJvZHkgJiYgKHJlcS5ib2R5LmNsaWVudFVybCB8fCByZXEuYm9keS5kZXByZWNhdGVkTW1zM1VybCB8fCByZXEuYm9keS51cmwgfHwgcmVxLmJvZHkuZGlyZWN0UGF0aCk7XG4gICAgaWYgKHJlcS5ib2R5ICYmIHJlcS5ib2R5Lm1lZGlhS2V5ICYmIGhhc0Rvd25sb2FkVXJsKSB7XG4gICAgICByZXEubG9nZ2VyLmluZm8oYFJlY2VpdmVkIGZ1bGwgZGVjcnlwdGlvbiBrZXlzIGFuZCBkb3dubG9hZCBVUkwgaW4gYm9keSBmb3IgbWVzc2FnZSAke21lc3NhZ2VJZH0uIEJ5cGFzc2luZyBQdXBwZXRlZXIgbG9va3VwLmApO1xuICAgICAgbWVzc2FnZSA9IHJlcS5ib2R5O1xuICAgICAgaWYgKCFtZXNzYWdlLmNsaWVudFVybCAmJiAobWVzc2FnZS51cmwgfHwgbWVzc2FnZS5kZXByZWNhdGVkTW1zM1VybCkpIHtcbiAgICAgICAgbWVzc2FnZS5jbGllbnRVcmwgPSBtZXNzYWdlLmNsaWVudFVybCB8fCBtZXNzYWdlLnVybCB8fCBtZXNzYWdlLmRlcHJlY2F0ZWRNbXMzVXJsO1xuICAgICAgfVxuICAgICAgLy8gTm9ybWFsaXNlIGtleSB0eXBlcyBhbmQgc3RydWN0dXJlcyBpZiBuZWVkZWQgYnkgZGVjcnlwdEZpbGVcbiAgICAgIGlmICh0eXBlb2YgbWVzc2FnZS5tZWRpYUtleSA9PT0gJ29iamVjdCcgJiYgbWVzc2FnZS5tZWRpYUtleS5kYXRhKSB7XG4gICAgICAgIG1lc3NhZ2UubWVkaWFLZXkgPSBCdWZmZXIuZnJvbShtZXNzYWdlLm1lZGlhS2V5LmRhdGEpO1xuICAgICAgfSBlbHNlIGlmICh0eXBlb2YgbWVzc2FnZS5tZWRpYUtleSA9PT0gJ3N0cmluZycpIHtcbiAgICAgICAgbWVzc2FnZS5tZWRpYUtleSA9IEJ1ZmZlci5mcm9tKG1lc3NhZ2UubWVkaWFLZXksICdiYXNlNjQnKTtcbiAgICAgIH1cbiAgICB9IGVsc2Uge1xuICAgICAgdHJ5IHtcbiAgICAgICAgbWVzc2FnZSA9IGF3YWl0IGNsaWVudC5nZXRNZXNzYWdlQnlJZChtZXNzYWdlSWQpO1xuICAgICAgfSBjYXRjaCAoZXJyOiBhbnkpIHtcbiAgICAgICAgcmVxLmxvZ2dlci53YXJuKGBjbGllbnQuZ2V0TWVzc2FnZUJ5SWQgdGhyZXcgZXJyb3I6ICR7ZXJyLm1lc3NhZ2UgfHwgZXJyfS4gVHJ5aW5nIGZhbGxiYWNrLi4uYCk7XG4gICAgICB9XG5cbiAgICAgIC8vIEZhbGxiYWNrOiBJZiBtZXNzYWdlIGlzIG5vdCBmb3VuZCwgaXQgbWlnaHQgbm90IGJlIGxvYWRlZCBpbiB0aGUgV2hhdHNBcHAgV2ViIGNhY2hlLlxuICAgICAgLy8gVHJ5IHRvIHBhcnNlIHRoZSBjaGF0SWQgZnJvbSB0aGUgc2VyaWFsaXplZCBtZXNzYWdlSWQgKGZvcm1hdDogZnJvbU1lX2NoYXRJZF9tc2dJZF9wYXJ0aWNpcGFudClcbiAgICAgIC8vIGFuZCBsb2FkIGVhcmxpZXIgbWVzc2FnZXMgdG8gZm9yY2Ugc3luYyBpdC5cbiAgICAgIGlmICghbWVzc2FnZSAmJiBtZXNzYWdlSWQpIHtcbiAgICAgICAgY29uc3QgcGFydHMgPSBtZXNzYWdlSWQuc3BsaXQoJ18nKTtcbiAgICAgICAgaWYgKHBhcnRzLmxlbmd0aCA+PSAyKSB7XG4gICAgICAgICAgY29uc3QgY2hhdElkID0gcGFydHNbMV07IC8vIGUuZy4gMTIwMzYzNDIwOTQ4MTM0MDY1QGcudXMgb3IgcGhvbmVAYy51c1xuICAgICAgICAgIGlmIChjaGF0SWQpIHtcbiAgICAgICAgICAgIHJlcS5sb2dnZXIuaW5mbyhgTWVzc2FnZSAke21lc3NhZ2VJZH0gbm90IGZvdW5kIGluIGNhY2hlLiBBdHRlbXB0aW5nIFdQUC5jaGF0LmZpbmQgJiBsb2FkRWFybGllck1lc3NhZ2VzIGZvciAke2NoYXRJZH1gKTtcbiAgICAgICAgICAgIHRyeSB7XG4gICAgICAgICAgICAgIGlmIChjbGllbnQucGFnZSAmJiAhY2xpZW50LnBhZ2UuaXNDbG9zZWQoKSkge1xuICAgICAgICAgICAgICAgIG1lc3NhZ2UgPSBhd2FpdCBjbGllbnQucGFnZS5ldmFsdWF0ZShhc3luYyAoeyBtc2dJZCwgdGFyZ2V0Q2hhdElkIH0pID0+IHtcbiAgICAgICAgICAgICAgICAgIHRyeSB7XG4gICAgICAgICAgICAgICAgICAgIGNvbnN0IFdQUCA9ICh3aW5kb3cgYXMgYW55KS5XUFA7XG4gICAgICAgICAgICAgICAgICAgIGNvbnN0IFN0b3JlID0gKHdpbmRvdyBhcyBhbnkpLlN0b3JlO1xuXG4gICAgICAgICAgICAgICAgICAgIC8vIEhlbHBlciAxOiBDb252ZXJ0IHN0cmluZyBKSUQgdG8gV2lkIGlmIHBvc3NpYmxlXG4gICAgICAgICAgICAgICAgICAgIGxldCB0YXJnZXRXaWQgPSB0YXJnZXRDaGF0SWQ7XG4gICAgICAgICAgICAgICAgICAgIGlmIChXUFA/LndoYXRzYXBwPy5XaWRGYWN0b3J5Py5jcmVhdGUpIHtcbiAgICAgICAgICAgICAgICAgICAgICB0cnkge1xuICAgICAgICAgICAgICAgICAgICAgICAgdGFyZ2V0V2lkID0gV1BQLndoYXRzYXBwLldpZEZhY3RvcnkuY3JlYXRlKHRhcmdldENoYXRJZCk7XG4gICAgICAgICAgICAgICAgICAgICAgfSBjYXRjaCAoZSkge31cbiAgICAgICAgICAgICAgICAgICAgfVxuXG4gICAgICAgICAgICAgICAgICAgIC8vIEhlbHBlciAyOiBFbnN1cmUgY2hhdCBpcyBsb2FkZWRcbiAgICAgICAgICAgICAgICAgICAgaWYgKFdQUD8uY2hhdD8uZmluZCkge1xuICAgICAgICAgICAgICAgICAgICAgIHRyeSB7IGF3YWl0IFdQUC5jaGF0LmZpbmQodGFyZ2V0Q2hhdElkKTsgfSBjYXRjaCAoZSkge31cbiAgICAgICAgICAgICAgICAgICAgICB0cnkgeyBpZiAodGFyZ2V0V2lkICE9PSB0YXJnZXRDaGF0SWQpIGF3YWl0IFdQUC5jaGF0LmZpbmQodGFyZ2V0V2lkKTsgfSBjYXRjaCAoZSkge31cbiAgICAgICAgICAgICAgICAgICAgICB0cnkge1xuICAgICAgICAgICAgICAgICAgICAgICAgaWYgKHRhcmdldENoYXRJZC5pbmNsdWRlcygnQGMudXMnKSkge1xuICAgICAgICAgICAgICAgICAgICAgICAgICBhd2FpdCBXUFAuY2hhdC5maW5kKHRhcmdldENoYXRJZC5yZXBsYWNlKC9AY1xcLnVzL2csICdAcy53aGF0c2FwcC5uZXQnKSk7XG4gICAgICAgICAgICAgICAgICAgICAgICB9XG4gICAgICAgICAgICAgICAgICAgICAgfSBjYXRjaCAoZSkge31cbiAgICAgICAgICAgICAgICAgICAgfVxuXG4gICAgICAgICAgICAgICAgICAgIGlmIChXUFA/LmNoYXQ/LmxvYWRFYXJsaWVyTWVzc2FnZXMpIHtcbiAgICAgICAgICAgICAgICAgICAgICB0cnkgeyBhd2FpdCBXUFAuY2hhdC5sb2FkRWFybGllck1lc3NhZ2VzKHRhcmdldENoYXRJZCk7IH0gY2F0Y2ggKGUpIHt9XG4gICAgICAgICAgICAgICAgICAgIH1cblxuICAgICAgICAgICAgICAgICAgICAvLyBIZWxwZXIgMzogRGVlcCBzZWFyY2ggbWVzc2FnZVxuICAgICAgICAgICAgICAgICAgICBjb25zdCBnZXRNc2dTYWZlID0gYXN5bmMgKG1JZDogc3RyaW5nKSA9PiB7XG4gICAgICAgICAgICAgICAgICAgICAgaWYgKCFtSWQpIHJldHVybiBudWxsO1xuICAgICAgICAgICAgICAgICAgICAgIGlmIChXUFA/LmNoYXQ/LmdldE1lc3NhZ2VCeUlkKSB7XG4gICAgICAgICAgICAgICAgICAgICAgICB0cnkge1xuICAgICAgICAgICAgICAgICAgICAgICAgICBjb25zdCBtID0gYXdhaXQgV1BQLmNoYXQuZ2V0TWVzc2FnZUJ5SWQobUlkKTtcbiAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgKG0pIHJldHVybiBtO1xuICAgICAgICAgICAgICAgICAgICAgICAgfSBjYXRjaCAoZSkge31cbiAgICAgICAgICAgICAgICAgICAgICAgIHRyeSB7XG4gICAgICAgICAgICAgICAgICAgICAgICAgIGlmIChtSWQuaW5jbHVkZXMoJ0BjLnVzJykpIHtcbiAgICAgICAgICAgICAgICAgICAgICAgICAgICBjb25zdCBtID0gYXdhaXQgV1BQLmNoYXQuZ2V0TWVzc2FnZUJ5SWQobUlkLnJlcGxhY2UoL0BjXFwudXMvZywgJ0BzLndoYXRzYXBwLm5ldCcpKTtcbiAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiAobSkgcmV0dXJuIG07XG4gICAgICAgICAgICAgICAgICAgICAgICAgIH0gZWxzZSBpZiAobUlkLmluY2x1ZGVzKCdAcy53aGF0c2FwcC5uZXQnKSkge1xuICAgICAgICAgICAgICAgICAgICAgICAgICAgIGNvbnN0IG0gPSBhd2FpdCBXUFAuY2hhdC5nZXRNZXNzYWdlQnlJZChtSWQucmVwbGFjZSgvQHNcXC53aGF0c2FwcFxcLm5ldC9nLCAnQGMudXMnKSk7XG4gICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgKG0pIHJldHVybiBtO1xuICAgICAgICAgICAgICAgICAgICAgICAgICB9XG4gICAgICAgICAgICAgICAgICAgICAgICB9IGNhdGNoIChlKSB7fVxuICAgICAgICAgICAgICAgICAgICAgIH1cblxuICAgICAgICAgICAgICAgICAgICAgIC8vIEZhbGxiYWNrOiBzZWFyY2ggU3RvcmUuTXNnLm1vZGVscyBieSByYXcgbWVzc2FnZSBJRFxuICAgICAgICAgICAgICAgICAgICAgIGNvbnN0IHBhcnRzID0gbUlkLnNwbGl0KCdfJyk7XG4gICAgICAgICAgICAgICAgICAgICAgY29uc3QgcmF3SWQgPSBwYXJ0cy5sZW5ndGggPiAyID8gcGFydHNbMl0gOiBtSWQ7XG4gICAgICAgICAgICAgICAgICAgICAgaWYgKFN0b3JlPy5Nc2c/Lm1vZGVscykge1xuICAgICAgICAgICAgICAgICAgICAgICAgY29uc3QgZm91bmQgPSBTdG9yZS5Nc2cubW9kZWxzLmZpbmQoKGl0ZW06IGFueSkgPT4ge1xuICAgICAgICAgICAgICAgICAgICAgICAgICBpZiAoIWl0ZW0gfHwgIWl0ZW0uaWQpIHJldHVybiBmYWxzZTtcbiAgICAgICAgICAgICAgICAgICAgICAgICAgY29uc3Qgc2VyID0gaXRlbS5pZC5fc2VyaWFsaXplZCB8fCAnJztcbiAgICAgICAgICAgICAgICAgICAgICAgICAgY29uc3QgaXRlbUlkID0gaXRlbS5pZC5pZCB8fCAnJztcbiAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJuIGl0ZW1JZCA9PT0gcmF3SWQgfHwgc2VyID09PSBtSWQgfHwgKHJhd0lkICYmIHNlci5pbmNsdWRlcyhyYXdJZCkpO1xuICAgICAgICAgICAgICAgICAgICAgICAgfSk7XG4gICAgICAgICAgICAgICAgICAgICAgICBpZiAoZm91bmQpIHJldHVybiBmb3VuZDtcbiAgICAgICAgICAgICAgICAgICAgICB9XG4gICAgICAgICAgICAgICAgICAgICAgcmV0dXJuIG51bGw7XG4gICAgICAgICAgICAgICAgICAgIH07XG5cbiAgICAgICAgICAgICAgICAgICAgcmV0dXJuIGF3YWl0IGdldE1zZ1NhZmUobXNnSWQpO1xuICAgICAgICAgICAgICAgICAgfSBjYXRjaCAoZSkge1xuICAgICAgICAgICAgICAgICAgICBjb25zb2xlLmxvZyhgW2Jyb3dzZXItZXZhbHVhdGUgZ2V0TWVkaWFCeU1lc3NhZ2UgZmFsbGJhY2sgZXJyb3JdOiAke2V9YCk7XG4gICAgICAgICAgICAgICAgICAgIHJldHVybiBudWxsO1xuICAgICAgICAgICAgICAgICAgfVxuICAgICAgICAgICAgICAgIH0sIHsgbXNnSWQ6IG1lc3NhZ2VJZCwgdGFyZ2V0Q2hhdElkOiBjaGF0SWQgfSk7XG4gICAgICAgICAgICAgIH1cblxuICAgICAgICAgICAgICAvLyBTZWNvbmQgY2hlY2sgaWYgZXZhbHVhdGUgcmV0dXJuZWQgbnVsbCBidXQgY2xpZW50LmdldE1lc3NhZ2VCeUlkIG1pZ2h0IHdvcmsgbm93XG4gICAgICAgICAgICAgIGlmICghbWVzc2FnZSAmJiB0eXBlb2YgY2xpZW50LmdldE1lc3NhZ2VCeUlkID09PSAnZnVuY3Rpb24nKSB7XG4gICAgICAgICAgICAgICAgdHJ5IHtcbiAgICAgICAgICAgICAgICAgIG1lc3NhZ2UgPSBhd2FpdCBjbGllbnQuZ2V0TWVzc2FnZUJ5SWQobWVzc2FnZUlkKTtcbiAgICAgICAgICAgICAgICB9IGNhdGNoIChyZXRyeUVycjogYW55KSB7XG4gICAgICAgICAgICAgICAgICByZXEubG9nZ2VyLmVycm9yKGBSZXRyeSBnZXRNZXNzYWdlQnlJZCBmYWlsZWQ6ICR7cmV0cnlFcnIubWVzc2FnZSB8fCByZXRyeUVycn1gKTtcbiAgICAgICAgICAgICAgICB9XG4gICAgICAgICAgICAgIH1cbiAgICAgICAgICAgIH0gY2F0Y2ggKGxvYWRFcnIpIHtcbiAgICAgICAgICAgICAgcmVxLmxvZ2dlci5lcnJvcihgRXJyb3IgZXhlY3V0aW5nIGdldE1lZGlhQnlNZXNzYWdlIGZhbGxiYWNrOiAke2xvYWRFcnJ9YCk7XG4gICAgICAgICAgICB9XG4gICAgICAgICAgfVxuICAgICAgICB9XG4gICAgICB9XG4gICAgfVxuXG4gICAgaWYgKCFtZXNzYWdlKSB7XG4gICAgICByZXR1cm4gcmVzLnN0YXR1cyg0MDApLmpzb24oe1xuICAgICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICAgIG1lc3NhZ2U6IGBNZXNzYWdlICR7bWVzc2FnZUlkfSBub3QgZm91bmRgLFxuICAgICAgfSk7XG4gICAgfVxuXG4gICAgLy8gRW5zdXJlIGNsaWVudCBicm93c2VyIGNvbnRleHQgaXMgYWxpdmVcbiAgICBpZiAoY2xpZW50LnBhZ2UgJiYgY2xpZW50LnBhZ2UuaXNDbG9zZWQoKSkge1xuICAgICAgcmVxLmxvZ2dlci53YXJuKGBCcm93c2VyIHBhZ2UgaXMgY2xvc2VkIGZvciBzZXNzaW9uIHdoZW4gZG93bmxvYWRpbmcgbWVkaWEgJHttZXNzYWdlSWR9YCk7XG4gICAgICByZXR1cm4gcmVzLnN0YXR1cyg1MDMpLmpzb24oe1xuICAgICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICAgIG1lc3NhZ2U6ICdCcm93c2VyIHNlc3Npb24gaXMgY2xvc2VkIG9yIHJlLWNvbm5lY3RpbmcnLFxuICAgICAgfSk7XG4gICAgfVxuXG4gICAgLy8gRW5zdXJlIGl0IGNvbnRhaW5zIG1lZGlhIHByb3BlcnRpZXMgb3IgaGFzIG1pbWV0eXBlXG4gICAgY29uc3QgbWVkaWFVcmwgPSBtZXNzYWdlLmNsaWVudFVybCB8fCBtZXNzYWdlLmRlcHJlY2F0ZWRNbXMzVXJsO1xuICAgIGlmICghbWVkaWFVcmwpIHtcbiAgICAgIGlmICh0eXBlb2YgKGNsaWVudCBhcyBhbnkpLmRvd25sb2FkTWVkaWEgPT09ICdmdW5jdGlvbicgJiYgY2xpZW50LnBhZ2UgJiYgIWNsaWVudC5wYWdlLmlzQ2xvc2VkKCkpIHtcbiAgICAgICAgcmVxLmxvZ2dlci5pbmZvKGBNZXNzYWdlICR7bWVzc2FnZUlkfSBkb2VzIG5vdCBoYXZlIGNsaWVudFVybC4gVHJ5aW5nIGNsaWVudC5kb3dubG9hZE1lZGlhIHdpdGggNXMgdGltZW91dC4uLmApO1xuICAgICAgICB0cnkge1xuICAgICAgICAgIGxldCB0aW1lcjogYW55O1xuICAgICAgICAgIGNvbnN0IGRvd25sb2FkUHJvbWlzZSA9IChjbGllbnQgYXMgYW55KS5kb3dubG9hZE1lZGlhKG1lc3NhZ2VJZCkuY2F0Y2goKGVycjogYW55KSA9PiB7XG4gICAgICAgICAgICByZXEubG9nZ2VyLndhcm4oYGNsaWVudC5kb3dubG9hZE1lZGlhIGNhdWdodCBpbm5lciBlcnJvcjogJHtlcnJ9YCk7XG4gICAgICAgICAgICByZXR1cm4gbnVsbDtcbiAgICAgICAgICB9KS5maW5hbGx5KCgpID0+IHtcbiAgICAgICAgICAgIGlmICh0aW1lcikgY2xlYXJUaW1lb3V0KHRpbWVyKTtcbiAgICAgICAgICB9KTtcbiAgICAgICAgICBjb25zdCB0aW1lb3V0UHJvbWlzZSA9IG5ldyBQcm9taXNlPG51bGw+KChyZXNvbHZlKSA9PiB7XG4gICAgICAgICAgICB0aW1lciA9IHNldFRpbWVvdXQoKCkgPT4ge1xuICAgICAgICAgICAgICByZXEubG9nZ2VyLndhcm4oYFRpbWVvdXQgNTAwMG1zIHJlYWNoZWQgZm9yIGNsaWVudC5kb3dubG9hZE1lZGlhICgke21lc3NhZ2VJZH0pYCk7XG4gICAgICAgICAgICAgIHJlc29sdmUobnVsbCk7XG4gICAgICAgICAgICB9LCA1MDAwKTtcbiAgICAgICAgICB9KTtcbiAgICAgICAgICBsZXQgYmFzZTY0OiBzdHJpbmcgfCBudWxsID0gYXdhaXQgUHJvbWlzZS5yYWNlKFtkb3dubG9hZFByb21pc2UsIHRpbWVvdXRQcm9taXNlXSk7XG4gICAgICAgICAgaWYgKGJhc2U2NCkge1xuICAgICAgICAgICAgbGV0IG1pbWV0eXBlID0gbWVzc2FnZS5taW1ldHlwZSB8fCAnYXVkaW8vb2dnJztcbiAgICAgICAgICAgIGlmIChiYXNlNjQuc3RhcnRzV2l0aCgnZGF0YTonKSkge1xuICAgICAgICAgICAgICBjb25zdCBtYXRjaGVzID0gYmFzZTY0Lm1hdGNoKC9eZGF0YTooLio/KTtiYXNlNjQsKC4qKSQvKTtcbiAgICAgICAgICAgICAgaWYgKG1hdGNoZXMpIHtcbiAgICAgICAgICAgICAgICBtaW1ldHlwZSA9IG1hdGNoZXNbMV07XG4gICAgICAgICAgICAgICAgYmFzZTY0ID0gbWF0Y2hlc1syXTtcbiAgICAgICAgICAgICAgfVxuICAgICAgICAgICAgfVxuICAgICAgICAgICAgcmV0dXJuIHJlcy5zdGF0dXMoMjAwKS5qc29uKHsgYmFzZTY0LCBtaW1ldHlwZSB9KTtcbiAgICAgICAgICB9XG4gICAgICAgIH0gY2F0Y2ggKGRvd25sb2FkRXJyKSB7XG4gICAgICAgICAgcmVxLmxvZ2dlci5lcnJvcihgRXJyb3IgaW4gY2xpZW50LmRvd25sb2FkTWVkaWEgZmFsbGJhY2s6ICR7ZG93bmxvYWRFcnJ9YCk7XG4gICAgICAgIH1cbiAgICAgIH1cbiAgICAgIHJldHVybiByZXMuc3RhdHVzKDQwMCkuanNvbih7XG4gICAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgICAgbWVzc2FnZTogJ01lc3NhZ2UgZG9lcyBub3QgY29udGFpbiBtZWRpYSBkb3dubG9hZCBVUkwnLFxuICAgICAgfSk7XG4gICAgfVxuXG4gICAgdHJ5IHtcbiAgICAgIGNvbnN0IGJ1ZmZlciA9IGF3YWl0IGNsaWVudC5kZWNyeXB0RmlsZShtZXNzYWdlKTtcbiAgICAgIHJlc1xuICAgICAgICAuc3RhdHVzKDIwMClcbiAgICAgICAgLmpzb24oeyBiYXNlNjQ6IGJ1ZmZlci50b1N0cmluZygnYmFzZTY0JyksIG1pbWV0eXBlOiBtZXNzYWdlLm1pbWV0eXBlIHx8ICdhdWRpby9vZ2cnIH0pO1xuICAgIH0gY2F0Y2ggKGRlY3J5cHRFcnIpIHtcbiAgICAgIHJlcS5sb2dnZXIuZXJyb3IoYGRlY3J5cHRGaWxlIGZhaWxlZCAoQ0ROIGxpbmsgZXhwaXJlZCBvciBmb3JiaWRkZW4pLCBhdHRlbXB0aW5nIFdQUC5jaGF0LmRvd25sb2FkTWVkaWEgaW4gYnJvd3NlcjogJHtkZWNyeXB0RXJyfWApO1xuICAgICAgXG4gICAgICBpZiAoY2xpZW50LnBhZ2UgJiYgIWNsaWVudC5wYWdlLmlzQ2xvc2VkKCkpIHtcbiAgICAgICAgdHJ5IHtcbiAgICAgICAgICBjb25zdCByYXdCYXNlNjQgPSBhd2FpdCBjbGllbnQucGFnZS5ldmFsdWF0ZShhc3luYyAoeyBtSWQgfSkgPT4ge1xuICAgICAgICAgICAgdHJ5IHtcbiAgICAgICAgICAgICAgY29uc3QgV1BQID0gKHdpbmRvdyBhcyBhbnkpLldQUDtcbiAgICAgICAgICAgICAgaWYgKCFXUFA/LmNoYXQ/LmRvd25sb2FkTWVkaWEpIHJldHVybiBudWxsO1xuICAgICAgICAgICAgICBsZXQgYmxvYjogYW55ID0gbnVsbDtcbiAgICAgICAgICAgICAgdHJ5IHtcbiAgICAgICAgICAgICAgICBibG9iID0gYXdhaXQgV1BQLmNoYXQuZG93bmxvYWRNZWRpYShtSWQpO1xuICAgICAgICAgICAgICB9IGNhdGNoIChlKSB7XG4gICAgICAgICAgICAgICAgaWYgKG1JZC5pbmNsdWRlcygnQGMudXMnKSkge1xuICAgICAgICAgICAgICAgICAgdHJ5IHsgYmxvYiA9IGF3YWl0IFdQUC5jaGF0LmRvd25sb2FkTWVkaWEobUlkLnJlcGxhY2UoL0BjXFwudXMvZywgJ0BzLndoYXRzYXBwLm5ldCcpKTsgfSBjYXRjaCAoZTIpIHt9XG4gICAgICAgICAgICAgICAgfSBlbHNlIGlmIChtSWQuaW5jbHVkZXMoJ0BzLndoYXRzYXBwLm5ldCcpKSB7XG4gICAgICAgICAgICAgICAgICB0cnkgeyBibG9iID0gYXdhaXQgV1BQLmNoYXQuZG93bmxvYWRNZWRpYShtSWQucmVwbGFjZSgvQHNcXC53aGF0c2FwcFxcLm5ldC9nLCAnQGMudXMnKSk7IH0gY2F0Y2ggKGUyKSB7fVxuICAgICAgICAgICAgICAgIH1cbiAgICAgICAgICAgICAgfVxuICAgICAgICAgICAgICBpZiAoYmxvYikge1xuICAgICAgICAgICAgICAgIGlmIChXUFA/LnV0aWw/LmJsb2JUb0Jhc2U2NCkge1xuICAgICAgICAgICAgICAgICAgcmV0dXJuIGF3YWl0IFdQUC51dGlsLmJsb2JUb0Jhc2U2NChibG9iKTtcbiAgICAgICAgICAgICAgICB9XG4gICAgICAgICAgICAgICAgcmV0dXJuIG5ldyBQcm9taXNlKChyZXNvbHZlKSA9PiB7XG4gICAgICAgICAgICAgICAgICBjb25zdCByZWFkZXIgPSBuZXcgRmlsZVJlYWRlcigpO1xuICAgICAgICAgICAgICAgICAgcmVhZGVyLm9ubG9hZGVuZCA9ICgpID0+IHJlc29sdmUocmVhZGVyLnJlc3VsdCk7XG4gICAgICAgICAgICAgICAgICByZWFkZXIub25lcnJvciA9ICgpID0+IHJlc29sdmUobnVsbCk7XG4gICAgICAgICAgICAgICAgICByZWFkZXIucmVhZEFzRGF0YVVSTChibG9iKTtcbiAgICAgICAgICAgICAgICB9KTtcbiAgICAgICAgICAgICAgfVxuICAgICAgICAgICAgICByZXR1cm4gbnVsbDtcbiAgICAgICAgICAgIH0gY2F0Y2ggKGUpIHtcbiAgICAgICAgICAgICAgY29uc29sZS5sb2coYFticm93c2VyLWV2YWx1YXRlIGRvd25sb2FkTWVkaWEgZXJyb3JdOiAke2V9YCk7XG4gICAgICAgICAgICAgIHJldHVybiBudWxsO1xuICAgICAgICAgICAgfVxuICAgICAgICAgIH0sIHsgbUlkOiBtZXNzYWdlSWQgfSk7XG5cbiAgICAgICAgICBpZiAocmF3QmFzZTY0ICYmIHR5cGVvZiByYXdCYXNlNjQgPT09ICdzdHJpbmcnKSB7XG4gICAgICAgICAgICBsZXQgbWltZXR5cGUgPSBtZXNzYWdlLm1pbWV0eXBlIHx8ICdhdWRpby9vZ2cnO1xuICAgICAgICAgICAgbGV0IGJhc2U2NCA9IHJhd0Jhc2U2NDtcbiAgICAgICAgICAgIGlmIChyYXdCYXNlNjQuc3RhcnRzV2l0aCgnZGF0YTonKSkge1xuICAgICAgICAgICAgICBjb25zdCBtYXRjaGVzID0gcmF3QmFzZTY0Lm1hdGNoKC9eZGF0YTooLio/KTtiYXNlNjQsKC4qKSQvKTtcbiAgICAgICAgICAgICAgaWYgKG1hdGNoZXMpIHtcbiAgICAgICAgICAgICAgICBtaW1ldHlwZSA9IG1hdGNoZXNbMV07XG4gICAgICAgICAgICAgICAgYmFzZTY0ID0gbWF0Y2hlc1syXTtcbiAgICAgICAgICAgICAgfVxuICAgICAgICAgICAgfVxuICAgICAgICAgICAgcmVxLmxvZ2dlci5pbmZvKGBTdWNjZXNzZnVsbHkgZG93bmxvYWRlZCBtZWRpYSB2aWEgYnJvd3NlciBXUFAuY2hhdC5kb3dubG9hZE1lZGlhIGZvciAke21lc3NhZ2VJZH0hIGJhc2U2NCBsZW49JHtiYXNlNjQubGVuZ3RofWApO1xuICAgICAgICAgICAgcmV0dXJuIHJlcy5zdGF0dXMoMjAwKS5qc29uKHsgYmFzZTY0LCBtaW1ldHlwZSB9KTtcbiAgICAgICAgICB9XG4gICAgICAgIH0gY2F0Y2ggKGJyb3dzZXJFcnIpIHtcbiAgICAgICAgICByZXEubG9nZ2VyLmVycm9yKGBCcm93c2VyIFdQUC5jaGF0LmRvd25sb2FkTWVkaWEgZmFsbGJhY2sgZXJyb3I6ICR7YnJvd3NlckVycn1gKTtcbiAgICAgICAgfVxuICAgICAgfVxuXG4gICAgICAvLyBTZWNvbmRhcnkgZmFsbGJhY2sgdG8gV1BQQ29ubmVjdCdzIGRvd25sb2FkTWVkaWFcbiAgICAgIGlmICh0eXBlb2YgKGNsaWVudCBhcyBhbnkpLmRvd25sb2FkTWVkaWEgPT09ICdmdW5jdGlvbicgJiYgY2xpZW50LnBhZ2UgJiYgIWNsaWVudC5wYWdlLmlzQ2xvc2VkKCkpIHtcbiAgICAgICAgdHJ5IHtcbiAgICAgICAgICBsZXQgdGltZXI6IGFueTtcbiAgICAgICAgICBjb25zdCBkb3dubG9hZFByb21pc2UgPSAoY2xpZW50IGFzIGFueSkuZG93bmxvYWRNZWRpYShtZXNzYWdlSWQpLmNhdGNoKChlcnI6IGFueSkgPT4ge1xuICAgICAgICAgICAgcmVxLmxvZ2dlci53YXJuKGBjbGllbnQuZG93bmxvYWRNZWRpYSBjYXVnaHQgaW5uZXIgZXJyb3I6ICR7ZXJyfWApO1xuICAgICAgICAgICAgcmV0dXJuIG51bGw7XG4gICAgICAgICAgfSkuZmluYWxseSgoKSA9PiB7XG4gICAgICAgICAgICBpZiAodGltZXIpIGNsZWFyVGltZW91dCh0aW1lcik7XG4gICAgICAgICAgfSk7XG4gICAgICAgICAgY29uc3QgdGltZW91dFByb21pc2UgPSBuZXcgUHJvbWlzZTxudWxsPigocmVzb2x2ZSkgPT4ge1xuICAgICAgICAgICAgdGltZXIgPSBzZXRUaW1lb3V0KCgpID0+IHtcbiAgICAgICAgICAgICAgcmVxLmxvZ2dlci53YXJuKGBUaW1lb3V0IDE1MDAwbXMgcmVhY2hlZCBmb3IgY2xpZW50LmRvd25sb2FkTWVkaWEgKCR7bWVzc2FnZUlkfSlgKTtcbiAgICAgICAgICAgICAgcmVzb2x2ZShudWxsKTtcbiAgICAgICAgICAgIH0sIDE1MDAwKTtcbiAgICAgICAgICB9KTtcbiAgICAgICAgICBsZXQgYmFzZTY0OiBzdHJpbmcgfCBudWxsID0gYXdhaXQgUHJvbWlzZS5yYWNlKFtkb3dubG9hZFByb21pc2UsIHRpbWVvdXRQcm9taXNlXSk7XG4gICAgICAgICAgaWYgKGJhc2U2NCkge1xuICAgICAgICAgICAgbGV0IG1pbWV0eXBlID0gbWVzc2FnZS5taW1ldHlwZSB8fCAnYXVkaW8vb2dnJztcbiAgICAgICAgICAgIGlmIChiYXNlNjQuc3RhcnRzV2l0aCgnZGF0YTonKSkge1xuICAgICAgICAgICAgICBjb25zdCBtYXRjaGVzID0gYmFzZTY0Lm1hdGNoKC9eZGF0YTooLio/KTtiYXNlNjQsKC4qKSQvKTtcbiAgICAgICAgICAgICAgaWYgKG1hdGNoZXMpIHtcbiAgICAgICAgICAgICAgICBtaW1ldHlwZSA9IG1hdGNoZXNbMV07XG4gICAgICAgICAgICAgICAgYmFzZTY0ID0gbWF0Y2hlc1syXTtcbiAgICAgICAgICAgICAgfVxuICAgICAgICAgICAgfVxuICAgICAgICAgICAgcmV0dXJuIHJlcy5zdGF0dXMoMjAwKS5qc29uKHsgYmFzZTY0LCBtaW1ldHlwZSB9KTtcbiAgICAgICAgICB9XG4gICAgICAgIH0gY2F0Y2ggKGRvd25sb2FkRXJyKSB7XG4gICAgICAgICAgcmVxLmxvZ2dlci5lcnJvcihgRXJyb3IgaW4gY2xpZW50LmRvd25sb2FkTWVkaWEgZmFsbGJhY2sgYWZ0ZXIgZGVjcnlwdGlvbiBlcnJvcjogJHtkb3dubG9hZEVycn1gKTtcbiAgICAgICAgfVxuICAgICAgfVxuICAgICAgdGhyb3cgZGVjcnlwdEVycjsgLy8gcmV0aHJvdyB0byB0cmlnZ2VyIHRoZSA1MDAgYmxvY2sgaWYgYm90aCBmYWlsZWRcbiAgICB9XG4gIH0gY2F0Y2ggKGV4KSB7XG4gICAgcmVxLmxvZ2dlci5lcnJvcihleCk7XG4gICAgcmVzLnN0YXR1cyg1MDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgbWVzc2FnZTogJ0ZhaWxlZCB0byBkZWNyeXB0IGZpbGUnLFxuICAgICAgZXJyb3I6IGV4IGluc3RhbmNlb2YgRXJyb3IgPyBleC5tZXNzYWdlIDogZXgsXG4gICAgfSk7XG4gIH1cbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIGdldFNlc3Npb25TdGF0ZShyZXE6IFJlcXVlc3QsIHJlczogUmVzcG9uc2UpIHtcbiAgLyoqXG4gICAgICNzd2FnZ2VyLnRhZ3MgPSBbXCJBdXRoXCJdXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ2dldFNlc3Npb25TdGF0ZSdcbiAgICAgI3N3YWdnZXIuc3VtbWFyeSA9ICdSZXRyaWV2ZSBzdGF0dXMgb2YgYSBzZXNzaW9uJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keSA9IGZhbHNlXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAqL1xuICB0cnkge1xuICAgIGNvbnN0IHsgd2FpdFFyQ29kZSA9IGZhbHNlIH0gPSByZXEuYm9keTtcbiAgICBjb25zdCBjbGllbnQgPSByZXEuY2xpZW50O1xuICAgIGNvbnN0IHFyID1cbiAgICAgIGNsaWVudD8udXJsY29kZSAhPSBudWxsICYmIGNsaWVudD8udXJsY29kZSAhPSAnJ1xuICAgICAgICA/IGF3YWl0IFFSQ29kZS50b0RhdGFVUkwoY2xpZW50LnVybGNvZGUpXG4gICAgICAgIDogbnVsbDtcblxuICAgIGlmICgoY2xpZW50ID09IG51bGwgfHwgY2xpZW50LnN0YXR1cyA9PSBudWxsKSAmJiAhd2FpdFFyQ29kZSlcbiAgICAgIHJlcy5zdGF0dXMoMjAwKS5qc29uKHsgc3RhdHVzOiAnQ0xPU0VEJywgcXJjb2RlOiBudWxsIH0pO1xuICAgIGVsc2UgaWYgKGNsaWVudCAhPSBudWxsKVxuICAgICAgcmVzLnN0YXR1cygyMDApLmpzb24oe1xuICAgICAgICBzdGF0dXM6IGNsaWVudC5zdGF0dXMsXG4gICAgICAgIHFyY29kZTogcXIsXG4gICAgICAgIHVybGNvZGU6IGNsaWVudC51cmxjb2RlLFxuICAgICAgICB2ZXJzaW9uOiB2ZXJzaW9uLFxuICAgICAgfSk7XG4gIH0gY2F0Y2ggKGV4KSB7XG4gICAgcmVxLmxvZ2dlci5lcnJvcihleCk7XG4gICAgcmVzLnN0YXR1cyg1MDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgbWVzc2FnZTogJ1RoZSBzZXNzaW9uIGlzIG5vdCBhY3RpdmUnLFxuICAgICAgZXJyb3I6IGV4LFxuICAgIH0pO1xuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBnZXRRckNvZGUocmVxOiBSZXF1ZXN0LCByZXM6IFJlc3BvbnNlKSB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiQXV0aFwiXVxuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5vcGVyYXRpb25JZCA9ICdnZXRRckNvZGUnXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAqL1xuICB0cnkge1xuICAgIGlmIChyZXE/LmNsaWVudD8udXJsY29kZSkge1xuICAgICAgLy8gV2UgYWRkIG9wdGlvbnMgdG8gZ2VuZXJhdGUgdGhlIFFSIGNvZGUgaW4gaGlnaGVyIHJlc29sdXRpb25cbiAgICAgIC8vIFRoZSAvcXJjb2RlLXNlc3Npb24gcmVxdWVzdCB3aWxsIG5vdyByZXR1cm4gYSByZWFkYWJsZSBxcmNvZGUuXG4gICAgICBjb25zdCBxck9wdGlvbnMgPSB7XG4gICAgICAgIGVycm9yQ29ycmVjdGlvbkxldmVsOiAnTScgYXMgY29uc3QsXG4gICAgICAgIHR5cGU6ICdpbWFnZS9wbmcnIGFzIGNvbnN0LFxuICAgICAgICBzY2FsZTogNSxcbiAgICAgICAgd2lkdGg6IDUwMCxcbiAgICAgIH07XG4gICAgICBjb25zdCBxciA9IHJlcS5jbGllbnQudXJsY29kZVxuICAgICAgICA/IGF3YWl0IFFSQ29kZS50b0RhdGFVUkwocmVxLmNsaWVudC51cmxjb2RlLCBxck9wdGlvbnMpXG4gICAgICAgIDogbnVsbDtcbiAgICAgIGNvbnN0IGltZyA9IEJ1ZmZlci5mcm9tKFxuICAgICAgICAocXIgYXMgYW55KS5yZXBsYWNlKC9eZGF0YTppbWFnZVxcLyhwbmd8anBlZ3xqcGcpO2Jhc2U2NCwvLCAnJyksXG4gICAgICAgICdiYXNlNjQnXG4gICAgICApO1xuICAgICAgcmVzLndyaXRlSGVhZCgyMDAsIHtcbiAgICAgICAgJ0NvbnRlbnQtVHlwZSc6ICdpbWFnZS9wbmcnLFxuICAgICAgICAnQ29udGVudC1MZW5ndGgnOiBpbWcubGVuZ3RoLFxuICAgICAgfSk7XG4gICAgICByZXMuZW5kKGltZyk7XG4gICAgfSBlbHNlIGlmICh0eXBlb2YgcmVxLmNsaWVudCA9PT0gJ3VuZGVmaW5lZCcpIHtcbiAgICAgIHJlcy5zdGF0dXMoMjAwKS5qc29uKHtcbiAgICAgICAgc3RhdHVzOiBudWxsLFxuICAgICAgICBtZXNzYWdlOlxuICAgICAgICAgICdTZXNzaW9uIG5vdCBzdGFydGVkLiBQbGVhc2UsIHVzZSB0aGUgL3N0YXJ0LXNlc3Npb24gcm91dGUsIGZvciBpbml0aWFsaXphdGlvbiB5b3VyIHNlc3Npb24nLFxuICAgICAgfSk7XG4gICAgfSBlbHNlIHtcbiAgICAgIHJlcy5zdGF0dXMoMjAwKS5qc29uKHtcbiAgICAgICAgc3RhdHVzOiByZXEuY2xpZW50LnN0YXR1cyxcbiAgICAgICAgbWVzc2FnZTogJ1FSQ29kZSBpcyBub3QgYXZhaWxhYmxlLi4uJyxcbiAgICAgIH0pO1xuICAgIH1cbiAgfSBjYXRjaCAoZXgpIHtcbiAgICByZXEubG9nZ2VyLmVycm9yKGV4KTtcbiAgICByZXNcbiAgICAgIC5zdGF0dXMoNTAwKVxuICAgICAgLmpzb24oeyBzdGF0dXM6ICdlcnJvcicsIG1lc3NhZ2U6ICdFcnJvciByZXRyaWV2aW5nIFFSQ29kZScsIGVycm9yOiBleCB9KTtcbiAgfVxufVxuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24ga2lsbFNlcnZpY2VXb3JrZXIocmVxOiBSZXF1ZXN0LCByZXM6IFJlc3BvbnNlKSB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci5pZ25vcmU9dHJ1ZVxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiTWVzc2FnZXNcIl1cbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAna2lsbFNlcnZpY2VXb3JraWVyJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgKi9cbiAgdHJ5IHtcbiAgICByZXMuc3RhdHVzKDIwMCkuanNvbih7IHN0YXR1czogJ2Vycm9yJywgcmVzcG9uc2U6ICdOb3QgaW1wbGVtZW50ZWQgeWV0JyB9KTtcbiAgfSBjYXRjaCAoZXgpIHtcbiAgICByZXEubG9nZ2VyLmVycm9yKGV4KTtcbiAgICByZXMuc3RhdHVzKDUwMCkuanNvbih7XG4gICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICBtZXNzYWdlOiAnVGhlIHNlc3Npb24gaXMgbm90IGFjdGl2ZScsXG4gICAgICBlcnJvcjogZXgsXG4gICAgfSk7XG4gIH1cbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIHJlc3RhcnRTZXJ2aWNlKHJlcTogUmVxdWVzdCwgcmVzOiBSZXNwb25zZSkge1xuICAvKipcbiAgICogI3N3YWdnZXIuaWdub3JlPXRydWVcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIk1lc3NhZ2VzXCJdXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ3Jlc3RhcnRTZXJ2aWNlJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgKi9cbiAgdHJ5IHtcbiAgICByZXMuc3RhdHVzKDIwMCkuanNvbih7IHN0YXR1czogJ2Vycm9yJywgcmVzcG9uc2U6ICdOb3QgaW1wbGVtZW50ZWQgeWV0JyB9KTtcbiAgfSBjYXRjaCAoZXgpIHtcbiAgICByZXEubG9nZ2VyLmVycm9yKGV4KTtcbiAgICByZXMuc3RhdHVzKDUwMCkuanNvbih7XG4gICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICByZXNwb25zZTogeyBtZXNzYWdlOiAnVGhlIHNlc3Npb24gaXMgbm90IGFjdGl2ZScsIGVycm9yOiBleCB9LFxuICAgIH0pO1xuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBzdWJzY3JpYmVQcmVzZW5jZShyZXE6IFJlcXVlc3QsIHJlczogUmVzcG9uc2UpIHtcbiAgLyoqXG4gICAqICNzd2FnZ2VyLnRhZ3MgPSBbXCJNaXNjXCJdXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ3N1YnNjcmliZVByZXNlbmNlJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgICAjc3dhZ2dlci5yZXF1ZXN0Qm9keSA9IHtcbiAgICAgIHJlcXVpcmVkOiB0cnVlLFxuICAgICAgXCJAY29udGVudFwiOiB7XG4gICAgICAgIFwiYXBwbGljYXRpb24vanNvblwiOiB7XG4gICAgICAgICAgc2NoZW1hOiB7XG4gICAgICAgICAgICB0eXBlOiBcIm9iamVjdFwiLFxuICAgICAgICAgICAgcHJvcGVydGllczoge1xuICAgICAgICAgICAgICBwaG9uZTogeyB0eXBlOiBcInN0cmluZ1wiIH0sXG4gICAgICAgICAgICAgIGlzR3JvdXA6IHsgdHlwZTogXCJib29sZWFuXCIgfSxcbiAgICAgICAgICAgICAgYWxsOiB7IHR5cGU6IFwiYm9vbGVhblwiIH0sXG4gICAgICAgICAgICB9XG4gICAgICAgICAgfSxcbiAgICAgICAgICBleGFtcGxlOiB7XG4gICAgICAgICAgICBwaG9uZTogJzU1MjE5OTk5OTk5OTknLFxuICAgICAgICAgICAgaXNHcm91cDogZmFsc2UsXG4gICAgICAgICAgICBhbGw6IGZhbHNlLFxuICAgICAgICAgIH1cbiAgICAgICAgfVxuICAgICAgfVxuICAgICB9XG4gICAqL1xuICB0cnkge1xuICAgIGNvbnN0IHsgcGhvbmUsIGlzR3JvdXAgPSBmYWxzZSwgYWxsID0gZmFsc2UsIGlzTGlkID0gZmFsc2UgfSA9IHJlcS5ib2R5O1xuXG4gICAgY29uc3Qgc3Vic2NyaWJlT25lID0gYXN5bmMgKGNvbnRhdG86IHN0cmluZykgPT4ge1xuICAgICAgLy8gUHJlZmVyIHRoZSBtb2Rlcm4gV1BQLmNvbnRhY3Quc3Vic2NyaWJlUHJlc2VuY2Ugd2hpY2ggd29ya3Mgd2l0aFxuICAgICAgLy8gY3VycmVudCBXaGF0c0FwcCBXZWIuIFRoZSBsZWdhY3kgcmVxLmNsaWVudC5zdWJzY3JpYmVQcmVzZW5jZSB1c2VzXG4gICAgICAvLyB0aGUgaW50ZXJuYWwgV0FQSSB0aGF0IGNhbGxzIFN0b3JlLlByZXNlbmNlLmZpbmQoKSDigJQgYnJva2VuIGluIG5ld2VyXG4gICAgICAvLyBXQSB2ZXJzaW9ucyBhbmQgcmV0dXJucyA1MDAuIFdlIGZhbGwgYmFjayB0byB0aGUgbGVnYWN5IHBhdGggaWYgdGhlXG4gICAgICAvLyBXUFAgQVBJIGlzIG5vdCBhdmFpbGFibGUuXG4gICAgICBjb25zdCBwYWdlID0gKHJlcS5jbGllbnQgYXMgYW55KS5wYWdlO1xuICAgICAgaWYgKHBhZ2UpIHtcbiAgICAgICAgdHJ5IHtcbiAgICAgICAgICBhd2FpdCBwYWdlLmV2YWx1YXRlKChpZDogc3RyaW5nKSA9PiB7XG4gICAgICAgICAgICBjb25zdCB3cHAgPSAod2luZG93IGFzIGFueSkuV1BQO1xuICAgICAgICAgICAgaWYgKHdwcCAmJiB3cHAuY29udGFjdCAmJiB0eXBlb2Ygd3BwLmNvbnRhY3Quc3Vic2NyaWJlUHJlc2VuY2UgPT09ICdmdW5jdGlvbicpIHtcbiAgICAgICAgICAgICAgcmV0dXJuIHdwcC5jb250YWN0LnN1YnNjcmliZVByZXNlbmNlKGlkKTtcbiAgICAgICAgICAgIH1cbiAgICAgICAgICAgIC8vIEZhbGxiYWNrIHRvIFdQUC53aGF0c2FwcC5QcmVzZW5jZVV0aWxzIGlmIGF2YWlsYWJsZVxuICAgICAgICAgICAgaWYgKHdwcCAmJiB3cHAud2hhdHNhcHAgJiYgd3BwLndoYXRzYXBwLlByZXNlbmNlVXRpbHMpIHtcbiAgICAgICAgICAgICAgcmV0dXJuIHdwcC53aGF0c2FwcC5QcmVzZW5jZVV0aWxzLnN1YnNjcmliZVRvUHJlc2VuY2UoaWQpO1xuICAgICAgICAgICAgfVxuICAgICAgICAgICAgdGhyb3cgbmV3IEVycm9yKCdXUFAuY29udGFjdC5zdWJzY3JpYmVQcmVzZW5jZSBub3QgYXZhaWxhYmxlJyk7XG4gICAgICAgICAgfSwgY29udGF0byk7XG4gICAgICAgICAgcmVxLmxvZ2dlci5pbmZvKGBbc3Vic2NyaWJlUHJlc2VuY2VdIFdQUCBzdWJzY3JpYmVkOiAke2NvbnRhdG99YCk7XG4gICAgICAgICAgcmV0dXJuO1xuICAgICAgICB9IGNhdGNoICh3cHBFcnIpIHtcbiAgICAgICAgICByZXEubG9nZ2VyLndhcm4oYFtzdWJzY3JpYmVQcmVzZW5jZV0gV1BQIGZhbGxiYWNrIGZvciAke2NvbnRhdG99OiAke3dwcEVycn1gKTtcbiAgICAgICAgfVxuICAgICAgfVxuICAgICAgLy8gTGVnYWN5IGZhbGxiYWNrXG4gICAgICBhd2FpdCByZXEuY2xpZW50LnN1YnNjcmliZVByZXNlbmNlKGNvbnRhdG8pO1xuICAgIH07XG5cbiAgICBpZiAoYWxsKSB7XG4gICAgICBsZXQgY29udGFjdHM7XG4gICAgICBpZiAoaXNHcm91cCkge1xuICAgICAgICBjb25zdCBncm91cHMgPSBhd2FpdCByZXEuY2xpZW50LmdldEFsbEdyb3VwcyhmYWxzZSk7XG4gICAgICAgIGNvbnRhY3RzID0gZ3JvdXBzLm1hcCgocDogYW55KSA9PiBwLmlkLl9zZXJpYWxpemVkKTtcbiAgICAgIH0gZWxzZSB7XG4gICAgICAgIGNvbnN0IGNoYXRzID0gYXdhaXQgcmVxLmNsaWVudC5nZXRBbGxDb250YWN0cygpO1xuICAgICAgICBjb250YWN0cyA9IGNoYXRzLm1hcCgoYzogYW55KSA9PiBjLmlkLl9zZXJpYWxpemVkKTtcbiAgICAgIH1cbiAgICAgIGZvciAoY29uc3QgY29udGF0byBvZiBjb250YWN0cykge1xuICAgICAgICBhd2FpdCBzdWJzY3JpYmVPbmUoY29udGF0byk7XG4gICAgICB9XG4gICAgfSBlbHNlIHtcbiAgICAgIGZvciAoY29uc3QgY29udGF0byBvZiBjb250YWN0VG9BcnJheShwaG9uZSwgaXNHcm91cCwgZmFsc2UsIGlzTGlkKSkge1xuICAgICAgICBhd2FpdCBzdWJzY3JpYmVPbmUoY29udGF0byk7XG4gICAgICB9XG4gICAgfVxuXG4gICAgcmVzLnN0YXR1cygyMDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnc3VjY2VzcycsXG4gICAgICByZXNwb25zZTogeyBtZXNzYWdlOiAnU3Vic2NyaWJlIHByZXNlbmNlIGV4ZWN1dGVkJyB9LFxuICAgIH0pO1xuICB9IGNhdGNoIChlcnJvcikge1xuICAgIHJlcS5sb2dnZXIuZXJyb3IoZXJyb3IpO1xuICAgIHJlcy5zdGF0dXMoNTAwKS5qc29uKHtcbiAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgIG1lc3NhZ2U6ICdFcnJvciBvbiBzdWJzY3JpYmUgcHJlc2VuY2UnLFxuICAgICAgZXJyb3I6IGVycm9yLFxuICAgIH0pO1xuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBzZXRPbmxpbmVQcmVzZW5jZShyZXE6IFJlcXVlc3QsIHJlczogUmVzcG9uc2UpIHtcbiAgLyoqXG4gICAqICNzd2FnZ2VyLnRhZ3MgPSBbXCJNaXNjXCJdXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ3NldE9ubGluZVByZXNlbmNlJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgICAjc3dhZ2dlci5yZXF1ZXN0Qm9keSA9IHtcbiAgICAgIHJlcXVpcmVkOiB0cnVlLFxuICAgICAgXCJAY29udGVudFwiOiB7XG4gICAgICAgIFwiYXBwbGljYXRpb24vanNvblwiOiB7XG4gICAgICAgICAgc2NoZW1hOiB7XG4gICAgICAgICAgICB0eXBlOiBcIm9iamVjdFwiLFxuICAgICAgICAgICAgcHJvcGVydGllczoge1xuICAgICAgICAgICAgICBpc09ubGluZTogeyB0eXBlOiBcImJvb2xlYW5cIiB9LFxuICAgICAgICAgICAgfVxuICAgICAgICAgIH0sXG4gICAgICAgICAgZXhhbXBsZToge1xuICAgaXNPbmxpbmU6IGZhbHNlLFxuICAgICAgICAgIH1cbiAgICAgICAgfVxuICAgICAgfVxuICAgICB9XG4gICAqL1xuICB0cnkge1xuICAgIGNvbnN0IHsgaXNPbmxpbmUgPSB0cnVlIH0gPSByZXEuYm9keTtcblxuICAgIGF3YWl0IHJlcS5jbGllbnQuc2V0T25saW5lUHJlc2VuY2UoaXNPbmxpbmUpO1xuXG4gICAgcmVzLnN0YXR1cygyMDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnc3VjY2VzcycsXG4gICAgICByZXNwb25zZTogeyBtZXNzYWdlOiAnU2V0IE9ubGluZSBQcmVzZW5jZSBTdWNjZXNzZnVsbHknIH0sXG4gICAgfSk7XG4gIH0gY2F0Y2ggKGVycm9yKSB7XG4gICAgcmVzLnN0YXR1cyg1MDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgbWVzc2FnZTogJ0Vycm9yIG9uIHNldCBvbmxpbmUgcHJlc2VuY2UnLFxuICAgICAgZXJyb3I6IGVycm9yLFxuICAgIH0pO1xuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBlZGl0QnVzaW5lc3NQcm9maWxlKHJlcTogUmVxdWVzdCwgcmVzOiBSZXNwb25zZSkge1xuICAvKipcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIlByb2ZpbGVcIl1cbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAnZWRpdEJ1c2luZXNzUHJvZmlsZSdcbiAgICogI3N3YWdnZXIuZGVzY3JpcHRpb24gPSAnRWRpdCB5b3VyIGJ1c3NpbmVzcyBwcm9maWxlJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wib2JqXCJdID0ge1xuICAgICAgaW46ICdib2R5JyxcbiAgICAgIHNjaGVtYToge1xuICAgICAgICAkYWRyZXNzOiAnQXYuIE5vc3NhIFNlbmhvcmEgZGUgQ29wYWNhYmFuYSwgMzE1JyxcbiAgICAgICAgJGVtYWlsOiAndGVzdEB0ZXN0LmNvbS5icicsXG4gICAgICAgICRjYXRlZ29yaWVzOiB7XG4gICAgICAgICAgJGlkOiBcIjEzMzQzNjc0MzM4ODIxN1wiLFxuICAgICAgICAgICRsb2NhbGl6ZWRfZGlzcGxheV9uYW1lOiBcIkFydGVzIGUgZW50cmV0ZW5pbWVudG9cIixcbiAgICAgICAgICAkbm90X2FfYml6OiBmYWxzZSxcbiAgICAgICAgfSxcbiAgICAgICAgJHdlYnNpdGU6IFtcbiAgICAgICAgICBcImh0dHBzOi8vd3d3LndwcGNvbm5lY3QuaW9cIixcbiAgICAgICAgICBcImh0dHBzOi8vd3d3LnRlc3RlMi5jb20uYnJcIixcbiAgICAgICAgXSxcbiAgICAgIH1cbiAgICAgfVxuICAgICBcbiAgICAgI3N3YWdnZXIucmVxdWVzdEJvZHkgPSB7XG4gICAgICByZXF1aXJlZDogdHJ1ZSxcbiAgICAgIFwiQGNvbnRlbnRcIjoge1xuICAgICAgICBcImFwcGxpY2F0aW9uL2pzb25cIjoge1xuICAgICAgICAgIHNjaGVtYToge1xuICAgICAgICAgICAgdHlwZTogXCJvYmplY3RcIixcbiAgICAgICAgICAgIHByb3BlcnRpZXM6IHtcbiAgICAgICAgICAgICAgYWRyZXNzOiB7IHR5cGU6IFwic3RyaW5nXCIgfSxcbiAgICAgICAgICAgICAgZW1haWw6IHsgdHlwZTogXCJzdHJpbmdcIiB9LFxuICAgICAgICAgICAgICBjYXRlZ29yaWVzOiB7IHR5cGU6IFwib2JqZWN0XCIgfSxcbiAgICAgICAgICAgICAgd2Vic2l0ZXM6IHsgdHlwZTogXCJhcnJheVwiIH0sXG4gICAgICAgICAgICB9XG4gICAgICAgICAgfSxcbiAgICAgICAgICBleGFtcGxlOiB7XG4gICAgICAgICAgICBhZHJlc3M6ICdBdi4gTm9zc2EgU2VuaG9yYSBkZSBDb3BhY2FiYW5hLCAzMTUnLFxuICAgICAgICAgICAgZW1haWw6ICd0ZXN0QHRlc3QuY29tLmJyJyxcbiAgICAgICAgICAgIGNhdGVnb3JpZXM6IHtcbiAgICAgICAgICAgICAgJGlkOiBcIjEzMzQzNjc0MzM4ODIxN1wiLFxuICAgICAgICAgICAgICAkbG9jYWxpemVkX2Rpc3BsYXlfbmFtZTogXCJBcnRlcyBlIGVudHJldGVuaW1lbnRvXCIsXG4gICAgICAgICAgICAgICRub3RfYV9iaXo6IGZhbHNlLFxuICAgICAgICAgICAgfSxcbiAgICAgICAgICAgIHdlYnNpdGU6IFtcbiAgICAgICAgICAgICAgXCJodHRwczovL3d3dy53cHBjb25uZWN0LmlvXCIsXG4gICAgICAgICAgICAgIFwiaHR0cHM6Ly93d3cudGVzdGUyLmNvbS5iclwiLFxuICAgICAgICAgICAgXSxcbiAgICAgICAgICB9XG4gICAgICAgIH1cbiAgICAgIH1cbiAgICAgfVxuICAgKi9cbiAgdHJ5IHtcbiAgICByZXMuc3RhdHVzKDIwMCkuanNvbihhd2FpdCByZXEuY2xpZW50LmVkaXRCdXNpbmVzc1Byb2ZpbGUocmVxLmJvZHkpKTtcbiAgfSBjYXRjaCAoZXJyb3IpIHtcbiAgICByZXMuc3RhdHVzKDUwMCkuanNvbih7XG4gICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICBtZXNzYWdlOiAnRXJyb3Igb24gZWRpdCBidXNpbmVzcyBwcm9maWxlJyxcbiAgICAgIGVycm9yOiBlcnJvcixcbiAgICB9KTtcbiAgfVxufVxuIl0sIm1hcHBpbmdzIjoiOzs7Ozs7Ozs7Ozs7Ozs7OztBQWlCQSxJQUFBQSxHQUFBLEdBQUFDLHNCQUFBLENBQUFDLE9BQUE7QUFDQSxJQUFBQyxVQUFBLEdBQUFGLHNCQUFBLENBQUFDLE9BQUE7QUFDQSxJQUFBRSxPQUFBLEdBQUFILHNCQUFBLENBQUFDLE9BQUE7OztBQUdBLElBQUFHLFFBQUEsR0FBQUgsT0FBQTtBQUNBLElBQUFJLE9BQUEsR0FBQUwsc0JBQUEsQ0FBQUMsT0FBQTtBQUNBLElBQUFLLGtCQUFBLEdBQUFOLHNCQUFBLENBQUFDLE9BQUE7QUFDQSxJQUFBTSxVQUFBLEdBQUFOLE9BQUE7QUFDQSxJQUFBTyxhQUFBLEdBQUFSLHNCQUFBLENBQUFDLE9BQUE7QUFDQSxJQUFBUSxZQUFBLEdBQUFSLE9BQUEsd0JBQXlFLENBM0J6RTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0EsR0FlQSxNQUFNUyxXQUFXLEdBQUcsSUFBSUMsMEJBQWlCLENBQUMsQ0FBQyxDQUUzQyxlQUFlQyxvQkFBb0JBLENBQ2pDQyxPQUFnQixFQUNoQkMsTUFBZ0IsRUFDaEJDLE1BQWMsRUFDZCxDQUNBLElBQUksQ0FDRixNQUFNQyxNQUFNLEdBQUcsTUFBTUYsTUFBTSxDQUFDRyxXQUFXLENBQUNKLE9BQU8sQ0FBQyxDQUVoRCxNQUFNSyxRQUFRLEdBQUcsd0JBQXdCTCxPQUFPLENBQUNNLENBQUMsRUFBRSxDQUNwRCxJQUFJLENBQUNDLFdBQUUsQ0FBQ0MsVUFBVSxDQUFDSCxRQUFRLENBQUMsRUFBRSxDQUM1QixJQUFJSSxNQUFNLEdBQUcsRUFBRTtNQUNmLElBQUlULE9BQU8sQ0FBQ1UsSUFBSSxLQUFLLEtBQUssRUFBRTtRQUMxQkQsTUFBTSxHQUFHLEdBQUdKLFFBQVEsTUFBTTtNQUM1QixDQUFDLE1BQU07UUFDTEksTUFBTSxHQUFHLEdBQUdKLFFBQVEsSUFBSU0sa0JBQUksQ0FBQ0MsU0FBUyxDQUFDWixPQUFPLENBQUNhLFFBQVEsQ0FBQyxFQUFFO01BQzVEOztNQUVBLE1BQU1OLFdBQUUsQ0FBQ08sU0FBUyxDQUFDTCxNQUFNLEVBQUVOLE1BQU0sRUFBRSxDQUFDWSxHQUFHLEtBQUs7UUFDMUMsSUFBSUEsR0FBRyxFQUFFO1VBQ1BiLE1BQU0sQ0FBQ2MsS0FBSyxDQUFDRCxHQUFHLENBQUM7UUFDbkI7TUFDRixDQUFDLENBQUM7O01BRUYsT0FBT04sTUFBTTtJQUNmLENBQUMsTUFBTTtNQUNMLE9BQU8sR0FBR0osUUFBUSxJQUFJTSxrQkFBSSxDQUFDQyxTQUFTLENBQUNaLE9BQU8sQ0FBQ2EsUUFBUSxDQUFDLEVBQUU7SUFDMUQ7RUFDRixDQUFDLENBQUMsT0FBT0ksQ0FBQyxFQUFFO0lBQ1ZmLE1BQU0sQ0FBQ2MsS0FBSyxDQUFDQyxDQUFDLENBQUM7SUFDZmYsTUFBTSxDQUFDZ0IsSUFBSTtNQUNUO0lBQ0YsQ0FBQztJQUNELElBQUk7TUFDRixNQUFNZixNQUFNLEdBQUcsTUFBTUYsTUFBTSxDQUFDa0IsYUFBYSxDQUFDbkIsT0FBTyxDQUFDO01BQ2xELE1BQU1LLFFBQVEsR0FBRyx3QkFBd0JMLE9BQU8sQ0FBQ00sQ0FBQyxFQUFFO01BQ3BELElBQUksQ0FBQ0MsV0FBRSxDQUFDQyxVQUFVLENBQUNILFFBQVEsQ0FBQyxFQUFFO1FBQzVCLElBQUlJLE1BQU0sR0FBRyxFQUFFO1FBQ2YsSUFBSVQsT0FBTyxDQUFDVSxJQUFJLEtBQUssS0FBSyxFQUFFO1VBQzFCRCxNQUFNLEdBQUcsR0FBR0osUUFBUSxNQUFNO1FBQzVCLENBQUMsTUFBTTtVQUNMSSxNQUFNLEdBQUcsR0FBR0osUUFBUSxJQUFJTSxrQkFBSSxDQUFDQyxTQUFTLENBQUNaLE9BQU8sQ0FBQ2EsUUFBUSxDQUFDLEVBQUU7UUFDNUQ7O1FBRUEsTUFBTU4sV0FBRSxDQUFDTyxTQUFTLENBQUNMLE1BQU0sRUFBRU4sTUFBTSxFQUFFLENBQUNZLEdBQUcsS0FBSztVQUMxQyxJQUFJQSxHQUFHLEVBQUU7WUFDUGIsTUFBTSxDQUFDYyxLQUFLLENBQUNELEdBQUcsQ0FBQztVQUNuQjtRQUNGLENBQUMsQ0FBQzs7UUFFRixPQUFPTixNQUFNO01BQ2YsQ0FBQyxNQUFNO1FBQ0wsT0FBTyxHQUFHSixRQUFRLElBQUlNLGtCQUFJLENBQUNDLFNBQVMsQ0FBQ1osT0FBTyxDQUFDYSxRQUFRLENBQUMsRUFBRTtNQUMxRDtJQUNGLENBQUMsQ0FBQyxPQUFPSSxDQUFDLEVBQUU7TUFDVmYsTUFBTSxDQUFDYyxLQUFLLENBQUNDLENBQUMsQ0FBQztNQUNmZixNQUFNLENBQUNnQixJQUFJLENBQUMsb0NBQW9DLENBQUM7SUFDbkQ7RUFDRjtBQUNGOztBQUVPLGVBQWVFLFFBQVFBLENBQUNwQixPQUFZLEVBQUVDLE1BQVcsRUFBRUMsTUFBVyxFQUFFO0VBQ3JFLElBQUk7SUFDRixNQUFNbUIsSUFBSSxHQUFHLE1BQU10QixvQkFBb0IsQ0FBQ0MsT0FBTyxFQUFFQyxNQUFNLEVBQUVDLE1BQU0sQ0FBQztJQUNoRSxPQUFPbUIsSUFBSSxFQUFFQyxPQUFPLENBQUMsSUFBSSxFQUFFLEVBQUUsQ0FBQztFQUNoQyxDQUFDLENBQUMsT0FBT0wsQ0FBQyxFQUFFO0lBQ1ZmLE1BQU0sQ0FBQ2MsS0FBSyxDQUFDQyxDQUFDLENBQUM7RUFDakI7QUFDRjs7QUFFTyxlQUFlTSxnQkFBZ0JBO0FBQ3BDQyxHQUFZO0FBQ1pDLEdBQWE7QUFDQztFQUNkO0FBQ0Y7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7RUFDRSxNQUFNLEVBQUVDLFNBQVMsQ0FBQyxDQUFDLEdBQUdGLEdBQUcsQ0FBQ0csTUFBTTtFQUNoQyxNQUFNLEVBQUVDLGFBQWEsRUFBRUMsS0FBSyxDQUFDLENBQUMsR0FBR0wsR0FBRyxDQUFDTSxPQUFPOztFQUU1QyxJQUFJQyxZQUFZLEdBQUcsRUFBRTs7RUFFckIsSUFBSUwsU0FBUyxLQUFLTSxTQUFTLEVBQUU7SUFDM0JELFlBQVksR0FBSUYsS0FBSyxDQUFTSSxLQUFLLENBQUMsR0FBRyxDQUFDLENBQUMsQ0FBQyxDQUFDO0VBQzdDLENBQUMsTUFBTTtJQUNMRixZQUFZLEdBQUdMLFNBQVM7RUFDMUI7O0VBRUEsTUFBTVEsV0FBVyxHQUFHLE1BQU0sSUFBQUMscUJBQVksRUFBQ1gsR0FBRyxDQUFDOztFQUUzQyxJQUFJTyxZQUFZLEtBQUtQLEdBQUcsQ0FBQ1ksYUFBYSxDQUFDQyxTQUFTLEVBQUU7SUFDaERaLEdBQUcsQ0FBQ2EsTUFBTSxDQUFDLEdBQUcsQ0FBQyxDQUFDQyxJQUFJLENBQUM7TUFDbkJDLFFBQVEsRUFBRSxPQUFPO01BQ2pCeEMsT0FBTyxFQUFFO0lBQ1gsQ0FBQyxDQUFDO0VBQ0o7O0VBRUFrQyxXQUFXLENBQUNPLEdBQUcsQ0FBQyxPQUFPQyxPQUFlLEtBQUs7SUFDekMsTUFBTUMsSUFBSSxHQUFHLElBQUk3QywwQkFBaUIsQ0FBQyxDQUFDO0lBQ3BDLE1BQU02QyxJQUFJLENBQUNDLFFBQVEsQ0FBQ3BCLEdBQUcsRUFBRWtCLE9BQU8sQ0FBQztFQUNuQyxDQUFDLENBQUM7O0VBRUYsT0FBTyxNQUFNakIsR0FBRztFQUNiYSxNQUFNLENBQUMsR0FBRyxDQUFDO0VBQ1hDLElBQUksQ0FBQyxFQUFFRCxNQUFNLEVBQUUsU0FBUyxFQUFFdEMsT0FBTyxFQUFFLHVCQUF1QixDQUFDLENBQUMsQ0FBQztBQUNsRTs7QUFFTyxlQUFlNkMsZUFBZUE7QUFDbkNyQixHQUFZO0FBQ1pDLEdBQWE7QUFDQztFQUNkO0FBQ0Y7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0VBQ0UsTUFBTSxFQUFFQyxTQUFTLENBQUMsQ0FBQyxHQUFHRixHQUFHLENBQUNHLE1BQU07RUFDaEMsTUFBTSxFQUFFQyxhQUFhLEVBQUVDLEtBQUssQ0FBQyxDQUFDLEdBQUdMLEdBQUcsQ0FBQ00sT0FBTzs7RUFFNUMsSUFBSUMsWUFBaUIsR0FBRyxFQUFFOztFQUUxQixJQUFJTCxTQUFTLEtBQUtNLFNBQVMsRUFBRTtJQUMzQkQsWUFBWSxHQUFHRixLQUFLLEVBQUVJLEtBQUssQ0FBQyxHQUFHLENBQUMsQ0FBQyxDQUFDLENBQUM7RUFDckMsQ0FBQyxNQUFNO0lBQ0xGLFlBQVksR0FBR0wsU0FBUztFQUMxQjs7RUFFQSxNQUFNb0IsR0FBUSxHQUFHLEVBQUU7O0VBRW5CLElBQUlmLFlBQVksS0FBS1AsR0FBRyxDQUFDWSxhQUFhLENBQUNDLFNBQVMsRUFBRTtJQUNoRFosR0FBRyxDQUFDYSxNQUFNLENBQUMsR0FBRyxDQUFDLENBQUNDLElBQUksQ0FBQztNQUNuQkMsUUFBUSxFQUFFLEtBQUs7TUFDZnhDLE9BQU8sRUFBRTtJQUNYLENBQUMsQ0FBQztFQUNKOztFQUVBK0MsTUFBTSxDQUFDQyxJQUFJLENBQUNDLHlCQUFZLENBQUMsQ0FBQ0MsT0FBTyxDQUFDLENBQUNDLElBQUksS0FBSztJQUMxQ0wsR0FBRyxDQUFDTSxJQUFJLENBQUMsRUFBRVYsT0FBTyxFQUFFUyxJQUFJLENBQUMsQ0FBQyxDQUFDO0VBQzdCLENBQUMsQ0FBQzs7RUFFRjFCLEdBQUcsQ0FBQ2EsTUFBTSxDQUFDLEdBQUcsQ0FBQyxDQUFDQyxJQUFJLENBQUMsRUFBRUMsUUFBUSxFQUFFLE1BQU0sSUFBQUwscUJBQVksRUFBQ1gsR0FBRyxDQUFDLENBQUMsQ0FBQyxDQUFDO0FBQzdEOztBQUVPLGVBQWU2QixZQUFZQSxDQUFDN0IsR0FBWSxFQUFFQyxHQUFhLEVBQWdCO0VBQzVFO0FBQ0Y7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtFQUNFLE1BQU1pQixPQUFPLEdBQUdsQixHQUFHLENBQUNrQixPQUFPO0VBQzNCLE1BQU0sRUFBRVksVUFBVSxHQUFHLEtBQUssQ0FBQyxDQUFDLEdBQUc5QixHQUFHLENBQUMrQixJQUFJOztFQUV2QyxNQUFNQyxlQUFlLENBQUNoQyxHQUFHLEVBQUVDLEdBQUcsQ0FBQztFQUMvQixNQUFNNUIsV0FBVyxDQUFDK0MsUUFBUSxDQUFDcEIsR0FBRyxFQUFFa0IsT0FBTyxFQUFFWSxVQUFVLEdBQUc3QixHQUFHLEdBQUcsSUFBSSxDQUFDO0FBQ25FOztBQUVPLGVBQWVnQyxZQUFZQSxDQUFDakMsR0FBWSxFQUFFQyxHQUFhLEVBQWdCO0VBQzVFO0FBQ0Y7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7RUFDRSxNQUFNaUIsT0FBTyxHQUFHbEIsR0FBRyxDQUFDa0IsT0FBTztFQUMzQixJQUFJO0lBQ0YsTUFBTXpDLE1BQU0sR0FBSWdELHlCQUFZLENBQVNQLE9BQU8sQ0FBQztJQUM3QyxJQUFJLENBQUN6QyxNQUFNLEVBQUU7TUFDWCxPQUFPLE1BQU13QixHQUFHO01BQ2JhLE1BQU0sQ0FBQyxHQUFHLENBQUM7TUFDWEMsSUFBSSxDQUFDLEVBQUVELE1BQU0sRUFBRSxJQUFJLEVBQUV0QyxPQUFPLEVBQUUsNkJBQTZCLENBQUMsQ0FBQyxDQUFDO0lBQ25FOztJQUVBLElBQUlDLE1BQU0sQ0FBQ3FDLE1BQU0sS0FBSyxXQUFXLElBQUlyQyxNQUFNLENBQUNxQyxNQUFNLEtBQUssTUFBTSxFQUFFO01BQzdEZCxHQUFHLENBQUN0QixNQUFNLENBQUN3RCxJQUFJLENBQUMsSUFBSWhCLE9BQU8sNkNBQTZDekMsTUFBTSxDQUFDcUMsTUFBTSxFQUFFLENBQUM7TUFDeEZyQyxNQUFNLENBQUMwRCxXQUFXLEdBQUcsSUFBSTtNQUN6QixJQUFJO1FBQ0Y5RCxXQUFXLENBQUMrRCxnQkFBZ0IsQ0FBQ2xCLE9BQU8sRUFBRWxCLEdBQUcsQ0FBQ3RCLE1BQU0sQ0FBQztNQUNuRCxDQUFDLENBQUMsT0FBT2UsQ0FBQyxFQUFFLENBQUM7TUFDWmdDLHlCQUFZLENBQVNQLE9BQU8sQ0FBQyxHQUFHVixTQUFTO01BQzFDLE9BQU8sTUFBTVAsR0FBRztNQUNiYSxNQUFNLENBQUMsR0FBRyxDQUFDO01BQ1hDLElBQUksQ0FBQyxFQUFFRCxNQUFNLEVBQUUsSUFBSSxFQUFFdEMsT0FBTyxFQUFFLHNCQUFzQixDQUFDLENBQUMsQ0FBQztJQUM1RDs7SUFFQ2lELHlCQUFZLENBQVNQLE9BQU8sQ0FBQyxHQUFHLEVBQUVKLE1BQU0sRUFBRSxJQUFJLENBQUMsQ0FBQzs7SUFFakQsSUFBSWQsR0FBRyxDQUFDdkIsTUFBTSxJQUFJLE9BQU91QixHQUFHLENBQUN2QixNQUFNLENBQUM0RCxLQUFLLEtBQUssVUFBVSxFQUFFO01BQ3hELE1BQU1yQyxHQUFHLENBQUN2QixNQUFNLENBQUM0RCxLQUFLLENBQUMsQ0FBQztJQUMxQjtJQUNFckMsR0FBRyxDQUFDc0MsRUFBRSxDQUFDQyxJQUFJLENBQUMsaUJBQWlCLEVBQUUsS0FBSyxDQUFDO0lBQ3JDLElBQUFDLHNCQUFXLEVBQUN4QyxHQUFHLENBQUN2QixNQUFNLEVBQUV1QixHQUFHLEVBQUUsY0FBYyxFQUFFO01BQzNDeEIsT0FBTyxFQUFFLFlBQVkwQyxPQUFPLGVBQWU7TUFDM0N1QixTQUFTLEVBQUU7SUFDYixDQUFDLENBQUM7O0lBRUYsT0FBTyxNQUFNeEMsR0FBRztJQUNiYSxNQUFNLENBQUMsR0FBRyxDQUFDO0lBQ1hDLElBQUksQ0FBQyxFQUFFRCxNQUFNLEVBQUUsSUFBSSxFQUFFdEMsT0FBTyxFQUFFLDZCQUE2QixDQUFDLENBQUMsQ0FBQztFQUNyRSxDQUFDLENBQUMsT0FBT2dCLEtBQUssRUFBRTtJQUNkUSxHQUFHLENBQUN0QixNQUFNLENBQUNjLEtBQUssQ0FBQ0EsS0FBSyxDQUFDO0lBQ3ZCLE9BQU8sTUFBTVMsR0FBRztJQUNiYSxNQUFNLENBQUMsR0FBRyxDQUFDO0lBQ1hDLElBQUksQ0FBQyxFQUFFRCxNQUFNLEVBQUUsS0FBSyxFQUFFdEMsT0FBTyxFQUFFLHVCQUF1QixFQUFFZ0IsS0FBSyxDQUFDLENBQUMsQ0FBQztFQUNyRTtBQUNGOztBQUVPLGVBQWVrRCxhQUFhQSxDQUFDMUMsR0FBWSxFQUFFQyxHQUFhLEVBQWdCO0VBQzdFO0FBQ0Y7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtFQUNFLElBQUk7SUFDRixNQUFNaUIsT0FBTyxHQUFHbEIsR0FBRyxDQUFDa0IsT0FBTztJQUMzQixNQUFNbEIsR0FBRyxDQUFDdkIsTUFBTSxDQUFDa0UsTUFBTSxDQUFDLENBQUM7SUFDekIsSUFBQUMsaUNBQW9CLEVBQUM1QyxHQUFHLENBQUNrQixPQUFPLENBQUM7O0lBRWpDMkIsVUFBVSxDQUFDLFlBQVk7TUFDckIsTUFBTUMsWUFBWSxHQUFHQyxlQUFNLENBQUNDLGlCQUFpQixHQUFHaEQsR0FBRyxDQUFDa0IsT0FBTztNQUMzRCxNQUFNK0IsVUFBVSxHQUFHQyxTQUFTLEdBQUcsbUJBQW1CbEQsR0FBRyxDQUFDa0IsT0FBTyxZQUFZOztNQUV6RSxJQUFJbkMsV0FBRSxDQUFDQyxVQUFVLENBQUM4RCxZQUFZLENBQUMsRUFBRTtRQUMvQixNQUFNL0QsV0FBRSxDQUFDb0UsUUFBUSxDQUFDQyxFQUFFLENBQUNOLFlBQVksRUFBRTtVQUNqQ08sU0FBUyxFQUFFLElBQUk7VUFDZkMsVUFBVSxFQUFFLENBQUM7VUFDYkMsS0FBSyxFQUFFLElBQUk7VUFDWEMsVUFBVSxFQUFFO1FBQ2QsQ0FBQyxDQUFDO01BQ0o7TUFDQSxJQUFJekUsV0FBRSxDQUFDQyxVQUFVLENBQUNpRSxVQUFVLENBQUMsRUFBRTtRQUM3QixNQUFNbEUsV0FBRSxDQUFDb0UsUUFBUSxDQUFDQyxFQUFFLENBQUNILFVBQVUsRUFBRTtVQUMvQkksU0FBUyxFQUFFLElBQUk7VUFDZkMsVUFBVSxFQUFFLENBQUM7VUFDYkMsS0FBSyxFQUFFLElBQUk7VUFDWEMsVUFBVSxFQUFFO1FBQ2QsQ0FBQyxDQUFDO01BQ0o7O01BRUF4RCxHQUFHLENBQUNzQyxFQUFFLENBQUNDLElBQUksQ0FBQyxpQkFBaUIsRUFBRSxLQUFLLENBQUM7TUFDckMsSUFBQUMsc0JBQVcsRUFBQ3hDLEdBQUcsQ0FBQ3ZCLE1BQU0sRUFBRXVCLEdBQUcsRUFBRSxlQUFlLEVBQUU7UUFDNUN4QixPQUFPLEVBQUUsWUFBWTBDLE9BQU8sYUFBYTtRQUN6Q3VCLFNBQVMsRUFBRTtNQUNiLENBQUMsQ0FBQzs7TUFFRixPQUFPLE1BQU14QyxHQUFHO01BQ2JhLE1BQU0sQ0FBQyxHQUFHLENBQUM7TUFDWEMsSUFBSSxDQUFDLEVBQUVELE1BQU0sRUFBRSxJQUFJLEVBQUV0QyxPQUFPLEVBQUUsNkJBQTZCLENBQUMsQ0FBQyxDQUFDO0lBQ25FLENBQUMsRUFBRSxHQUFHLENBQUM7SUFDUDtBQUNKO0FBQ0E7RUFDRSxDQUFDLENBQUMsT0FBT2dCLEtBQUssRUFBRTtJQUNkUSxHQUFHLENBQUN0QixNQUFNLENBQUNjLEtBQUssQ0FBQ0EsS0FBSyxDQUFDO0lBQ3ZCUyxHQUFHO0lBQ0FhLE1BQU0sQ0FBQyxHQUFHLENBQUM7SUFDWEMsSUFBSSxDQUFDLEVBQUVELE1BQU0sRUFBRSxLQUFLLEVBQUV0QyxPQUFPLEVBQUUsdUJBQXVCLEVBQUVnQixLQUFLLENBQUMsQ0FBQyxDQUFDO0VBQ3JFO0FBQ0Y7O0FBRU8sZUFBZWlFLHNCQUFzQkE7QUFDMUN6RCxHQUFZO0FBQ1pDLEdBQWE7QUFDQztFQUNkO0FBQ0Y7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7RUFDRSxJQUFJO0lBQ0YsTUFBTUQsR0FBRyxDQUFDdkIsTUFBTSxDQUFDaUYsV0FBVyxDQUFDLENBQUM7O0lBRTlCekQsR0FBRyxDQUFDYSxNQUFNLENBQUMsR0FBRyxDQUFDLENBQUNDLElBQUksQ0FBQyxFQUFFRCxNQUFNLEVBQUUsSUFBSSxFQUFFdEMsT0FBTyxFQUFFLFdBQVcsQ0FBQyxDQUFDLENBQUM7RUFDOUQsQ0FBQyxDQUFDLE9BQU9nQixLQUFLLEVBQUU7SUFDZFMsR0FBRyxDQUFDYSxNQUFNLENBQUMsR0FBRyxDQUFDLENBQUNDLElBQUksQ0FBQyxFQUFFRCxNQUFNLEVBQUUsS0FBSyxFQUFFdEMsT0FBTyxFQUFFLGNBQWMsQ0FBQyxDQUFDLENBQUM7RUFDbEU7QUFDRjs7QUFFQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDTyxlQUFlbUYscUJBQXFCQSxDQUFDM0QsR0FBWSxFQUFFQyxHQUFhLEVBQUU7RUFDdkU7QUFDRjtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7RUFDRSxJQUFJO0lBQ0YsTUFBTTJELElBQUksR0FBSTVELEdBQUcsQ0FBQ3ZCLE1BQU0sRUFBVW1GLElBQUk7SUFDdEMsSUFBSSxDQUFDQSxJQUFJLElBQUlBLElBQUksQ0FBQ0MsUUFBUSxDQUFDLENBQUMsRUFBRTtNQUM1QixPQUFPNUQsR0FBRyxDQUFDYSxNQUFNLENBQUMsR0FBRyxDQUFDLENBQUNDLElBQUksQ0FBQztRQUMxQkQsTUFBTSxFQUFFLE9BQU87UUFDZnRDLE9BQU8sRUFBRTtNQUNYLENBQUMsQ0FBQztJQUNKO0lBQ0EsTUFBTVMsTUFBTSxHQUFHLE1BQU0yRSxJQUFJLENBQUNFLFFBQVEsQ0FBQyxNQUFNO01BQ3ZDLElBQUk7UUFDRixNQUFNQyxHQUFHLEdBQUlDLE1BQU0sQ0FBU0MsR0FBRztRQUMvQixJQUFJRixHQUFHLEVBQUVHLFFBQVEsRUFBRUMsR0FBRyxFQUFFQyxnQkFBZ0IsRUFBRTtVQUN4Q0wsR0FBRyxDQUFDRyxRQUFRLENBQUNDLEdBQUcsQ0FBQ0MsZ0JBQWdCLENBQUMsQ0FBQztVQUNuQyxPQUFPLEVBQUVDLEVBQUUsRUFBRSxJQUFJLENBQUMsQ0FBQztRQUNyQjtRQUNBLE9BQU8sRUFBRUEsRUFBRSxFQUFFLEtBQUssRUFBRTdFLEtBQUssRUFBRSxpREFBaUQsQ0FBQyxDQUFDO01BQ2hGLENBQUMsQ0FBQyxPQUFPQyxDQUFNLEVBQUU7UUFDZixPQUFPLEVBQUU0RSxFQUFFLEVBQUUsS0FBSyxFQUFFN0UsS0FBSyxFQUFFQyxDQUFDLEVBQUVqQixPQUFPLElBQUk4RixNQUFNLENBQUM3RSxDQUFDLENBQUMsQ0FBQyxDQUFDO01BQ3REO0lBQ0YsQ0FBQyxDQUFDO0lBQ0YsSUFBSSxDQUFDUixNQUFNLEVBQUVvRixFQUFFLEVBQUU7TUFDZnJFLEdBQUcsQ0FBQ3RCLE1BQU0sQ0FBQ2dCLElBQUksQ0FBQywyQkFBMkJULE1BQU0sRUFBRU8sS0FBSyxJQUFJLGlCQUFpQixFQUFFLENBQUM7SUFDbEY7SUFDQVMsR0FBRyxDQUFDYSxNQUFNLENBQUMsR0FBRyxDQUFDLENBQUNDLElBQUksQ0FBQyxFQUFFRCxNQUFNLEVBQUUsU0FBUyxFQUFFRSxRQUFRLEVBQUUvQixNQUFNLENBQUMsQ0FBQyxDQUFDO0VBQy9ELENBQUMsQ0FBQyxPQUFPTyxLQUFVLEVBQUU7SUFDbkJRLEdBQUcsQ0FBQ3RCLE1BQU0sQ0FBQ2MsS0FBSyxDQUFDQSxLQUFLLENBQUM7SUFDdkJTLEdBQUcsQ0FBQ2EsTUFBTSxDQUFDLEdBQUcsQ0FBQyxDQUFDQyxJQUFJLENBQUM7TUFDbkJELE1BQU0sRUFBRSxPQUFPO01BQ2Z0QyxPQUFPLEVBQUVnQixLQUFLLEVBQUVoQixPQUFPLElBQUk4RixNQUFNLENBQUM5RSxLQUFLO0lBQ3pDLENBQUMsQ0FBQztFQUNKO0FBQ0Y7O0FBRU8sZUFBZStFLHNCQUFzQkEsQ0FBQ3ZFLEdBQVksRUFBRUMsR0FBYSxFQUFFO0VBQ3hFO0FBQ0Y7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtFQUNFLE1BQU14QixNQUFNLEdBQUd1QixHQUFHLENBQUN2QixNQUFNO0VBQ3pCLE1BQU0sRUFBRStGLFNBQVMsQ0FBQyxDQUFDLEdBQUd4RSxHQUFHLENBQUMrQixJQUFJOztFQUU5QixJQUFJLENBQUN0RCxNQUFNLElBQUksT0FBT0EsTUFBTSxDQUFDZ0csY0FBYyxLQUFLLFVBQVUsRUFBRTtJQUMxRCxPQUFPeEUsR0FBRyxDQUFDYSxNQUFNLENBQUMsR0FBRyxDQUFDLENBQUNDLElBQUksQ0FBQztNQUMxQkQsTUFBTSxFQUFFLE9BQU87TUFDZnRDLE9BQU8sRUFBRTtJQUNYLENBQUMsQ0FBQztFQUNKOztFQUVBLElBQUlBLE9BQU87O0VBRVgsSUFBSTtJQUNGLElBQUksQ0FBQ2dHLFNBQVMsQ0FBQ0UsT0FBTyxJQUFJLENBQUNGLFNBQVMsQ0FBQ3RGLElBQUksRUFBRTtNQUN6Q1YsT0FBTyxHQUFHLE1BQU1DLE1BQU0sQ0FBQ2dHLGNBQWMsQ0FBQ0QsU0FBUyxDQUFDO0lBQ2xELENBQUMsTUFBTTtNQUNMaEcsT0FBTyxHQUFHZ0csU0FBUztJQUNyQjs7SUFFQSxJQUFJLENBQUNoRyxPQUFPO0lBQ1Z5QixHQUFHLENBQUNhLE1BQU0sQ0FBQyxHQUFHLENBQUMsQ0FBQ0MsSUFBSSxDQUFDO01BQ25CRCxNQUFNLEVBQUUsT0FBTztNQUNmdEMsT0FBTyxFQUFFO0lBQ1gsQ0FBQyxDQUFDOztJQUVKLElBQUksRUFBRUEsT0FBTyxDQUFDLFVBQVUsQ0FBQyxJQUFJQSxPQUFPLENBQUNrRyxPQUFPLElBQUlsRyxPQUFPLENBQUNtRyxLQUFLLENBQUM7SUFDNUQxRSxHQUFHLENBQUNhLE1BQU0sQ0FBQyxHQUFHLENBQUMsQ0FBQ0MsSUFBSSxDQUFDO01BQ25CRCxNQUFNLEVBQUUsT0FBTztNQUNmdEMsT0FBTyxFQUFFO0lBQ1gsQ0FBQyxDQUFDOztJQUVKLE1BQU1HLE1BQU0sR0FBRyxNQUFNRixNQUFNLENBQUNHLFdBQVcsQ0FBQ0osT0FBTyxDQUFDOztJQUVoRHlCLEdBQUc7SUFDQWEsTUFBTSxDQUFDLEdBQUcsQ0FBQztJQUNYQyxJQUFJLENBQUMsRUFBRTZELE1BQU0sRUFBRWpHLE1BQU0sQ0FBQ2tHLFFBQVEsQ0FBQyxRQUFRLENBQUMsRUFBRXhGLFFBQVEsRUFBRWIsT0FBTyxDQUFDYSxRQUFRLENBQUMsQ0FBQyxDQUFDO0VBQzVFLENBQUMsQ0FBQyxPQUFPSSxDQUFDLEVBQUU7SUFDVk8sR0FBRyxDQUFDdEIsTUFBTSxDQUFDYyxLQUFLLENBQUNDLENBQUMsQ0FBQztJQUNuQlEsR0FBRyxDQUFDYSxNQUFNLENBQUMsR0FBRyxDQUFDLENBQUNDLElBQUksQ0FBQztNQUNuQkQsTUFBTSxFQUFFLE9BQU87TUFDZnRDLE9BQU8sRUFBRSxvQkFBb0I7TUFDN0JnQixLQUFLLEVBQUVDO0lBQ1QsQ0FBQyxDQUFDO0VBQ0o7QUFDRjs7QUFFTyxlQUFlcUYsaUJBQWlCQSxDQUFDOUUsR0FBWSxFQUFFQyxHQUFhLEVBQUU7RUFDbkU7QUFDRjtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtFQUNFLE1BQU14QixNQUFNLEdBQUd1QixHQUFHLENBQUN2QixNQUFNO0VBQ3pCLE1BQU0sRUFBRStGLFNBQVMsQ0FBQyxDQUFDLEdBQUd4RSxHQUFHLENBQUNHLE1BQU07O0VBRWhDLElBQUksQ0FBQzFCLE1BQU0sSUFBSSxPQUFPQSxNQUFNLENBQUNnRyxjQUFjLEtBQUssVUFBVSxFQUFFO0lBQzFELE9BQU94RSxHQUFHLENBQUNhLE1BQU0sQ0FBQyxHQUFHLENBQUMsQ0FBQ0MsSUFBSSxDQUFDO01BQzFCRCxNQUFNLEVBQUUsT0FBTztNQUNmdEMsT0FBTyxFQUFFO0lBQ1gsQ0FBQyxDQUFDO0VBQ0o7O0VBRUEsSUFBSTtJQUNGLElBQUlBLE9BQVksR0FBRyxJQUFJOztJQUV2QjtJQUNBLE1BQU11RyxjQUFjLEdBQUcvRSxHQUFHLENBQUMrQixJQUFJLEtBQUsvQixHQUFHLENBQUMrQixJQUFJLENBQUNpRCxTQUFTLElBQUloRixHQUFHLENBQUMrQixJQUFJLENBQUNrRCxpQkFBaUIsSUFBSWpGLEdBQUcsQ0FBQytCLElBQUksQ0FBQ21ELEdBQUcsSUFBSWxGLEdBQUcsQ0FBQytCLElBQUksQ0FBQ29ELFVBQVUsQ0FBQztJQUM1SCxJQUFJbkYsR0FBRyxDQUFDK0IsSUFBSSxJQUFJL0IsR0FBRyxDQUFDK0IsSUFBSSxDQUFDcUQsUUFBUSxJQUFJTCxjQUFjLEVBQUU7TUFDbkQvRSxHQUFHLENBQUN0QixNQUFNLENBQUN3RCxJQUFJLENBQUMsc0VBQXNFc0MsU0FBUywrQkFBK0IsQ0FBQztNQUMvSGhHLE9BQU8sR0FBR3dCLEdBQUcsQ0FBQytCLElBQUk7TUFDbEIsSUFBSSxDQUFDdkQsT0FBTyxDQUFDd0csU0FBUyxLQUFLeEcsT0FBTyxDQUFDMEcsR0FBRyxJQUFJMUcsT0FBTyxDQUFDeUcsaUJBQWlCLENBQUMsRUFBRTtRQUNwRXpHLE9BQU8sQ0FBQ3dHLFNBQVMsR0FBR3hHLE9BQU8sQ0FBQ3dHLFNBQVMsSUFBSXhHLE9BQU8sQ0FBQzBHLEdBQUcsSUFBSTFHLE9BQU8sQ0FBQ3lHLGlCQUFpQjtNQUNuRjtNQUNBO01BQ0EsSUFBSSxPQUFPekcsT0FBTyxDQUFDNEcsUUFBUSxLQUFLLFFBQVEsSUFBSTVHLE9BQU8sQ0FBQzRHLFFBQVEsQ0FBQ0MsSUFBSSxFQUFFO1FBQ2pFN0csT0FBTyxDQUFDNEcsUUFBUSxHQUFHRSxNQUFNLENBQUNDLElBQUksQ0FBQy9HLE9BQU8sQ0FBQzRHLFFBQVEsQ0FBQ0MsSUFBSSxDQUFDO01BQ3ZELENBQUMsTUFBTSxJQUFJLE9BQU83RyxPQUFPLENBQUM0RyxRQUFRLEtBQUssUUFBUSxFQUFFO1FBQy9DNUcsT0FBTyxDQUFDNEcsUUFBUSxHQUFHRSxNQUFNLENBQUNDLElBQUksQ0FBQy9HLE9BQU8sQ0FBQzRHLFFBQVEsRUFBRSxRQUFRLENBQUM7TUFDNUQ7SUFDRixDQUFDLE1BQU07TUFDTCxJQUFJO1FBQ0Y1RyxPQUFPLEdBQUcsTUFBTUMsTUFBTSxDQUFDZ0csY0FBYyxDQUFDRCxTQUFTLENBQUM7TUFDbEQsQ0FBQyxDQUFDLE9BQU9qRixHQUFRLEVBQUU7UUFDakJTLEdBQUcsQ0FBQ3RCLE1BQU0sQ0FBQ2dCLElBQUksQ0FBQyxzQ0FBc0NILEdBQUcsQ0FBQ2YsT0FBTyxJQUFJZSxHQUFHLHNCQUFzQixDQUFDO01BQ2pHOztNQUVBO01BQ0E7TUFDQTtNQUNBLElBQUksQ0FBQ2YsT0FBTyxJQUFJZ0csU0FBUyxFQUFFO1FBQ3pCLE1BQU1nQixLQUFLLEdBQUdoQixTQUFTLENBQUMvRCxLQUFLLENBQUMsR0FBRyxDQUFDO1FBQ2xDLElBQUkrRSxLQUFLLENBQUNDLE1BQU0sSUFBSSxDQUFDLEVBQUU7VUFDckIsTUFBTUMsTUFBTSxHQUFHRixLQUFLLENBQUMsQ0FBQyxDQUFDLENBQUMsQ0FBQztVQUN6QixJQUFJRSxNQUFNLEVBQUU7WUFDVjFGLEdBQUcsQ0FBQ3RCLE1BQU0sQ0FBQ3dELElBQUksQ0FBQyxXQUFXc0MsU0FBUywyRUFBMkVrQixNQUFNLEVBQUUsQ0FBQztZQUN4SCxJQUFJO2NBQ0YsSUFBSWpILE1BQU0sQ0FBQ21GLElBQUksSUFBSSxDQUFDbkYsTUFBTSxDQUFDbUYsSUFBSSxDQUFDQyxRQUFRLENBQUMsQ0FBQyxFQUFFO2dCQUMxQ3JGLE9BQU8sR0FBRyxNQUFNQyxNQUFNLENBQUNtRixJQUFJLENBQUNFLFFBQVEsQ0FBQyxPQUFPLEVBQUU2QixLQUFLLEVBQUVDLFlBQVksQ0FBQyxDQUFDLEtBQUs7a0JBQ3RFLElBQUk7b0JBQ0YsTUFBTTNCLEdBQUcsR0FBSUQsTUFBTSxDQUFTQyxHQUFHO29CQUMvQixNQUFNNEIsS0FBSyxHQUFJN0IsTUFBTSxDQUFTNkIsS0FBSzs7b0JBRW5DO29CQUNBLElBQUlDLFNBQVMsR0FBR0YsWUFBWTtvQkFDNUIsSUFBSTNCLEdBQUcsRUFBRUMsUUFBUSxFQUFFNkIsVUFBVSxFQUFFQyxNQUFNLEVBQUU7c0JBQ3JDLElBQUk7d0JBQ0ZGLFNBQVMsR0FBRzdCLEdBQUcsQ0FBQ0MsUUFBUSxDQUFDNkIsVUFBVSxDQUFDQyxNQUFNLENBQUNKLFlBQVksQ0FBQztzQkFDMUQsQ0FBQyxDQUFDLE9BQU9uRyxDQUFDLEVBQUUsQ0FBQztvQkFDZjs7b0JBRUE7b0JBQ0EsSUFBSXdFLEdBQUcsRUFBRWdDLElBQUksRUFBRUMsSUFBSSxFQUFFO3NCQUNuQixJQUFJLENBQUUsTUFBTWpDLEdBQUcsQ0FBQ2dDLElBQUksQ0FBQ0MsSUFBSSxDQUFDTixZQUFZLENBQUMsQ0FBRSxDQUFDLENBQUMsT0FBT25HLENBQUMsRUFBRSxDQUFDO3NCQUN0RCxJQUFJLENBQUUsSUFBSXFHLFNBQVMsS0FBS0YsWUFBWSxFQUFFLE1BQU0zQixHQUFHLENBQUNnQyxJQUFJLENBQUNDLElBQUksQ0FBQ0osU0FBUyxDQUFDLENBQUUsQ0FBQyxDQUFDLE9BQU9yRyxDQUFDLEVBQUUsQ0FBQztzQkFDbkYsSUFBSTt3QkFDRixJQUFJbUcsWUFBWSxDQUFDTyxRQUFRLENBQUMsT0FBTyxDQUFDLEVBQUU7MEJBQ2xDLE1BQU1sQyxHQUFHLENBQUNnQyxJQUFJLENBQUNDLElBQUksQ0FBQ04sWUFBWSxDQUFDOUYsT0FBTyxDQUFDLFNBQVMsRUFBRSxpQkFBaUIsQ0FBQyxDQUFDO3dCQUN6RTtzQkFDRixDQUFDLENBQUMsT0FBT0wsQ0FBQyxFQUFFLENBQUM7b0JBQ2Y7O29CQUVBLElBQUl3RSxHQUFHLEVBQUVnQyxJQUFJLEVBQUVHLG1CQUFtQixFQUFFO3NCQUNsQyxJQUFJLENBQUUsTUFBTW5DLEdBQUcsQ0FBQ2dDLElBQUksQ0FBQ0csbUJBQW1CLENBQUNSLFlBQVksQ0FBQyxDQUFFLENBQUMsQ0FBQyxPQUFPbkcsQ0FBQyxFQUFFLENBQUM7b0JBQ3ZFOztvQkFFQTtvQkFDQSxNQUFNNEcsVUFBVSxHQUFHLE1BQUFBLENBQU9DLEdBQVcsS0FBSztzQkFDeEMsSUFBSSxDQUFDQSxHQUFHLEVBQUUsT0FBTyxJQUFJO3NCQUNyQixJQUFJckMsR0FBRyxFQUFFZ0MsSUFBSSxFQUFFeEIsY0FBYyxFQUFFO3dCQUM3QixJQUFJOzBCQUNGLE1BQU04QixDQUFDLEdBQUcsTUFBTXRDLEdBQUcsQ0FBQ2dDLElBQUksQ0FBQ3hCLGNBQWMsQ0FBQzZCLEdBQUcsQ0FBQzswQkFDNUMsSUFBSUMsQ0FBQyxFQUFFLE9BQU9BLENBQUM7d0JBQ2pCLENBQUMsQ0FBQyxPQUFPOUcsQ0FBQyxFQUFFLENBQUM7d0JBQ2IsSUFBSTswQkFDRixJQUFJNkcsR0FBRyxDQUFDSCxRQUFRLENBQUMsT0FBTyxDQUFDLEVBQUU7NEJBQ3pCLE1BQU1JLENBQUMsR0FBRyxNQUFNdEMsR0FBRyxDQUFDZ0MsSUFBSSxDQUFDeEIsY0FBYyxDQUFDNkIsR0FBRyxDQUFDeEcsT0FBTyxDQUFDLFNBQVMsRUFBRSxpQkFBaUIsQ0FBQyxDQUFDOzRCQUNsRixJQUFJeUcsQ0FBQyxFQUFFLE9BQU9BLENBQUM7MEJBQ2pCLENBQUMsTUFBTSxJQUFJRCxHQUFHLENBQUNILFFBQVEsQ0FBQyxpQkFBaUIsQ0FBQyxFQUFFOzRCQUMxQyxNQUFNSSxDQUFDLEdBQUcsTUFBTXRDLEdBQUcsQ0FBQ2dDLElBQUksQ0FBQ3hCLGNBQWMsQ0FBQzZCLEdBQUcsQ0FBQ3hHLE9BQU8sQ0FBQyxvQkFBb0IsRUFBRSxPQUFPLENBQUMsQ0FBQzs0QkFDbkYsSUFBSXlHLENBQUMsRUFBRSxPQUFPQSxDQUFDOzBCQUNqQjt3QkFDRixDQUFDLENBQUMsT0FBTzlHLENBQUMsRUFBRSxDQUFDO3NCQUNmOztzQkFFQTtzQkFDQSxNQUFNK0YsS0FBSyxHQUFHYyxHQUFHLENBQUM3RixLQUFLLENBQUMsR0FBRyxDQUFDO3NCQUM1QixNQUFNK0YsS0FBSyxHQUFHaEIsS0FBSyxDQUFDQyxNQUFNLEdBQUcsQ0FBQyxHQUFHRCxLQUFLLENBQUMsQ0FBQyxDQUFDLEdBQUdjLEdBQUc7c0JBQy9DLElBQUlULEtBQUssRUFBRVksR0FBRyxFQUFFQyxNQUFNLEVBQUU7d0JBQ3RCLE1BQU1DLEtBQUssR0FBR2QsS0FBSyxDQUFDWSxHQUFHLENBQUNDLE1BQU0sQ0FBQ1IsSUFBSSxDQUFDLENBQUN2RSxJQUFTLEtBQUs7MEJBQ2pELElBQUksQ0FBQ0EsSUFBSSxJQUFJLENBQUNBLElBQUksQ0FBQ2lGLEVBQUUsRUFBRSxPQUFPLEtBQUs7MEJBQ25DLE1BQU1DLEdBQUcsR0FBR2xGLElBQUksQ0FBQ2lGLEVBQUUsQ0FBQ0UsV0FBVyxJQUFJLEVBQUU7MEJBQ3JDLE1BQU1DLE1BQU0sR0FBR3BGLElBQUksQ0FBQ2lGLEVBQUUsQ0FBQ0EsRUFBRSxJQUFJLEVBQUU7MEJBQy9CLE9BQU9HLE1BQU0sS0FBS1AsS0FBSyxJQUFJSyxHQUFHLEtBQUtQLEdBQUcsSUFBS0UsS0FBSyxJQUFJSyxHQUFHLENBQUNWLFFBQVEsQ0FBQ0ssS0FBSyxDQUFFO3dCQUMxRSxDQUFDLENBQUM7d0JBQ0YsSUFBSUcsS0FBSyxFQUFFLE9BQU9BLEtBQUs7c0JBQ3pCO3NCQUNBLE9BQU8sSUFBSTtvQkFDYixDQUFDOztvQkFFRCxPQUFPLE1BQU1OLFVBQVUsQ0FBQ1YsS0FBSyxDQUFDO2tCQUNoQyxDQUFDLENBQUMsT0FBT2xHLENBQUMsRUFBRTtvQkFDVnVILE9BQU8sQ0FBQ0MsR0FBRyxDQUFDLHdEQUF3RHhILENBQUMsRUFBRSxDQUFDO29CQUN4RSxPQUFPLElBQUk7a0JBQ2I7Z0JBQ0YsQ0FBQyxFQUFFLEVBQUVrRyxLQUFLLEVBQUVuQixTQUFTLEVBQUVvQixZQUFZLEVBQUVGLE1BQU0sQ0FBQyxDQUFDLENBQUM7Y0FDaEQ7O2NBRUE7Y0FDQSxJQUFJLENBQUNsSCxPQUFPLElBQUksT0FBT0MsTUFBTSxDQUFDZ0csY0FBYyxLQUFLLFVBQVUsRUFBRTtnQkFDM0QsSUFBSTtrQkFDRmpHLE9BQU8sR0FBRyxNQUFNQyxNQUFNLENBQUNnRyxjQUFjLENBQUNELFNBQVMsQ0FBQztnQkFDbEQsQ0FBQyxDQUFDLE9BQU8wQyxRQUFhLEVBQUU7a0JBQ3RCbEgsR0FBRyxDQUFDdEIsTUFBTSxDQUFDYyxLQUFLLENBQUMsZ0NBQWdDMEgsUUFBUSxDQUFDMUksT0FBTyxJQUFJMEksUUFBUSxFQUFFLENBQUM7Z0JBQ2xGO2NBQ0Y7WUFDRixDQUFDLENBQUMsT0FBT0MsT0FBTyxFQUFFO2NBQ2hCbkgsR0FBRyxDQUFDdEIsTUFBTSxDQUFDYyxLQUFLLENBQUMsK0NBQStDMkgsT0FBTyxFQUFFLENBQUM7WUFDNUU7VUFDRjtRQUNGO01BQ0Y7SUFDRjs7SUFFQSxJQUFJLENBQUMzSSxPQUFPLEVBQUU7TUFDWixPQUFPeUIsR0FBRyxDQUFDYSxNQUFNLENBQUMsR0FBRyxDQUFDLENBQUNDLElBQUksQ0FBQztRQUMxQkQsTUFBTSxFQUFFLE9BQU87UUFDZnRDLE9BQU8sRUFBRSxXQUFXZ0csU0FBUztNQUMvQixDQUFDLENBQUM7SUFDSjs7SUFFQTtJQUNBLElBQUkvRixNQUFNLENBQUNtRixJQUFJLElBQUluRixNQUFNLENBQUNtRixJQUFJLENBQUNDLFFBQVEsQ0FBQyxDQUFDLEVBQUU7TUFDekM3RCxHQUFHLENBQUN0QixNQUFNLENBQUNnQixJQUFJLENBQUMsNkRBQTZEOEUsU0FBUyxFQUFFLENBQUM7TUFDekYsT0FBT3ZFLEdBQUcsQ0FBQ2EsTUFBTSxDQUFDLEdBQUcsQ0FBQyxDQUFDQyxJQUFJLENBQUM7UUFDMUJELE1BQU0sRUFBRSxPQUFPO1FBQ2Z0QyxPQUFPLEVBQUU7TUFDWCxDQUFDLENBQUM7SUFDSjs7SUFFQTtJQUNBLE1BQU00SSxRQUFRLEdBQUc1SSxPQUFPLENBQUN3RyxTQUFTLElBQUl4RyxPQUFPLENBQUN5RyxpQkFBaUI7SUFDL0QsSUFBSSxDQUFDbUMsUUFBUSxFQUFFO01BQ2IsSUFBSSxPQUFRM0ksTUFBTSxDQUFTa0IsYUFBYSxLQUFLLFVBQVUsSUFBSWxCLE1BQU0sQ0FBQ21GLElBQUksSUFBSSxDQUFDbkYsTUFBTSxDQUFDbUYsSUFBSSxDQUFDQyxRQUFRLENBQUMsQ0FBQyxFQUFFO1FBQ2pHN0QsR0FBRyxDQUFDdEIsTUFBTSxDQUFDd0QsSUFBSSxDQUFDLFdBQVdzQyxTQUFTLDBFQUEwRSxDQUFDO1FBQy9HLElBQUk7VUFDRixJQUFJNkMsS0FBVTtVQUNkLE1BQU1DLGVBQWUsR0FBSTdJLE1BQU0sQ0FBU2tCLGFBQWEsQ0FBQzZFLFNBQVMsQ0FBQyxDQUFDK0MsS0FBSyxDQUFDLENBQUNoSSxHQUFRLEtBQUs7WUFDbkZTLEdBQUcsQ0FBQ3RCLE1BQU0sQ0FBQ2dCLElBQUksQ0FBQyw0Q0FBNENILEdBQUcsRUFBRSxDQUFDO1lBQ2xFLE9BQU8sSUFBSTtVQUNiLENBQUMsQ0FBQyxDQUFDaUksT0FBTyxDQUFDLE1BQU07WUFDZixJQUFJSCxLQUFLLEVBQUVJLFlBQVksQ0FBQ0osS0FBSyxDQUFDO1VBQ2hDLENBQUMsQ0FBQztVQUNGLE1BQU1LLGNBQWMsR0FBRyxJQUFJQyxPQUFPLENBQU8sQ0FBQ0MsT0FBTyxLQUFLO1lBQ3BEUCxLQUFLLEdBQUd4RSxVQUFVLENBQUMsTUFBTTtjQUN2QjdDLEdBQUcsQ0FBQ3RCLE1BQU0sQ0FBQ2dCLElBQUksQ0FBQyxvREFBb0Q4RSxTQUFTLEdBQUcsQ0FBQztjQUNqRm9ELE9BQU8sQ0FBQyxJQUFJLENBQUM7WUFDZixDQUFDLEVBQUUsSUFBSSxDQUFDO1VBQ1YsQ0FBQyxDQUFDO1VBQ0YsSUFBSWhELE1BQXFCLEdBQUcsTUFBTStDLE9BQU8sQ0FBQ0UsSUFBSSxDQUFDLENBQUNQLGVBQWUsRUFBRUksY0FBYyxDQUFDLENBQUM7VUFDakYsSUFBSTlDLE1BQU0sRUFBRTtZQUNWLElBQUl2RixRQUFRLEdBQUdiLE9BQU8sQ0FBQ2EsUUFBUSxJQUFJLFdBQVc7WUFDOUMsSUFBSXVGLE1BQU0sQ0FBQ2tELFVBQVUsQ0FBQyxPQUFPLENBQUMsRUFBRTtjQUM5QixNQUFNQyxPQUFPLEdBQUduRCxNQUFNLENBQUNvRCxLQUFLLENBQUMsMEJBQTBCLENBQUM7Y0FDeEQsSUFBSUQsT0FBTyxFQUFFO2dCQUNYMUksUUFBUSxHQUFHMEksT0FBTyxDQUFDLENBQUMsQ0FBQztnQkFDckJuRCxNQUFNLEdBQUdtRCxPQUFPLENBQUMsQ0FBQyxDQUFDO2NBQ3JCO1lBQ0Y7WUFDQSxPQUFPOUgsR0FBRyxDQUFDYSxNQUFNLENBQUMsR0FBRyxDQUFDLENBQUNDLElBQUksQ0FBQyxFQUFFNkQsTUFBTSxFQUFFdkYsUUFBUSxDQUFDLENBQUMsQ0FBQztVQUNuRDtRQUNGLENBQUMsQ0FBQyxPQUFPNEksV0FBVyxFQUFFO1VBQ3BCakksR0FBRyxDQUFDdEIsTUFBTSxDQUFDYyxLQUFLLENBQUMsMkNBQTJDeUksV0FBVyxFQUFFLENBQUM7UUFDNUU7TUFDRjtNQUNBLE9BQU9oSSxHQUFHLENBQUNhLE1BQU0sQ0FBQyxHQUFHLENBQUMsQ0FBQ0MsSUFBSSxDQUFDO1FBQzFCRCxNQUFNLEVBQUUsT0FBTztRQUNmdEMsT0FBTyxFQUFFO01BQ1gsQ0FBQyxDQUFDO0lBQ0o7O0lBRUEsSUFBSTtNQUNGLE1BQU1HLE1BQU0sR0FBRyxNQUFNRixNQUFNLENBQUNHLFdBQVcsQ0FBQ0osT0FBTyxDQUFDO01BQ2hEeUIsR0FBRztNQUNBYSxNQUFNLENBQUMsR0FBRyxDQUFDO01BQ1hDLElBQUksQ0FBQyxFQUFFNkQsTUFBTSxFQUFFakcsTUFBTSxDQUFDa0csUUFBUSxDQUFDLFFBQVEsQ0FBQyxFQUFFeEYsUUFBUSxFQUFFYixPQUFPLENBQUNhLFFBQVEsSUFBSSxXQUFXLENBQUMsQ0FBQyxDQUFDO0lBQzNGLENBQUMsQ0FBQyxPQUFPNkksVUFBVSxFQUFFO01BQ25CbEksR0FBRyxDQUFDdEIsTUFBTSxDQUFDYyxLQUFLLENBQUMscUdBQXFHMEksVUFBVSxFQUFFLENBQUM7O01BRW5JLElBQUl6SixNQUFNLENBQUNtRixJQUFJLElBQUksQ0FBQ25GLE1BQU0sQ0FBQ21GLElBQUksQ0FBQ0MsUUFBUSxDQUFDLENBQUMsRUFBRTtRQUMxQyxJQUFJO1VBQ0YsTUFBTXNFLFNBQVMsR0FBRyxNQUFNMUosTUFBTSxDQUFDbUYsSUFBSSxDQUFDRSxRQUFRLENBQUMsT0FBTyxFQUFFd0MsR0FBRyxDQUFDLENBQUMsS0FBSztZQUM5RCxJQUFJO2NBQ0YsTUFBTXJDLEdBQUcsR0FBSUQsTUFBTSxDQUFTQyxHQUFHO2NBQy9CLElBQUksQ0FBQ0EsR0FBRyxFQUFFZ0MsSUFBSSxFQUFFdEcsYUFBYSxFQUFFLE9BQU8sSUFBSTtjQUMxQyxJQUFJeUksSUFBUyxHQUFHLElBQUk7Y0FDcEIsSUFBSTtnQkFDRkEsSUFBSSxHQUFHLE1BQU1uRSxHQUFHLENBQUNnQyxJQUFJLENBQUN0RyxhQUFhLENBQUMyRyxHQUFHLENBQUM7Y0FDMUMsQ0FBQyxDQUFDLE9BQU83RyxDQUFDLEVBQUU7Z0JBQ1YsSUFBSTZHLEdBQUcsQ0FBQ0gsUUFBUSxDQUFDLE9BQU8sQ0FBQyxFQUFFO2tCQUN6QixJQUFJLENBQUVpQyxJQUFJLEdBQUcsTUFBTW5FLEdBQUcsQ0FBQ2dDLElBQUksQ0FBQ3RHLGFBQWEsQ0FBQzJHLEdBQUcsQ0FBQ3hHLE9BQU8sQ0FBQyxTQUFTLEVBQUUsaUJBQWlCLENBQUMsQ0FBQyxDQUFFLENBQUMsQ0FBQyxPQUFPdUksRUFBRSxFQUFFLENBQUM7Z0JBQ3RHLENBQUMsTUFBTSxJQUFJL0IsR0FBRyxDQUFDSCxRQUFRLENBQUMsaUJBQWlCLENBQUMsRUFBRTtrQkFDMUMsSUFBSSxDQUFFaUMsSUFBSSxHQUFHLE1BQU1uRSxHQUFHLENBQUNnQyxJQUFJLENBQUN0RyxhQUFhLENBQUMyRyxHQUFHLENBQUN4RyxPQUFPLENBQUMsb0JBQW9CLEVBQUUsT0FBTyxDQUFDLENBQUMsQ0FBRSxDQUFDLENBQUMsT0FBT3VJLEVBQUUsRUFBRSxDQUFDO2dCQUN2RztjQUNGO2NBQ0EsSUFBSUQsSUFBSSxFQUFFO2dCQUNSLElBQUluRSxHQUFHLEVBQUU5QyxJQUFJLEVBQUVtSCxZQUFZLEVBQUU7a0JBQzNCLE9BQU8sTUFBTXJFLEdBQUcsQ0FBQzlDLElBQUksQ0FBQ21ILFlBQVksQ0FBQ0YsSUFBSSxDQUFDO2dCQUMxQztnQkFDQSxPQUFPLElBQUlULE9BQU8sQ0FBQyxDQUFDQyxPQUFPLEtBQUs7a0JBQzlCLE1BQU1XLE1BQU0sR0FBRyxJQUFJQyxVQUFVLENBQUMsQ0FBQztrQkFDL0JELE1BQU0sQ0FBQ0UsU0FBUyxHQUFHLE1BQU1iLE9BQU8sQ0FBQ1csTUFBTSxDQUFDdEosTUFBTSxDQUFDO2tCQUMvQ3NKLE1BQU0sQ0FBQ0csT0FBTyxHQUFHLE1BQU1kLE9BQU8sQ0FBQyxJQUFJLENBQUM7a0JBQ3BDVyxNQUFNLENBQUNJLGFBQWEsQ0FBQ1AsSUFBSSxDQUFDO2dCQUM1QixDQUFDLENBQUM7Y0FDSjtjQUNBLE9BQU8sSUFBSTtZQUNiLENBQUMsQ0FBQyxPQUFPM0ksQ0FBQyxFQUFFO2NBQ1Z1SCxPQUFPLENBQUNDLEdBQUcsQ0FBQywyQ0FBMkN4SCxDQUFDLEVBQUUsQ0FBQztjQUMzRCxPQUFPLElBQUk7WUFDYjtVQUNGLENBQUMsRUFBRSxFQUFFNkcsR0FBRyxFQUFFOUIsU0FBUyxDQUFDLENBQUMsQ0FBQzs7VUFFdEIsSUFBSTJELFNBQVMsSUFBSSxPQUFPQSxTQUFTLEtBQUssUUFBUSxFQUFFO1lBQzlDLElBQUk5SSxRQUFRLEdBQUdiLE9BQU8sQ0FBQ2EsUUFBUSxJQUFJLFdBQVc7WUFDOUMsSUFBSXVGLE1BQU0sR0FBR3VELFNBQVM7WUFDdEIsSUFBSUEsU0FBUyxDQUFDTCxVQUFVLENBQUMsT0FBTyxDQUFDLEVBQUU7Y0FDakMsTUFBTUMsT0FBTyxHQUFHSSxTQUFTLENBQUNILEtBQUssQ0FBQywwQkFBMEIsQ0FBQztjQUMzRCxJQUFJRCxPQUFPLEVBQUU7Z0JBQ1gxSSxRQUFRLEdBQUcwSSxPQUFPLENBQUMsQ0FBQyxDQUFDO2dCQUNyQm5ELE1BQU0sR0FBR21ELE9BQU8sQ0FBQyxDQUFDLENBQUM7Y0FDckI7WUFDRjtZQUNBL0gsR0FBRyxDQUFDdEIsTUFBTSxDQUFDd0QsSUFBSSxDQUFDLHdFQUF3RXNDLFNBQVMsZ0JBQWdCSSxNQUFNLENBQUNhLE1BQU0sRUFBRSxDQUFDO1lBQ2pJLE9BQU94RixHQUFHLENBQUNhLE1BQU0sQ0FBQyxHQUFHLENBQUMsQ0FBQ0MsSUFBSSxDQUFDLEVBQUU2RCxNQUFNLEVBQUV2RixRQUFRLENBQUMsQ0FBQyxDQUFDO1VBQ25EO1FBQ0YsQ0FBQyxDQUFDLE9BQU91SixVQUFVLEVBQUU7VUFDbkI1SSxHQUFHLENBQUN0QixNQUFNLENBQUNjLEtBQUssQ0FBQyxrREFBa0RvSixVQUFVLEVBQUUsQ0FBQztRQUNsRjtNQUNGOztNQUVBO01BQ0EsSUFBSSxPQUFRbkssTUFBTSxDQUFTa0IsYUFBYSxLQUFLLFVBQVUsSUFBSWxCLE1BQU0sQ0FBQ21GLElBQUksSUFBSSxDQUFDbkYsTUFBTSxDQUFDbUYsSUFBSSxDQUFDQyxRQUFRLENBQUMsQ0FBQyxFQUFFO1FBQ2pHLElBQUk7VUFDRixJQUFJd0QsS0FBVTtVQUNkLE1BQU1DLGVBQWUsR0FBSTdJLE1BQU0sQ0FBU2tCLGFBQWEsQ0FBQzZFLFNBQVMsQ0FBQyxDQUFDK0MsS0FBSyxDQUFDLENBQUNoSSxHQUFRLEtBQUs7WUFDbkZTLEdBQUcsQ0FBQ3RCLE1BQU0sQ0FBQ2dCLElBQUksQ0FBQyw0Q0FBNENILEdBQUcsRUFBRSxDQUFDO1lBQ2xFLE9BQU8sSUFBSTtVQUNiLENBQUMsQ0FBQyxDQUFDaUksT0FBTyxDQUFDLE1BQU07WUFDZixJQUFJSCxLQUFLLEVBQUVJLFlBQVksQ0FBQ0osS0FBSyxDQUFDO1VBQ2hDLENBQUMsQ0FBQztVQUNGLE1BQU1LLGNBQWMsR0FBRyxJQUFJQyxPQUFPLENBQU8sQ0FBQ0MsT0FBTyxLQUFLO1lBQ3BEUCxLQUFLLEdBQUd4RSxVQUFVLENBQUMsTUFBTTtjQUN2QjdDLEdBQUcsQ0FBQ3RCLE1BQU0sQ0FBQ2dCLElBQUksQ0FBQyxxREFBcUQ4RSxTQUFTLEdBQUcsQ0FBQztjQUNsRm9ELE9BQU8sQ0FBQyxJQUFJLENBQUM7WUFDZixDQUFDLEVBQUUsS0FBSyxDQUFDO1VBQ1gsQ0FBQyxDQUFDO1VBQ0YsSUFBSWhELE1BQXFCLEdBQUcsTUFBTStDLE9BQU8sQ0FBQ0UsSUFBSSxDQUFDLENBQUNQLGVBQWUsRUFBRUksY0FBYyxDQUFDLENBQUM7VUFDakYsSUFBSTlDLE1BQU0sRUFBRTtZQUNWLElBQUl2RixRQUFRLEdBQUdiLE9BQU8sQ0FBQ2EsUUFBUSxJQUFJLFdBQVc7WUFDOUMsSUFBSXVGLE1BQU0sQ0FBQ2tELFVBQVUsQ0FBQyxPQUFPLENBQUMsRUFBRTtjQUM5QixNQUFNQyxPQUFPLEdBQUduRCxNQUFNLENBQUNvRCxLQUFLLENBQUMsMEJBQTBCLENBQUM7Y0FDeEQsSUFBSUQsT0FBTyxFQUFFO2dCQUNYMUksUUFBUSxHQUFHMEksT0FBTyxDQUFDLENBQUMsQ0FBQztnQkFDckJuRCxNQUFNLEdBQUdtRCxPQUFPLENBQUMsQ0FBQyxDQUFDO2NBQ3JCO1lBQ0Y7WUFDQSxPQUFPOUgsR0FBRyxDQUFDYSxNQUFNLENBQUMsR0FBRyxDQUFDLENBQUNDLElBQUksQ0FBQyxFQUFFNkQsTUFBTSxFQUFFdkYsUUFBUSxDQUFDLENBQUMsQ0FBQztVQUNuRDtRQUNGLENBQUMsQ0FBQyxPQUFPNEksV0FBVyxFQUFFO1VBQ3BCakksR0FBRyxDQUFDdEIsTUFBTSxDQUFDYyxLQUFLLENBQUMsa0VBQWtFeUksV0FBVyxFQUFFLENBQUM7UUFDbkc7TUFDRjtNQUNBLE1BQU1DLFVBQVUsQ0FBQyxDQUFDO0lBQ3BCO0VBQ0YsQ0FBQyxDQUFDLE9BQU9XLEVBQUUsRUFBRTtJQUNYN0ksR0FBRyxDQUFDdEIsTUFBTSxDQUFDYyxLQUFLLENBQUNxSixFQUFFLENBQUM7SUFDcEI1SSxHQUFHLENBQUNhLE1BQU0sQ0FBQyxHQUFHLENBQUMsQ0FBQ0MsSUFBSSxDQUFDO01BQ25CRCxNQUFNLEVBQUUsT0FBTztNQUNmdEMsT0FBTyxFQUFFLHdCQUF3QjtNQUNqQ2dCLEtBQUssRUFBRXFKLEVBQUUsWUFBWUMsS0FBSyxHQUFHRCxFQUFFLENBQUNySyxPQUFPLEdBQUdxSztJQUM1QyxDQUFDLENBQUM7RUFDSjtBQUNGOztBQUVPLGVBQWU3RyxlQUFlQSxDQUFDaEMsR0FBWSxFQUFFQyxHQUFhLEVBQUU7RUFDakU7QUFDRjtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0VBQ0UsSUFBSTtJQUNGLE1BQU0sRUFBRTZCLFVBQVUsR0FBRyxLQUFLLENBQUMsQ0FBQyxHQUFHOUIsR0FBRyxDQUFDK0IsSUFBSTtJQUN2QyxNQUFNdEQsTUFBTSxHQUFHdUIsR0FBRyxDQUFDdkIsTUFBTTtJQUN6QixNQUFNc0ssRUFBRTtJQUNOdEssTUFBTSxFQUFFdUssT0FBTyxJQUFJLElBQUksSUFBSXZLLE1BQU0sRUFBRXVLLE9BQU8sSUFBSSxFQUFFO0lBQzVDLE1BQU1DLGVBQU0sQ0FBQ0MsU0FBUyxDQUFDekssTUFBTSxDQUFDdUssT0FBTyxDQUFDO0lBQ3RDLElBQUk7O0lBRVYsSUFBSSxDQUFDdkssTUFBTSxJQUFJLElBQUksSUFBSUEsTUFBTSxDQUFDcUMsTUFBTSxJQUFJLElBQUksS0FBSyxDQUFDZ0IsVUFBVTtJQUMxRDdCLEdBQUcsQ0FBQ2EsTUFBTSxDQUFDLEdBQUcsQ0FBQyxDQUFDQyxJQUFJLENBQUMsRUFBRUQsTUFBTSxFQUFFLFFBQVEsRUFBRXFJLE1BQU0sRUFBRSxJQUFJLENBQUMsQ0FBQyxDQUFDLENBQUM7SUFDdEQsSUFBSTFLLE1BQU0sSUFBSSxJQUFJO0lBQ3JCd0IsR0FBRyxDQUFDYSxNQUFNLENBQUMsR0FBRyxDQUFDLENBQUNDLElBQUksQ0FBQztNQUNuQkQsTUFBTSxFQUFFckMsTUFBTSxDQUFDcUMsTUFBTTtNQUNyQnFJLE1BQU0sRUFBRUosRUFBRTtNQUNWQyxPQUFPLEVBQUV2SyxNQUFNLENBQUN1SyxPQUFPO01BQ3ZCSSxPQUFPLEVBQUVBO0lBQ1gsQ0FBQyxDQUFDO0VBQ04sQ0FBQyxDQUFDLE9BQU9QLEVBQUUsRUFBRTtJQUNYN0ksR0FBRyxDQUFDdEIsTUFBTSxDQUFDYyxLQUFLLENBQUNxSixFQUFFLENBQUM7SUFDcEI1SSxHQUFHLENBQUNhLE1BQU0sQ0FBQyxHQUFHLENBQUMsQ0FBQ0MsSUFBSSxDQUFDO01BQ25CRCxNQUFNLEVBQUUsT0FBTztNQUNmdEMsT0FBTyxFQUFFLDJCQUEyQjtNQUNwQ2dCLEtBQUssRUFBRXFKO0lBQ1QsQ0FBQyxDQUFDO0VBQ0o7QUFDRjs7QUFFTyxlQUFlUSxTQUFTQSxDQUFDckosR0FBWSxFQUFFQyxHQUFhLEVBQUU7RUFDM0Q7QUFDRjtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtFQUNFLElBQUk7SUFDRixJQUFJRCxHQUFHLEVBQUV2QixNQUFNLEVBQUV1SyxPQUFPLEVBQUU7TUFDeEI7TUFDQTtNQUNBLE1BQU1NLFNBQVMsR0FBRztRQUNoQkMsb0JBQW9CLEVBQUUsR0FBWTtRQUNsQ3JLLElBQUksRUFBRSxXQUFvQjtRQUMxQnNLLEtBQUssRUFBRSxDQUFDO1FBQ1JDLEtBQUssRUFBRTtNQUNULENBQUM7TUFDRCxNQUFNVixFQUFFLEdBQUcvSSxHQUFHLENBQUN2QixNQUFNLENBQUN1SyxPQUFPO01BQ3pCLE1BQU1DLGVBQU0sQ0FBQ0MsU0FBUyxDQUFDbEosR0FBRyxDQUFDdkIsTUFBTSxDQUFDdUssT0FBTyxFQUFFTSxTQUFTLENBQUM7TUFDckQsSUFBSTtNQUNSLE1BQU1JLEdBQUcsR0FBR3BFLE1BQU0sQ0FBQ0MsSUFBSTtRQUNwQndELEVBQUUsQ0FBU2pKLE9BQU8sQ0FBQyxxQ0FBcUMsRUFBRSxFQUFFLENBQUM7UUFDOUQ7TUFDRixDQUFDO01BQ0RHLEdBQUcsQ0FBQzBKLFNBQVMsQ0FBQyxHQUFHLEVBQUU7UUFDakIsY0FBYyxFQUFFLFdBQVc7UUFDM0IsZ0JBQWdCLEVBQUVELEdBQUcsQ0FBQ2pFO01BQ3hCLENBQUMsQ0FBQztNQUNGeEYsR0FBRyxDQUFDMkosR0FBRyxDQUFDRixHQUFHLENBQUM7SUFDZCxDQUFDLE1BQU0sSUFBSSxPQUFPMUosR0FBRyxDQUFDdkIsTUFBTSxLQUFLLFdBQVcsRUFBRTtNQUM1Q3dCLEdBQUcsQ0FBQ2EsTUFBTSxDQUFDLEdBQUcsQ0FBQyxDQUFDQyxJQUFJLENBQUM7UUFDbkJELE1BQU0sRUFBRSxJQUFJO1FBQ1p0QyxPQUFPO1FBQ0w7TUFDSixDQUFDLENBQUM7SUFDSixDQUFDLE1BQU07TUFDTHlCLEdBQUcsQ0FBQ2EsTUFBTSxDQUFDLEdBQUcsQ0FBQyxDQUFDQyxJQUFJLENBQUM7UUFDbkJELE1BQU0sRUFBRWQsR0FBRyxDQUFDdkIsTUFBTSxDQUFDcUMsTUFBTTtRQUN6QnRDLE9BQU8sRUFBRTtNQUNYLENBQUMsQ0FBQztJQUNKO0VBQ0YsQ0FBQyxDQUFDLE9BQU9xSyxFQUFFLEVBQUU7SUFDWDdJLEdBQUcsQ0FBQ3RCLE1BQU0sQ0FBQ2MsS0FBSyxDQUFDcUosRUFBRSxDQUFDO0lBQ3BCNUksR0FBRztJQUNBYSxNQUFNLENBQUMsR0FBRyxDQUFDO0lBQ1hDLElBQUksQ0FBQyxFQUFFRCxNQUFNLEVBQUUsT0FBTyxFQUFFdEMsT0FBTyxFQUFFLHlCQUF5QixFQUFFZ0IsS0FBSyxFQUFFcUosRUFBRSxDQUFDLENBQUMsQ0FBQztFQUM3RTtBQUNGOztBQUVPLGVBQWVnQixpQkFBaUJBLENBQUM3SixHQUFZLEVBQUVDLEdBQWEsRUFBRTtFQUNuRTtBQUNGO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7RUFDRSxJQUFJO0lBQ0ZBLEdBQUcsQ0FBQ2EsTUFBTSxDQUFDLEdBQUcsQ0FBQyxDQUFDQyxJQUFJLENBQUMsRUFBRUQsTUFBTSxFQUFFLE9BQU8sRUFBRUUsUUFBUSxFQUFFLHFCQUFxQixDQUFDLENBQUMsQ0FBQztFQUM1RSxDQUFDLENBQUMsT0FBTzZILEVBQUUsRUFBRTtJQUNYN0ksR0FBRyxDQUFDdEIsTUFBTSxDQUFDYyxLQUFLLENBQUNxSixFQUFFLENBQUM7SUFDcEI1SSxHQUFHLENBQUNhLE1BQU0sQ0FBQyxHQUFHLENBQUMsQ0FBQ0MsSUFBSSxDQUFDO01BQ25CRCxNQUFNLEVBQUUsT0FBTztNQUNmdEMsT0FBTyxFQUFFLDJCQUEyQjtNQUNwQ2dCLEtBQUssRUFBRXFKO0lBQ1QsQ0FBQyxDQUFDO0VBQ0o7QUFDRjs7QUFFTyxlQUFlaUIsY0FBY0EsQ0FBQzlKLEdBQVksRUFBRUMsR0FBYSxFQUFFO0VBQ2hFO0FBQ0Y7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtFQUNFLElBQUk7SUFDRkEsR0FBRyxDQUFDYSxNQUFNLENBQUMsR0FBRyxDQUFDLENBQUNDLElBQUksQ0FBQyxFQUFFRCxNQUFNLEVBQUUsT0FBTyxFQUFFRSxRQUFRLEVBQUUscUJBQXFCLENBQUMsQ0FBQyxDQUFDO0VBQzVFLENBQUMsQ0FBQyxPQUFPNkgsRUFBRSxFQUFFO0lBQ1g3SSxHQUFHLENBQUN0QixNQUFNLENBQUNjLEtBQUssQ0FBQ3FKLEVBQUUsQ0FBQztJQUNwQjVJLEdBQUcsQ0FBQ2EsTUFBTSxDQUFDLEdBQUcsQ0FBQyxDQUFDQyxJQUFJLENBQUM7TUFDbkJELE1BQU0sRUFBRSxPQUFPO01BQ2ZFLFFBQVEsRUFBRSxFQUFFeEMsT0FBTyxFQUFFLDJCQUEyQixFQUFFZ0IsS0FBSyxFQUFFcUosRUFBRSxDQUFDO0lBQzlELENBQUMsQ0FBQztFQUNKO0FBQ0Y7O0FBRU8sZUFBZWtCLGlCQUFpQkEsQ0FBQy9KLEdBQVksRUFBRUMsR0FBYSxFQUFFO0VBQ25FO0FBQ0Y7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0VBQ0UsSUFBSTtJQUNGLE1BQU0sRUFBRStKLEtBQUssRUFBRUMsT0FBTyxHQUFHLEtBQUssRUFBRUMsR0FBRyxHQUFHLEtBQUssRUFBRUMsS0FBSyxHQUFHLEtBQUssQ0FBQyxDQUFDLEdBQUduSyxHQUFHLENBQUMrQixJQUFJOztJQUV2RSxNQUFNcUksWUFBWSxHQUFHLE1BQUFBLENBQU9DLE9BQWUsS0FBSztNQUM5QztNQUNBO01BQ0E7TUFDQTtNQUNBO01BQ0EsTUFBTXpHLElBQUksR0FBSTVELEdBQUcsQ0FBQ3ZCLE1BQU0sQ0FBU21GLElBQUk7TUFDckMsSUFBSUEsSUFBSSxFQUFFO1FBQ1IsSUFBSTtVQUNGLE1BQU1BLElBQUksQ0FBQ0UsUUFBUSxDQUFDLENBQUM4QyxFQUFVLEtBQUs7WUFDbEMsTUFBTTdDLEdBQUcsR0FBSUMsTUFBTSxDQUFTQyxHQUFHO1lBQy9CLElBQUlGLEdBQUcsSUFBSUEsR0FBRyxDQUFDdUcsT0FBTyxJQUFJLE9BQU92RyxHQUFHLENBQUN1RyxPQUFPLENBQUNQLGlCQUFpQixLQUFLLFVBQVUsRUFBRTtjQUM3RSxPQUFPaEcsR0FBRyxDQUFDdUcsT0FBTyxDQUFDUCxpQkFBaUIsQ0FBQ25ELEVBQUUsQ0FBQztZQUMxQztZQUNBO1lBQ0EsSUFBSTdDLEdBQUcsSUFBSUEsR0FBRyxDQUFDRyxRQUFRLElBQUlILEdBQUcsQ0FBQ0csUUFBUSxDQUFDcUcsYUFBYSxFQUFFO2NBQ3JELE9BQU94RyxHQUFHLENBQUNHLFFBQVEsQ0FBQ3FHLGFBQWEsQ0FBQ0MsbUJBQW1CLENBQUM1RCxFQUFFLENBQUM7WUFDM0Q7WUFDQSxNQUFNLElBQUlrQyxLQUFLLENBQUMsNkNBQTZDLENBQUM7VUFDaEUsQ0FBQyxFQUFFdUIsT0FBTyxDQUFDO1VBQ1hySyxHQUFHLENBQUN0QixNQUFNLENBQUN3RCxJQUFJLENBQUMsdUNBQXVDbUksT0FBTyxFQUFFLENBQUM7VUFDakU7UUFDRixDQUFDLENBQUMsT0FBT0ksTUFBTSxFQUFFO1VBQ2Z6SyxHQUFHLENBQUN0QixNQUFNLENBQUNnQixJQUFJLENBQUMsd0NBQXdDMkssT0FBTyxLQUFLSSxNQUFNLEVBQUUsQ0FBQztRQUMvRTtNQUNGO01BQ0E7TUFDQSxNQUFNekssR0FBRyxDQUFDdkIsTUFBTSxDQUFDc0wsaUJBQWlCLENBQUNNLE9BQU8sQ0FBQztJQUM3QyxDQUFDOztJQUVELElBQUlILEdBQUcsRUFBRTtNQUNQLElBQUlRLFFBQVE7TUFDWixJQUFJVCxPQUFPLEVBQUU7UUFDWCxNQUFNVSxNQUFNLEdBQUcsTUFBTTNLLEdBQUcsQ0FBQ3ZCLE1BQU0sQ0FBQ21NLFlBQVksQ0FBQyxLQUFLLENBQUM7UUFDbkRGLFFBQVEsR0FBR0MsTUFBTSxDQUFDMUosR0FBRyxDQUFDLENBQUM0SixDQUFNLEtBQUtBLENBQUMsQ0FBQ2pFLEVBQUUsQ0FBQ0UsV0FBVyxDQUFDO01BQ3JELENBQUMsTUFBTTtRQUNMLE1BQU1nRSxLQUFLLEdBQUcsTUFBTTlLLEdBQUcsQ0FBQ3ZCLE1BQU0sQ0FBQ3NNLGNBQWMsQ0FBQyxDQUFDO1FBQy9DTCxRQUFRLEdBQUdJLEtBQUssQ0FBQzdKLEdBQUcsQ0FBQyxDQUFDK0osQ0FBTSxLQUFLQSxDQUFDLENBQUNwRSxFQUFFLENBQUNFLFdBQVcsQ0FBQztNQUNwRDtNQUNBLEtBQUssTUFBTXVELE9BQU8sSUFBSUssUUFBUSxFQUFFO1FBQzlCLE1BQU1OLFlBQVksQ0FBQ0MsT0FBTyxDQUFDO01BQzdCO0lBQ0YsQ0FBQyxNQUFNO01BQ0wsS0FBSyxNQUFNQSxPQUFPLElBQUksSUFBQVkseUJBQWMsRUFBQ2pCLEtBQUssRUFBRUMsT0FBTyxFQUFFLEtBQUssRUFBRUUsS0FBSyxDQUFDLEVBQUU7UUFDbEUsTUFBTUMsWUFBWSxDQUFDQyxPQUFPLENBQUM7TUFDN0I7SUFDRjs7SUFFQXBLLEdBQUcsQ0FBQ2EsTUFBTSxDQUFDLEdBQUcsQ0FBQyxDQUFDQyxJQUFJLENBQUM7TUFDbkJELE1BQU0sRUFBRSxTQUFTO01BQ2pCRSxRQUFRLEVBQUUsRUFBRXhDLE9BQU8sRUFBRSw2QkFBNkIsQ0FBQztJQUNyRCxDQUFDLENBQUM7RUFDSixDQUFDLENBQUMsT0FBT2dCLEtBQUssRUFBRTtJQUNkUSxHQUFHLENBQUN0QixNQUFNLENBQUNjLEtBQUssQ0FBQ0EsS0FBSyxDQUFDO0lBQ3ZCUyxHQUFHLENBQUNhLE1BQU0sQ0FBQyxHQUFHLENBQUMsQ0FBQ0MsSUFBSSxDQUFDO01BQ25CRCxNQUFNLEVBQUUsT0FBTztNQUNmdEMsT0FBTyxFQUFFLDZCQUE2QjtNQUN0Q2dCLEtBQUssRUFBRUE7SUFDVCxDQUFDLENBQUM7RUFDSjtBQUNGOztBQUVPLGVBQWUwTCxpQkFBaUJBLENBQUNsTCxHQUFZLEVBQUVDLEdBQWEsRUFBRTtFQUNuRTtBQUNGO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7RUFDRSxJQUFJO0lBQ0YsTUFBTSxFQUFFa0wsUUFBUSxHQUFHLElBQUksQ0FBQyxDQUFDLEdBQUduTCxHQUFHLENBQUMrQixJQUFJOztJQUVwQyxNQUFNL0IsR0FBRyxDQUFDdkIsTUFBTSxDQUFDeU0saUJBQWlCLENBQUNDLFFBQVEsQ0FBQzs7SUFFNUNsTCxHQUFHLENBQUNhLE1BQU0sQ0FBQyxHQUFHLENBQUMsQ0FBQ0MsSUFBSSxDQUFDO01BQ25CRCxNQUFNLEVBQUUsU0FBUztNQUNqQkUsUUFBUSxFQUFFLEVBQUV4QyxPQUFPLEVBQUUsa0NBQWtDLENBQUM7SUFDMUQsQ0FBQyxDQUFDO0VBQ0osQ0FBQyxDQUFDLE9BQU9nQixLQUFLLEVBQUU7SUFDZFMsR0FBRyxDQUFDYSxNQUFNLENBQUMsR0FBRyxDQUFDLENBQUNDLElBQUksQ0FBQztNQUNuQkQsTUFBTSxFQUFFLE9BQU87TUFDZnRDLE9BQU8sRUFBRSw4QkFBOEI7TUFDdkNnQixLQUFLLEVBQUVBO0lBQ1QsQ0FBQyxDQUFDO0VBQ0o7QUFDRjs7QUFFTyxlQUFlNEwsbUJBQW1CQSxDQUFDcEwsR0FBWSxFQUFFQyxHQUFhLEVBQUU7RUFDckU7QUFDRjtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7RUFDRSxJQUFJO0lBQ0ZBLEdBQUcsQ0FBQ2EsTUFBTSxDQUFDLEdBQUcsQ0FBQyxDQUFDQyxJQUFJLENBQUMsTUFBTWYsR0FBRyxDQUFDdkIsTUFBTSxDQUFDMk0sbUJBQW1CLENBQUNwTCxHQUFHLENBQUMrQixJQUFJLENBQUMsQ0FBQztFQUN0RSxDQUFDLENBQUMsT0FBT3ZDLEtBQUssRUFBRTtJQUNkUyxHQUFHLENBQUNhLE1BQU0sQ0FBQyxHQUFHLENBQUMsQ0FBQ0MsSUFBSSxDQUFDO01BQ25CRCxNQUFNLEVBQUUsT0FBTztNQUNmdEMsT0FBTyxFQUFFLGdDQUFnQztNQUN6Q2dCLEtBQUssRUFBRUE7SUFDVCxDQUFDLENBQUM7RUFDSjtBQUNGIiwiaWdub3JlTGlzdCI6W119