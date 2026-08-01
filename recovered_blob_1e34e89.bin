"use strict";var _interopRequireDefault = require("@babel/runtime/helpers/interopRequireDefault");Object.defineProperty(exports, "__esModule", { value: true });exports.checkConnectionSession = checkConnectionSession;exports.closeSession = closeSession;exports.download = download;exports.downloadMediaByMessage = downloadMediaByMessage;exports.editBusinessProfile = editBusinessProfile;exports.getMediaByMessage = getMediaByMessage;exports.getQrCode = getQrCode;exports.getSessionState = getSessionState;exports.killServiceWorker = killServiceWorker;exports.logOutSession = logOutSession;exports.restartService = restartService;exports.setOnlinePresence = setOnlinePresence;exports.showAllSessions = showAllSessions;exports.startAllSessions = startAllSessions;exports.startSession = startSession;exports.subscribePresence = subscribePresence;
















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
        SessionUtil.forceKillSession(session);
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

  // Normalize 4-part message ID (fromMe_chatId_msgId_participantLid) to 3-part standard ID
  let lookupId = messageId;
  const parts = messageId ? messageId.split('_') : [];
  if (parts.length === 4) {
    lookupId = `${parts[0]}_${parts[1]}_${parts[2]}`;
  }

  try {
    let message = null;

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
      } catch (err) {}
      if (!message && lookupId !== messageId) {
        try {
          message = await client.getMessageById(messageId);
        } catch (_) {}
      }

      // Robust fallback: query WhatsApp Web Store via WPP.chat.getMsg or scanning chat messages by ID prefix
      if (!message && client.page && !client.page.isClosed()) {
        try {
          const browserMsg = await client.page.evaluate(async (mId, lId) => {
            try {
              if (window.WPP && window.WPP.chat) {
                let msg = await window.WPP.chat.getMsg(mId).catch(() => null)
                       || await window.WPP.chat.getMsg(lId).catch(() => null);
                if (!msg && lId) {
                  const parts = lId.split('_');
                  if (parts.length >= 2) {
                    const chatId = parts[1];
                    const msgs = await window.WPP.chat.getMessages(chatId, { count: 100 }).catch(() => []);
                    msg = msgs.find((m) => m && m.id && (m.id._serialized === mId || m.id._serialized === lId || m.id._serialized.startsWith(lId)));
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
            const resultData = await Promise.race([
              client.page.evaluate(async (msgId, lId) => {
                try {
                  if (window.WPP && window.WPP.chat) {
                    let msg = await window.WPP.chat.getMsg(msgId).catch(() => null)
                           || await window.WPP.chat.getMsg(lId).catch(() => null);
                    if (!msg && lId) {
                      const parts = lId.split('_');
                      if (parts.length >= 2) {
                        const chatId = parts[1];
                        const msgs = await window.WPP.chat.getMessages(chatId, { count: 100 }).catch(() => []);
                        msg = msgs.find((m) => m && m.id && (m.id._serialized === msgId || m.id._serialized === lId || m.id._serialized.startsWith(lId)));
                      }
                    }

                    let targetId = (msg && msg.id) ? (msg.id._serialized || msg.id) : msgId;
                    const blob = await window.WPP.chat.downloadMedia(targetId).catch(() => null)
                              || await window.WPP.chat.downloadMedia(msgId).catch(() => null)
                              || await window.WPP.chat.downloadMedia(lId).catch(() => null);
                    let b64 = null;
                    if (blob && blob instanceof Blob) {
                      b64 = await new Promise((resolve) => {
                        const reader = new FileReader();
                        reader.onloadend = () => resolve(reader.result);
                        reader.readAsDataURL(blob);
                      });
                    }
                    return { base64Data: b64, msgObj: msg ? JSON.parse(JSON.stringify(msg)) : null };
                  }
                  if (window.WAPI && typeof window.WAPI.downloadFile === 'function') {
                    const b64 = await window.WAPI.downloadFile(msgId).catch(() => null)
                             || await window.WAPI.downloadFile(lId).catch(() => null);
                    if (b64) return { base64Data: b64, msgObj: null };
                  }
                } catch (err) {
                  return null;
                }
                return null;
              }, messageId, lookupId),
              new Promise((resolve) => setTimeout(() => resolve(null), 6000))
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
        message: `Message ${messageId} not found`
      });
    }

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

    if (client.page && client.page.isClosed()) {
      req.logger.warn(`Browser page is closed for session when downloading media ${messageId}`);
      return res.status(503).json({
        status: 'error',
        message: 'Browser session is closed or re-connecting',
      });
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

    // Primary approach: Try WPPConnect's downloadMedia using active browser context with short 2.5s timeout
    if (typeof client.downloadMedia === 'function' && client.page && !client.page.isClosed()) {
      try {
        let timer;
        const downloadPromise = (client.downloadMedia(lookupId).catch(() => null)
                             || client.downloadMedia(messageId).catch(() => null)).finally(() => {
          if (timer) clearTimeout(timer);
        });
        const timeoutPromise = new Promise((resolve) => {
          timer = setTimeout(() => {
            req.logger.warn(`Timeout 2500ms downloading media via Puppeteer for ${messageId}`);
            resolve(null);
          }, 2500);
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
          req.logger.info(`Successfully downloaded media via client.downloadMedia for ${messageId}`);
          return res.status(200).json({ base64, mimetype });
        }
      } catch (dlErr) {
        req.logger.warn(`Primary client.downloadMedia failed for ${messageId}: ${dlErr}. Falling back to decryptFile...`);
      }
    }

    try {
      const buffer = await client.decryptFile(message);
      return res
        .status(200)
        .json({ base64: buffer.toString('base64'), mimetype: message.mimetype || 'audio/ogg' });
    } catch (decryptErr) {
      req.logger.error(`decryptFile failed for ${messageId}: ${decryptErr}`);
      throw decryptErr;
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
//# sourceMappingURL=data:application/json;charset=utf-8;base64,eyJ2ZXJzaW9uIjozLCJuYW1lcyI6WyJfZnMiLCJfaW50ZXJvcFJlcXVpcmVEZWZhdWx0IiwicmVxdWlyZSIsIl9taW1lVHlwZXMiLCJfcXJjb2RlIiwiX3BhY2thZ2UiLCJfY29uZmlnIiwiX2NyZWF0ZVNlc3Npb25VdGlsIiwiX2Z1bmN0aW9ucyIsIl9nZXRBbGxUb2tlbnMiLCJfc2Vzc2lvblV0aWwiLCJTZXNzaW9uVXRpbCIsIkNyZWF0ZVNlc3Npb25VdGlsIiwiZG93bmxvYWRGaWxlRnVuY3Rpb24iLCJtZXNzYWdlIiwiY2xpZW50IiwibG9nZ2VyIiwiYnVmZmVyIiwiZGVjcnlwdEZpbGUiLCJmaWxlbmFtZSIsInQiLCJmcyIsImV4aXN0c1N5bmMiLCJyZXN1bHQiLCJ0eXBlIiwibWltZSIsImV4dGVuc2lvbiIsIm1pbWV0eXBlIiwid3JpdGVGaWxlIiwiZXJyIiwiZXJyb3IiLCJlIiwid2FybiIsImRvd25sb2FkTWVkaWEiLCJkb3dubG9hZCIsInBhdGgiLCJyZXBsYWNlIiwic3RhcnRBbGxTZXNzaW9ucyIsInJlcSIsInJlcyIsInNlY3JldGtleSIsInBhcmFtcyIsImF1dGhvcml6YXRpb24iLCJ0b2tlbiIsImhlYWRlcnMiLCJ0b2tlbkRlY3J5cHQiLCJ1bmRlZmluZWQiLCJzcGxpdCIsImFsbFNlc3Npb25zIiwiZ2V0QWxsVG9rZW5zIiwic2VydmVyT3B0aW9ucyIsInNlY3JldEtleSIsInN0YXR1cyIsImpzb24iLCJyZXNwb25zZSIsIm1hcCIsInNlc3Npb24iLCJ1dGlsIiwib3BlbmRhdGEiLCJzaG93QWxsU2Vzc2lvbnMiLCJhcnIiLCJPYmplY3QiLCJrZXlzIiwiY2xpZW50c0FycmF5IiwiZm9yRWFjaCIsIml0ZW0iLCJwdXNoIiwic3RhcnRTZXNzaW9uIiwid2FpdFFyQ29kZSIsImJvZHkiLCJnZXRTZXNzaW9uU3RhdGUiLCJjbG9zZVNlc3Npb24iLCJpbmZvIiwic2hvdWxkQ2xvc2UiLCJmb3JjZUtpbGxTZXNzaW9uIiwiY2xvc2UiLCJpbyIsImVtaXQiLCJjYWxsV2ViSG9vayIsImNvbm5lY3RlZCIsImxvZ091dFNlc3Npb24iLCJsb2dvdXQiLCJkZWxldGVTZXNzaW9uT25BcnJheSIsInNldFRpbWVvdXQiLCJwYXRoVXNlckRhdGEiLCJjb25maWciLCJjdXN0b21Vc2VyRGF0YURpciIsInBhdGhUb2tlbnMiLCJfX2Rpcm5hbWUiLCJwcm9taXNlcyIsInJtIiwicmVjdXJzaXZlIiwibWF4UmV0cmllcyIsImZvcmNlIiwicmV0cnlEZWxheSIsImNoZWNrQ29ubmVjdGlvblNlc3Npb24iLCJpc0Nvbm5lY3RlZCIsImRvd25sb2FkTWVkaWFCeU1lc3NhZ2UiLCJtZXNzYWdlSWQiLCJnZXRNZXNzYWdlQnlJZCIsImlzTWVkaWEiLCJpc01NUyIsImJhc2U2NCIsInRvU3RyaW5nIiwiZ2V0TWVkaWFCeU1lc3NhZ2UiLCJtZWRpYUtleSIsImNsaWVudFVybCIsImRhdGEiLCJCdWZmZXIiLCJmcm9tIiwicGFydHMiLCJsZW5ndGgiLCJjaGF0SWQiLCJsb2FkRWFybGllck1lc3NhZ2VzIiwicmV0cnlFcnIiLCJsb2FkRXJyIiwibWVkaWFVcmwiLCJkZXByZWNhdGVkTW1zM1VybCIsInRpbWVyIiwiZG93bmxvYWRQcm9taXNlIiwiZmluYWxseSIsImNsZWFyVGltZW91dCIsInRpbWVvdXRQcm9taXNlIiwiUHJvbWlzZSIsIl8iLCJyZWplY3QiLCJFcnJvciIsInJhY2UiLCJzdGFydHNXaXRoIiwibWF0Y2hlcyIsIm1hdGNoIiwiZG93bmxvYWRFcnIiLCJkZWNyeXB0RXJyIiwiZnJlc2hNZXNzYWdlIiwiZnJlc2hEZWNyeXB0RXJyIiwiZXgiLCJxciIsInVybGNvZGUiLCJRUkNvZGUiLCJ0b0RhdGFVUkwiLCJxcmNvZGUiLCJ2ZXJzaW9uIiwiZ2V0UXJDb2RlIiwicXJPcHRpb25zIiwiZXJyb3JDb3JyZWN0aW9uTGV2ZWwiLCJzY2FsZSIsIndpZHRoIiwiaW1nIiwid3JpdGVIZWFkIiwiZW5kIiwia2lsbFNlcnZpY2VXb3JrZXIiLCJyZXN0YXJ0U2VydmljZSIsInN1YnNjcmliZVByZXNlbmNlIiwicGhvbmUiLCJpc0dyb3VwIiwiYWxsIiwiaXNMaWQiLCJzdWJzY3JpYmVPbmUiLCJjb250YXRvIiwicGFnZSIsImV2YWx1YXRlIiwiaWQiLCJ3cHAiLCJ3aW5kb3ciLCJXUFAiLCJjb250YWN0Iiwid2hhdHNhcHAiLCJQcmVzZW5jZVV0aWxzIiwic3Vic2NyaWJlVG9QcmVzZW5jZSIsIndwcEVyciIsImNvbnRhY3RzIiwiZ3JvdXBzIiwiZ2V0QWxsR3JvdXBzIiwicCIsIl9zZXJpYWxpemVkIiwiY2hhdHMiLCJnZXRBbGxDb250YWN0cyIsImMiLCJjb250YWN0VG9BcnJheSIsInNldE9ubGluZVByZXNlbmNlIiwiaXNPbmxpbmUiLCJlZGl0QnVzaW5lc3NQcm9maWxlIl0sInNvdXJjZXMiOlsiLi4vLi4vc3JjL2NvbnRyb2xsZXIvc2Vzc2lvbkNvbnRyb2xsZXIudHMiXSwic291cmNlc0NvbnRlbnQiOlsiLypcbiAqIENvcHlyaWdodCAyMDIxIFdQUENvbm5lY3QgVGVhbVxuICpcbiAqIExpY2Vuc2VkIHVuZGVyIHRoZSBBcGFjaGUgTGljZW5zZSwgVmVyc2lvbiAyLjAgKHRoZSBcIkxpY2Vuc2VcIik7XG4gKiB5b3UgbWF5IG5vdCB1c2UgdGhpcyBmaWxlIGV4Y2VwdCBpbiBjb21wbGlhbmNlIHdpdGggdGhlIExpY2Vuc2UuXG4gKiBZb3UgbWF5IG9idGFpbiBhIGNvcHkgb2YgdGhlIExpY2Vuc2UgYXRcbiAqXG4gKiAgICAgaHR0cDovL3d3dy5hcGFjaGUub3JnL2xpY2Vuc2VzL0xJQ0VOU0UtMi4wXG4gKlxuICogVW5sZXNzIHJlcXVpcmVkIGJ5IGFwcGxpY2FibGUgbGF3IG9yIGFncmVlZCB0byBpbiB3cml0aW5nLCBzb2Z0d2FyZVxuICogZGlzdHJpYnV0ZWQgdW5kZXIgdGhlIExpY2Vuc2UgaXMgZGlzdHJpYnV0ZWQgb24gYW4gXCJBUyBJU1wiIEJBU0lTLFxuICogV0lUSE9VVCBXQVJSQU5USUVTIE9SIENPTkRJVElPTlMgT0YgQU5ZIEtJTkQsIGVpdGhlciBleHByZXNzIG9yIGltcGxpZWQuXG4gKiBTZWUgdGhlIExpY2Vuc2UgZm9yIHRoZSBzcGVjaWZpYyBsYW5ndWFnZSBnb3Zlcm5pbmcgcGVybWNsZWFyU2Vzc2lvbmlzc2lvbnMgYW5kXG4gKiBsaW1pdGF0aW9ucyB1bmRlciB0aGUgTGljZW5zZS5cbiAqL1xuaW1wb3J0IHsgTWVzc2FnZSwgV2hhdHNhcHAgfSBmcm9tICdAd3BwY29ubmVjdC10ZWFtL3dwcGNvbm5lY3QnO1xuaW1wb3J0IHsgUmVxdWVzdCwgUmVzcG9uc2UgfSBmcm9tICdleHByZXNzJztcbmltcG9ydCBmcyBmcm9tICdmcyc7XG5pbXBvcnQgbWltZSBmcm9tICdtaW1lLXR5cGVzJztcbmltcG9ydCBRUkNvZGUgZnJvbSAncXJjb2RlJztcbmltcG9ydCB7IExvZ2dlciB9IGZyb20gJ3dpbnN0b24nO1xuXG5pbXBvcnQgeyB2ZXJzaW9uIH0gZnJvbSAnLi4vLi4vcGFja2FnZS5qc29uJztcbmltcG9ydCBjb25maWcgZnJvbSAnLi4vY29uZmlnJztcbmltcG9ydCBDcmVhdGVTZXNzaW9uVXRpbCBmcm9tICcuLi91dGlsL2NyZWF0ZVNlc3Npb25VdGlsJztcbmltcG9ydCB7IGNhbGxXZWJIb29rLCBjb250YWN0VG9BcnJheSB9IGZyb20gJy4uL3V0aWwvZnVuY3Rpb25zJztcbmltcG9ydCBnZXRBbGxUb2tlbnMgZnJvbSAnLi4vdXRpbC9nZXRBbGxUb2tlbnMnO1xuaW1wb3J0IHsgY2xpZW50c0FycmF5LCBkZWxldGVTZXNzaW9uT25BcnJheSB9IGZyb20gJy4uL3V0aWwvc2Vzc2lvblV0aWwnO1xuXG5jb25zdCBTZXNzaW9uVXRpbCA9IG5ldyBDcmVhdGVTZXNzaW9uVXRpbCgpO1xuXG5hc3luYyBmdW5jdGlvbiBkb3dubG9hZEZpbGVGdW5jdGlvbihcbiAgbWVzc2FnZTogTWVzc2FnZSxcbiAgY2xpZW50OiBXaGF0c2FwcCxcbiAgbG9nZ2VyOiBMb2dnZXJcbikge1xuICB0cnkge1xuICAgIGNvbnN0IGJ1ZmZlciA9IGF3YWl0IGNsaWVudC5kZWNyeXB0RmlsZShtZXNzYWdlKTtcblxuICAgIGNvbnN0IGZpbGVuYW1lID0gYC4vV2hhdHNBcHBJbWFnZXMvZmlsZSR7bWVzc2FnZS50fWA7XG4gICAgaWYgKCFmcy5leGlzdHNTeW5jKGZpbGVuYW1lKSkge1xuICAgICAgbGV0IHJlc3VsdCA9ICcnO1xuICAgICAgaWYgKG1lc3NhZ2UudHlwZSA9PT0gJ3B0dCcpIHtcbiAgICAgICAgcmVzdWx0ID0gYCR7ZmlsZW5hbWV9Lm9nYWA7XG4gICAgICB9IGVsc2Uge1xuICAgICAgICByZXN1bHQgPSBgJHtmaWxlbmFtZX0uJHttaW1lLmV4dGVuc2lvbihtZXNzYWdlLm1pbWV0eXBlKX1gO1xuICAgICAgfVxuXG4gICAgICBhd2FpdCBmcy53cml0ZUZpbGUocmVzdWx0LCBidWZmZXIsIChlcnIpID0+IHtcbiAgICAgICAgaWYgKGVycikge1xuICAgICAgICAgIGxvZ2dlci5lcnJvcihlcnIpO1xuICAgICAgICB9XG4gICAgICB9KTtcblxuICAgICAgcmV0dXJuIHJlc3VsdDtcbiAgICB9IGVsc2Uge1xuICAgICAgcmV0dXJuIGAke2ZpbGVuYW1lfS4ke21pbWUuZXh0ZW5zaW9uKG1lc3NhZ2UubWltZXR5cGUpfWA7XG4gICAgfVxuICB9IGNhdGNoIChlKSB7XG4gICAgbG9nZ2VyLmVycm9yKGUpO1xuICAgIGxvZ2dlci53YXJuKFxuICAgICAgJ0Vycm8gYW8gZGVzY3JpcHRvZ3JhZmFyIGEgbWlkaWEsIHRlbnRhbmRvIGZhemVyIG8gZG93bmxvYWQgZGlyZXRvLi4uJ1xuICAgICk7XG4gICAgdHJ5IHtcbiAgICAgIGNvbnN0IGJ1ZmZlciA9IGF3YWl0IGNsaWVudC5kb3dubG9hZE1lZGlhKG1lc3NhZ2UpO1xuICAgICAgY29uc3QgZmlsZW5hbWUgPSBgLi9XaGF0c0FwcEltYWdlcy9maWxlJHttZXNzYWdlLnR9YDtcbiAgICAgIGlmICghZnMuZXhpc3RzU3luYyhmaWxlbmFtZSkpIHtcbiAgICAgICAgbGV0IHJlc3VsdCA9ICcnO1xuICAgICAgICBpZiAobWVzc2FnZS50eXBlID09PSAncHR0Jykge1xuICAgICAgICAgIHJlc3VsdCA9IGAke2ZpbGVuYW1lfS5vZ2FgO1xuICAgICAgICB9IGVsc2Uge1xuICAgICAgICAgIHJlc3VsdCA9IGAke2ZpbGVuYW1lfS4ke21pbWUuZXh0ZW5zaW9uKG1lc3NhZ2UubWltZXR5cGUpfWA7XG4gICAgICAgIH1cblxuICAgICAgICBhd2FpdCBmcy53cml0ZUZpbGUocmVzdWx0LCBidWZmZXIsIChlcnIpID0+IHtcbiAgICAgICAgICBpZiAoZXJyKSB7XG4gICAgICAgICAgICBsb2dnZXIuZXJyb3IoZXJyKTtcbiAgICAgICAgICB9XG4gICAgICAgIH0pO1xuXG4gICAgICAgIHJldHVybiByZXN1bHQ7XG4gICAgICB9IGVsc2Uge1xuICAgICAgICByZXR1cm4gYCR7ZmlsZW5hbWV9LiR7bWltZS5leHRlbnNpb24obWVzc2FnZS5taW1ldHlwZSl9YDtcbiAgICAgIH1cbiAgICB9IGNhdGNoIChlKSB7XG4gICAgICBsb2dnZXIuZXJyb3IoZSk7XG4gICAgICBsb2dnZXIud2FybignTsOjbyBmb2kgcG9zc8OtdmVsIGJhaXhhciBhIG3DrWRpYS4uLicpO1xuICAgIH1cbiAgfVxufVxuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24gZG93bmxvYWQobWVzc2FnZTogYW55LCBjbGllbnQ6IGFueSwgbG9nZ2VyOiBhbnkpIHtcbiAgdHJ5IHtcbiAgICBjb25zdCBwYXRoID0gYXdhaXQgZG93bmxvYWRGaWxlRnVuY3Rpb24obWVzc2FnZSwgY2xpZW50LCBsb2dnZXIpO1xuICAgIHJldHVybiBwYXRoPy5yZXBsYWNlKCcuLycsICcnKTtcbiAgfSBjYXRjaCAoZSkge1xuICAgIGxvZ2dlci5lcnJvcihlKTtcbiAgfVxufVxuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24gc3RhcnRBbGxTZXNzaW9ucyhcbiAgcmVxOiBSZXF1ZXN0LFxuICByZXM6IFJlc3BvbnNlXG4pOiBQcm9taXNlPGFueT4ge1xuICAvKipcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIkF1dGhcIl1cbiAgICAgI3N3YWdnZXIuYXV0b0JvZHk9ZmFsc2VcbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAnc3RhcnRBbGxTZXNzaW9ucydcbiAgICAgI3N3YWdnZXIuc2VjdXJpdHkgPSBbe1xuICAgICAgICAgICAgXCJiZWFyZXJBdXRoXCI6IFtdXG4gICAgIH1dXG4gICAgICNzd2FnZ2VyLnBhcmFtZXRlcnNbXCJzZXNzaW9uXCJdID0ge1xuICAgICAgc2NoZW1hOiAnTkVSRFdIQVRTX0FNRVJJQ0EnXG4gICAgIH1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlY3JldGtleVwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ1RISVNJU01ZU0VDVVJFQ09ERSdcbiAgICAgfVxuICAgKi9cbiAgY29uc3QgeyBzZWNyZXRrZXkgfSA9IHJlcS5wYXJhbXM7XG4gIGNvbnN0IHsgYXV0aG9yaXphdGlvbjogdG9rZW4gfSA9IHJlcS5oZWFkZXJzO1xuXG4gIGxldCB0b2tlbkRlY3J5cHQgPSAnJztcblxuICBpZiAoc2VjcmV0a2V5ID09PSB1bmRlZmluZWQpIHtcbiAgICB0b2tlbkRlY3J5cHQgPSAodG9rZW4gYXMgYW55KS5zcGxpdCgnICcpWzBdO1xuICB9IGVsc2Uge1xuICAgIHRva2VuRGVjcnlwdCA9IHNlY3JldGtleTtcbiAgfVxuXG4gIGNvbnN0IGFsbFNlc3Npb25zID0gYXdhaXQgZ2V0QWxsVG9rZW5zKHJlcSk7XG5cbiAgaWYgKHRva2VuRGVjcnlwdCAhPT0gcmVxLnNlcnZlck9wdGlvbnMuc2VjcmV0S2V5KSB7XG4gICAgcmVzLnN0YXR1cyg0MDApLmpzb24oe1xuICAgICAgcmVzcG9uc2U6ICdlcnJvcicsXG4gICAgICBtZXNzYWdlOiAnVGhlIHRva2VuIGlzIGluY29ycmVjdCcsXG4gICAgfSk7XG4gIH1cblxuICBhbGxTZXNzaW9ucy5tYXAoYXN5bmMgKHNlc3Npb246IHN0cmluZykgPT4ge1xuICAgIGNvbnN0IHV0aWwgPSBuZXcgQ3JlYXRlU2Vzc2lvblV0aWwoKTtcbiAgICBhd2FpdCB1dGlsLm9wZW5kYXRhKHJlcSwgc2Vzc2lvbik7XG4gIH0pO1xuXG4gIHJldHVybiBhd2FpdCByZXNcbiAgICAuc3RhdHVzKDIwMSlcbiAgICAuanNvbih7IHN0YXR1czogJ3N1Y2Nlc3MnLCBtZXNzYWdlOiAnU3RhcnRpbmcgYWxsIHNlc3Npb25zJyB9KTtcbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIHNob3dBbGxTZXNzaW9ucyhcbiAgcmVxOiBSZXF1ZXN0LFxuICByZXM6IFJlc3BvbnNlXG4pOiBQcm9taXNlPGFueT4ge1xuICAvKipcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIkF1dGhcIl1cbiAgICAgI3N3YWdnZXIuYXV0b0JvZHk9ZmFsc2VcbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAnc2hvd0FsbFNlc3Npb25zJ1xuICAgICAjc3dhZ2dlci5hdXRvUXVlcnk9ZmFsc2VcbiAgICAgI3N3YWdnZXIuYXV0b0hlYWRlcnM9ZmFsc2VcbiAgICAgI3N3YWdnZXIuc2VjdXJpdHkgPSBbe1xuICAgICAgICAgICAgXCJiZWFyZXJBdXRoXCI6IFtdXG4gICAgIH1dXG4gICAgICNzd2FnZ2VyLnBhcmFtZXRlcnNbXCJzZWNyZXRrZXlcIl0gPSB7XG4gICAgICBzY2hlbWE6ICdUSElTSVNNWVNFQ1VSRVRPS0VOJ1xuICAgICB9XG4gICAqL1xuICBjb25zdCB7IHNlY3JldGtleSB9ID0gcmVxLnBhcmFtcztcbiAgY29uc3QgeyBhdXRob3JpemF0aW9uOiB0b2tlbiB9ID0gcmVxLmhlYWRlcnM7XG5cbiAgbGV0IHRva2VuRGVjcnlwdDogYW55ID0gJyc7XG5cbiAgaWYgKHNlY3JldGtleSA9PT0gdW5kZWZpbmVkKSB7XG4gICAgdG9rZW5EZWNyeXB0ID0gdG9rZW4/LnNwbGl0KCcgJylbMF07XG4gIH0gZWxzZSB7XG4gICAgdG9rZW5EZWNyeXB0ID0gc2VjcmV0a2V5O1xuICB9XG5cbiAgY29uc3QgYXJyOiBhbnkgPSBbXTtcblxuICBpZiAodG9rZW5EZWNyeXB0ICE9PSByZXEuc2VydmVyT3B0aW9ucy5zZWNyZXRLZXkpIHtcbiAgICByZXMuc3RhdHVzKDQwMCkuanNvbih7XG4gICAgICByZXNwb25zZTogZmFsc2UsXG4gICAgICBtZXNzYWdlOiAnVGhlIHRva2VuIGlzIGluY29ycmVjdCcsXG4gICAgfSk7XG4gIH1cblxuICBPYmplY3Qua2V5cyhjbGllbnRzQXJyYXkpLmZvckVhY2goKGl0ZW0pID0+IHtcbiAgICBhcnIucHVzaCh7IHNlc3Npb246IGl0ZW0gfSk7XG4gIH0pO1xuXG4gIHJlcy5zdGF0dXMoMjAwKS5qc29uKHsgcmVzcG9uc2U6IGF3YWl0IGdldEFsbFRva2VucyhyZXEpIH0pO1xufVxuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24gc3RhcnRTZXNzaW9uKHJlcTogUmVxdWVzdCwgcmVzOiBSZXNwb25zZSk6IFByb21pc2U8YW55PiB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiQXV0aFwiXVxuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5vcGVyYXRpb25JZCA9ICdzdGFydFNlc3Npb24nXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAgICNzd2FnZ2VyLnJlcXVlc3RCb2R5ID0ge1xuICAgICAgcmVxdWlyZWQ6IHRydWUsXG4gICAgICBcIkBjb250ZW50XCI6IHtcbiAgICAgICAgXCJhcHBsaWNhdGlvbi9qc29uXCI6IHtcbiAgICAgICAgICBzY2hlbWE6IHtcbiAgICAgICAgICAgIHR5cGU6IFwib2JqZWN0XCIsXG4gICAgICAgICAgICBwcm9wZXJ0aWVzOiB7XG4gICAgICAgICAgICAgIHdlYmhvb2s6IHsgdHlwZTogXCJzdHJpbmdcIiB9LFxuICAgICAgICAgICAgICB3YWl0UXJDb2RlOiB7IHR5cGU6IFwiYm9vbGVhblwiIH0sXG4gICAgICAgICAgICAgIHByb3h5OiB7XG4gICAgICAgICAgICAgICAgdHlwZTogXCJvYmplY3RcIixcbiAgICAgICAgICAgICAgICBwcm9wZXJ0aWVzOiB7XG4gICAgICAgICAgICAgICAgICB1cmw6IHsgdHlwZTogXCJzdHJpbmdcIiB9LFxuICAgICAgICAgICAgICAgICAgdXNlcm5hbWU6IHsgdHlwZTogXCJzdHJpbmdcIiB9LFxuICAgICAgICAgICAgICAgICAgcGFzc3dvcmQ6IHsgdHlwZTogXCJzdHJpbmdcIiB9LFxuICAgICAgICAgICAgICAgIH1cbiAgICAgICAgICAgICAgfVxuICAgICAgICAgICAgfVxuICAgICAgICAgIH0sXG4gICAgICAgICAgZXhhbXBsZToge1xuICAgICAgICAgICAgd2ViaG9vazogXCJcIixcbiAgICAgICAgICAgIHdhaXRRckNvZGU6IGZhbHNlLFxuICAgICAgICAgICAgcHJveHk6IHtcbiAgICAgICAgICAgICAgdXJsOiBcImh0dHA6Ly9teXByb3h5LmNvbTo4MDgwXCIsXG4gICAgICAgICAgICAgIHVzZXJuYW1lOiBcIm15dXNlclwiLFxuICAgICAgICAgICAgICBwYXNzd29yZDogXCJteXBhc3N3b3JkXCJcbiAgICAgICAgICAgIH1cbiAgICAgICAgICB9XG4gICAgICAgIH1cbiAgICAgIH1cbiAgICAgfVxuICAgKi9cbiAgY29uc3Qgc2Vzc2lvbiA9IHJlcS5zZXNzaW9uO1xuICBjb25zdCB7IHdhaXRRckNvZGUgPSBmYWxzZSB9ID0gcmVxLmJvZHk7XG5cbiAgYXdhaXQgZ2V0U2Vzc2lvblN0YXRlKHJlcSwgcmVzKTtcbiAgYXdhaXQgU2Vzc2lvblV0aWwub3BlbmRhdGEocmVxLCBzZXNzaW9uLCB3YWl0UXJDb2RlID8gcmVzIDogbnVsbCk7XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBjbG9zZVNlc3Npb24ocmVxOiBSZXF1ZXN0LCByZXM6IFJlc3BvbnNlKTogUHJvbWlzZTxhbnk+IHtcbiAgLyoqXG4gICAqICNzd2FnZ2VyLnRhZ3MgPSBbXCJBdXRoXCJdXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ2Nsb3NlU2Vzc2lvbidcbiAgICAgI3N3YWdnZXIuYXV0b0JvZHk9dHJ1ZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgKi9cbiAgY29uc3Qgc2Vzc2lvbiA9IHJlcS5zZXNzaW9uO1xuICB0cnkge1xuICAgIGNvbnN0IGNsaWVudCA9IChjbGllbnRzQXJyYXkgYXMgYW55KVtzZXNzaW9uXTtcbiAgICBpZiAoIWNsaWVudCkge1xuICAgICAgcmV0dXJuIGF3YWl0IHJlc1xuICAgICAgICAuc3RhdHVzKDIwMClcbiAgICAgICAgLmpzb24oeyBzdGF0dXM6IHRydWUsIG1lc3NhZ2U6ICdTZXNzaW9uIHN1Y2Nlc3NmdWxseSBjbG9zZWQnIH0pO1xuICAgIH1cblxuICAgIGlmIChjbGllbnQuc3RhdHVzICE9PSAnQ09OTkVDVEVEJyAmJiBjbGllbnQuc3RhdHVzICE9PSAnb3BlbicpIHtcbiAgICAgIHJlcS5sb2dnZXIuaW5mbyhgWyR7c2Vzc2lvbn1dIEZvcmNlIGtpbGxpbmcgc2Vzc2lvbiBiZWNhdXNlIHN0YXR1cyBpcyAke2NsaWVudC5zdGF0dXN9YCk7XG4gICAgICBjbGllbnQuc2hvdWxkQ2xvc2UgPSB0cnVlO1xuICAgICAgdHJ5IHtcbiAgICAgICAgU2Vzc2lvblV0aWwuZm9yY2VLaWxsU2Vzc2lvbihzZXNzaW9uKTtcbiAgICAgIH0gY2F0Y2ggKGUpIHt9XG4gICAgICAoY2xpZW50c0FycmF5IGFzIGFueSlbc2Vzc2lvbl0gPSB1bmRlZmluZWQ7XG4gICAgICByZXR1cm4gYXdhaXQgcmVzXG4gICAgICAgIC5zdGF0dXMoMjAwKVxuICAgICAgICAuanNvbih7IHN0YXR1czogdHJ1ZSwgbWVzc2FnZTogJ1Nlc3Npb24gZm9yY2UgY2xvc2VkJyB9KTtcbiAgICB9XG5cbiAgICAoY2xpZW50c0FycmF5IGFzIGFueSlbc2Vzc2lvbl0gPSB7IHN0YXR1czogbnVsbCB9O1xuXG4gICAgaWYgKHJlcS5jbGllbnQgJiYgdHlwZW9mIHJlcS5jbGllbnQuY2xvc2UgPT09ICdmdW5jdGlvbicpIHtcbiAgICAgIGF3YWl0IHJlcS5jbGllbnQuY2xvc2UoKTtcbiAgICB9XG4gICAgICByZXEuaW8uZW1pdCgnd2hhdHNhcHAtc3RhdHVzJywgZmFsc2UpO1xuICAgICAgY2FsbFdlYkhvb2socmVxLmNsaWVudCwgcmVxLCAnY2xvc2VzZXNzaW9uJywge1xuICAgICAgICBtZXNzYWdlOiBgU2Vzc2lvbjogJHtzZXNzaW9ufSBkaXNjb25uZWN0ZWRgLFxuICAgICAgICBjb25uZWN0ZWQ6IGZhbHNlLFxuICAgICAgfSk7XG5cbiAgICAgIHJldHVybiBhd2FpdCByZXNcbiAgICAgICAgLnN0YXR1cygyMDApXG4gICAgICAgIC5qc29uKHsgc3RhdHVzOiB0cnVlLCBtZXNzYWdlOiAnU2Vzc2lvbiBzdWNjZXNzZnVsbHkgY2xvc2VkJyB9KTtcbiAgfSBjYXRjaCAoZXJyb3IpIHtcbiAgICByZXEubG9nZ2VyLmVycm9yKGVycm9yKTtcbiAgICByZXR1cm4gYXdhaXQgcmVzXG4gICAgICAuc3RhdHVzKDUwMClcbiAgICAgIC5qc29uKHsgc3RhdHVzOiBmYWxzZSwgbWVzc2FnZTogJ0Vycm9yIGNsb3Npbmcgc2Vzc2lvbicsIGVycm9yIH0pO1xuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBsb2dPdXRTZXNzaW9uKHJlcTogUmVxdWVzdCwgcmVzOiBSZXNwb25zZSk6IFByb21pc2U8YW55PiB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiQXV0aFwiXVxuICAgICAjc3dhZ2dlci5vcGVyYXRpb25JZCA9ICdsb2dvdXRTZXNzaW9uJ1xuICAgKiAjc3dhZ2dlci5kZXNjcmlwdGlvbiA9ICdUaGlzIHJvdXRlIGxvZ291dCBhbmQgZGVsZXRlIHNlc3Npb24gZGF0YSdcbiAgICAgI3N3YWdnZXIuYXV0b0JvZHk9ZmFsc2VcbiAgICAgI3N3YWdnZXIuc2VjdXJpdHkgPSBbe1xuICAgICAgICAgICAgXCJiZWFyZXJBdXRoXCI6IFtdXG4gICAgIH1dXG4gICAgICNzd2FnZ2VyLnBhcmFtZXRlcnNbXCJzZXNzaW9uXCJdID0ge1xuICAgICAgc2NoZW1hOiAnTkVSRFdIQVRTX0FNRVJJQ0EnXG4gICAgIH1cbiAgICovXG4gIHRyeSB7XG4gICAgY29uc3Qgc2Vzc2lvbiA9IHJlcS5zZXNzaW9uO1xuICAgIGF3YWl0IHJlcS5jbGllbnQubG9nb3V0KCk7XG4gICAgZGVsZXRlU2Vzc2lvbk9uQXJyYXkocmVxLnNlc3Npb24pO1xuXG4gICAgc2V0VGltZW91dChhc3luYyAoKSA9PiB7XG4gICAgICBjb25zdCBwYXRoVXNlckRhdGEgPSBjb25maWcuY3VzdG9tVXNlckRhdGFEaXIgKyByZXEuc2Vzc2lvbjtcbiAgICAgIGNvbnN0IHBhdGhUb2tlbnMgPSBfX2Rpcm5hbWUgKyBgLi4vLi4vLi4vdG9rZW5zLyR7cmVxLnNlc3Npb259LmRhdGEuanNvbmA7XG5cbiAgICAgIGlmIChmcy5leGlzdHNTeW5jKHBhdGhVc2VyRGF0YSkpIHtcbiAgICAgICAgYXdhaXQgZnMucHJvbWlzZXMucm0ocGF0aFVzZXJEYXRhLCB7XG4gICAgICAgICAgcmVjdXJzaXZlOiB0cnVlLFxuICAgICAgICAgIG1heFJldHJpZXM6IDUsXG4gICAgICAgICAgZm9yY2U6IHRydWUsXG4gICAgICAgICAgcmV0cnlEZWxheTogMTAwMCxcbiAgICAgICAgfSk7XG4gICAgICB9XG4gICAgICBpZiAoZnMuZXhpc3RzU3luYyhwYXRoVG9rZW5zKSkge1xuICAgICAgICBhd2FpdCBmcy5wcm9taXNlcy5ybShwYXRoVG9rZW5zLCB7XG4gICAgICAgICAgcmVjdXJzaXZlOiB0cnVlLFxuICAgICAgICAgIG1heFJldHJpZXM6IDUsXG4gICAgICAgICAgZm9yY2U6IHRydWUsXG4gICAgICAgICAgcmV0cnlEZWxheTogMTAwMCxcbiAgICAgICAgfSk7XG4gICAgICB9XG5cbiAgICAgIHJlcS5pby5lbWl0KCd3aGF0c2FwcC1zdGF0dXMnLCBmYWxzZSk7XG4gICAgICBjYWxsV2ViSG9vayhyZXEuY2xpZW50LCByZXEsICdsb2dvdXRzZXNzaW9uJywge1xuICAgICAgICBtZXNzYWdlOiBgU2Vzc2lvbjogJHtzZXNzaW9ufSBsb2dnZWQgb3V0YCxcbiAgICAgICAgY29ubmVjdGVkOiBmYWxzZSxcbiAgICAgIH0pO1xuXG4gICAgICByZXR1cm4gYXdhaXQgcmVzXG4gICAgICAgIC5zdGF0dXMoMjAwKVxuICAgICAgICAuanNvbih7IHN0YXR1czogdHJ1ZSwgbWVzc2FnZTogJ1Nlc3Npb24gc3VjY2Vzc2Z1bGx5IGNsb3NlZCcgfSk7XG4gICAgfSwgNTAwKTtcbiAgICAvKnRyeSB7XG4gICAgICBhd2FpdCByZXEuY2xpZW50LmNsb3NlKCk7XG4gICAgfSBjYXRjaCAoZXJyb3IpIHt9Ki9cbiAgfSBjYXRjaCAoZXJyb3IpIHtcbiAgICByZXEubG9nZ2VyLmVycm9yKGVycm9yKTtcbiAgICByZXNcbiAgICAgIC5zdGF0dXMoNTAwKVxuICAgICAgLmpzb24oeyBzdGF0dXM6IGZhbHNlLCBtZXNzYWdlOiAnRXJyb3IgY2xvc2luZyBzZXNzaW9uJywgZXJyb3IgfSk7XG4gIH1cbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIGNoZWNrQ29ubmVjdGlvblNlc3Npb24oXG4gIHJlcTogUmVxdWVzdCxcbiAgcmVzOiBSZXNwb25zZVxuKTogUHJvbWlzZTxhbnk+IHtcbiAgLyoqXG4gICAqICNzd2FnZ2VyLnRhZ3MgPSBbXCJBdXRoXCJdXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ0NoZWNrQ29ubmVjdGlvblN0YXRlJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgKi9cbiAgdHJ5IHtcbiAgICBhd2FpdCByZXEuY2xpZW50LmlzQ29ubmVjdGVkKCk7XG5cbiAgICByZXMuc3RhdHVzKDIwMCkuanNvbih7IHN0YXR1czogdHJ1ZSwgbWVzc2FnZTogJ0Nvbm5lY3RlZCcgfSk7XG4gIH0gY2F0Y2ggKGVycm9yKSB7XG4gICAgcmVzLnN0YXR1cygyMDApLmpzb24oeyBzdGF0dXM6IGZhbHNlLCBtZXNzYWdlOiAnRGlzY29ubmVjdGVkJyB9KTtcbiAgfVxufVxuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24gZG93bmxvYWRNZWRpYUJ5TWVzc2FnZShyZXE6IFJlcXVlc3QsIHJlczogUmVzcG9uc2UpIHtcbiAgLyoqXG4gICAqICNzd2FnZ2VyLnRhZ3MgPSBbXCJNZXNzYWdlc1wiXVxuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5vcGVyYXRpb25JZCA9ICdkb3dubG9hZE1lZGlhYnlNZXNzYWdlJ1xuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgICAjc3dhZ2dlci5yZXF1ZXN0Qm9keSA9IHtcbiAgICAgIHJlcXVpcmVkOiB0cnVlLFxuICAgICAgXCJAY29udGVudFwiOiB7XG4gICAgICAgIFwiYXBwbGljYXRpb24vanNvblwiOiB7XG4gICAgICAgICAgc2NoZW1hOiB7XG4gICAgICAgICAgICB0eXBlOiBcIm9iamVjdFwiLFxuICAgICAgICAgICAgcHJvcGVydGllczoge1xuICAgICAgICAgICAgICBtZXNzYWdlSWQ6IHsgdHlwZTogXCJzdHJpbmdcIiB9LFxuICAgICAgICAgICAgfVxuICAgICAgICAgIH0sXG4gICAgICAgICAgZXhhbXBsZToge1xuICAgICAgICAgICAgbWVzc2FnZUlkOiAnPG1lc3NhZ2VJZD4nXG4gICAgICAgICAgfVxuICAgICAgICB9XG4gICAgICB9XG4gICAgIH1cbiAgICovXG4gIGNvbnN0IGNsaWVudCA9IHJlcS5jbGllbnQ7XG4gIGNvbnN0IHsgbWVzc2FnZUlkIH0gPSByZXEuYm9keTtcblxuICBpZiAoIWNsaWVudCB8fCB0eXBlb2YgY2xpZW50LmdldE1lc3NhZ2VCeUlkICE9PSAnZnVuY3Rpb24nKSB7XG4gICAgcmV0dXJuIHJlcy5zdGF0dXMoNDAwKS5qc29uKHtcbiAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgIG1lc3NhZ2U6ICdUaGUgV2hhdHNBcHAgc2Vzc2lvbiBpcyBub3QgYWN0aXZlLicsXG4gICAgfSk7XG4gIH1cblxuICBsZXQgbWVzc2FnZTtcblxuICB0cnkge1xuICAgIGlmICghbWVzc2FnZUlkLmlzTWVkaWEgfHwgIW1lc3NhZ2VJZC50eXBlKSB7XG4gICAgICBtZXNzYWdlID0gYXdhaXQgY2xpZW50LmdldE1lc3NhZ2VCeUlkKG1lc3NhZ2VJZCk7XG4gICAgfSBlbHNlIHtcbiAgICAgIG1lc3NhZ2UgPSBtZXNzYWdlSWQ7XG4gICAgfVxuXG4gICAgaWYgKCFtZXNzYWdlKVxuICAgICAgcmVzLnN0YXR1cyg0MDApLmpzb24oe1xuICAgICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICAgIG1lc3NhZ2U6ICdNZXNzYWdlIG5vdCBmb3VuZCcsXG4gICAgICB9KTtcblxuICAgIGlmICghKG1lc3NhZ2VbJ21pbWV0eXBlJ10gfHwgbWVzc2FnZS5pc01lZGlhIHx8IG1lc3NhZ2UuaXNNTVMpKVxuICAgICAgcmVzLnN0YXR1cyg0MDApLmpzb24oe1xuICAgICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICAgIG1lc3NhZ2U6ICdNZXNzYWdlIGRvZXMgbm90IGNvbnRhaW4gbWVkaWEnLFxuICAgICAgfSk7XG5cbiAgICBjb25zdCBidWZmZXIgPSBhd2FpdCBjbGllbnQuZGVjcnlwdEZpbGUobWVzc2FnZSk7XG5cbiAgICByZXNcbiAgICAgIC5zdGF0dXMoMjAwKVxuICAgICAgLmpzb24oeyBiYXNlNjQ6IGJ1ZmZlci50b1N0cmluZygnYmFzZTY0JyksIG1pbWV0eXBlOiBtZXNzYWdlLm1pbWV0eXBlIH0pO1xuICB9IGNhdGNoIChlKSB7XG4gICAgcmVxLmxvZ2dlci5lcnJvcihlKTtcbiAgICByZXMuc3RhdHVzKDQwMCkuanNvbih7XG4gICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICBtZXNzYWdlOiAnRGVjcnlwdCBmaWxlIGVycm9yJyxcbiAgICAgIGVycm9yOiBlLFxuICAgIH0pO1xuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBnZXRNZWRpYUJ5TWVzc2FnZShyZXE6IFJlcXVlc3QsIHJlczogUmVzcG9uc2UpIHtcbiAgLyoqXG4gICAqICNzd2FnZ2VyLnRhZ3MgPSBbXCJNZXNzYWdlc1wiXVxuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5vcGVyYXRpb25JZCA9ICdnZXRNZWRpYUJ5TWVzc2FnZSdcbiAgICAgI3N3YWdnZXIuc2VjdXJpdHkgPSBbe1xuICAgICAgICAgICAgXCJiZWFyZXJBdXRoXCI6IFtdXG4gICAgIH1dXG4gICAgICNzd2FnZ2VyLnBhcmFtZXRlcnNbXCJzZXNzaW9uXCJdID0ge1xuICAgICAgc2NoZW1hOiAnTkVSRFdIQVRTX0FNRVJJQ0EnXG4gICAgIH1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdtZXNzYWdlSWQnXG4gICAgIH1cbiAgICovXG4gIGNvbnN0IGNsaWVudCA9IHJlcS5jbGllbnQ7XG4gIGNvbnN0IHsgbWVzc2FnZUlkIH0gPSByZXEucGFyYW1zO1xuXG4gIGlmICghY2xpZW50IHx8IHR5cGVvZiBjbGllbnQuZ2V0TWVzc2FnZUJ5SWQgIT09ICdmdW5jdGlvbicpIHtcbiAgICByZXR1cm4gcmVzLnN0YXR1cyg0MDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgbWVzc2FnZTogJ1RoZSBXaGF0c0FwcCBzZXNzaW9uIGlzIG5vdCBhY3RpdmUuJyxcbiAgICB9KTtcbiAgfVxuXG4gIHRyeSB7XG4gICAgbGV0IG1lc3NhZ2U6IGFueSA9IG51bGw7XG5cbiAgICAvLyBJZiBkZXRhaWxzIGFyZSBwcm92aWRlZCBpbiB0aGUgcmVxdWVzdCBib2R5IChlLmcuIFBPU1QgcmVxdWVzdCB3aXRoIGxvY2FsIGNhY2hlKSwgdXNlIHRoZW0gZGlyZWN0bHkuXG4gICAgaWYgKHJlcS5ib2R5ICYmIChyZXEuYm9keS5tZWRpYUtleSB8fCByZXEuYm9keS5jbGllbnRVcmwpKSB7XG4gICAgICByZXEubG9nZ2VyLmluZm8oYFJlY2VpdmVkIGRlY3J5cHRpb24ga2V5cyBpbiBib2R5IGZvciBtZXNzYWdlICR7bWVzc2FnZUlkfS4gQnlwYXNzaW5nIFB1cHBldGVlciBsb29rdXAuYCk7XG4gICAgICBtZXNzYWdlID0gcmVxLmJvZHk7XG4gICAgICAvLyBOb3JtYWxpc2Uga2V5IHR5cGVzIGFuZCBzdHJ1Y3R1cmVzIGlmIG5lZWRlZCBieSBkZWNyeXB0RmlsZVxuICAgICAgaWYgKHR5cGVvZiBtZXNzYWdlLm1lZGlhS2V5ID09PSAnb2JqZWN0JyAmJiBtZXNzYWdlLm1lZGlhS2V5LmRhdGEpIHtcbiAgICAgICAgbWVzc2FnZS5tZWRpYUtleSA9IEJ1ZmZlci5mcm9tKG1lc3NhZ2UubWVkaWFLZXkuZGF0YSk7XG4gICAgICB9IGVsc2UgaWYgKHR5cGVvZiBtZXNzYWdlLm1lZGlhS2V5ID09PSAnc3RyaW5nJykge1xuICAgICAgICBtZXNzYWdlLm1lZGlhS2V5ID0gQnVmZmVyLmZyb20obWVzc2FnZS5tZWRpYUtleSwgJ2Jhc2U2NCcpO1xuICAgICAgfVxuICAgIH0gZWxzZSB7XG4gICAgICB0cnkge1xuICAgICAgICBtZXNzYWdlID0gYXdhaXQgY2xpZW50LmdldE1lc3NhZ2VCeUlkKG1lc3NhZ2VJZCk7XG4gICAgICB9IGNhdGNoIChlcnI6IGFueSkge1xuICAgICAgICByZXEubG9nZ2VyLndhcm4oYGNsaWVudC5nZXRNZXNzYWdlQnlJZCB0aHJldyBlcnJvcjogJHtlcnIubWVzc2FnZSB8fCBlcnJ9LiBUcnlpbmcgZmFsbGJhY2suLi5gKTtcbiAgICAgIH1cblxuICAgICAgLy8gRmFsbGJhY2s6IElmIG1lc3NhZ2UgaXMgbm90IGZvdW5kLCBpdCBtaWdodCBub3QgYmUgbG9hZGVkIGluIHRoZSBXaGF0c0FwcCBXZWIgY2FjaGUuXG4gICAgICAvLyBUcnkgdG8gcGFyc2UgdGhlIGNoYXRJZCBmcm9tIHRoZSBzZXJpYWxpemVkIG1lc3NhZ2VJZCAoZm9ybWF0OiBmcm9tTWVfY2hhdElkX21zZ0lkX3BhcnRpY2lwYW50KVxuICAgICAgLy8gYW5kIGxvYWQgZWFybGllciBtZXNzYWdlcyB0byBmb3JjZSBzeW5jIGl0LlxuICAgICAgaWYgKCFtZXNzYWdlICYmIG1lc3NhZ2VJZCkge1xuICAgICAgICBjb25zdCBwYXJ0cyA9IG1lc3NhZ2VJZC5zcGxpdCgnXycpO1xuICAgICAgICBpZiAocGFydHMubGVuZ3RoID49IDIpIHtcbiAgICAgICAgICBjb25zdCBjaGF0SWQgPSBwYXJ0c1sxXTsgLy8gZS5nLiAxMjAzNjM0MjA5NDgxMzQwNjVAZy51cyBvciBwaG9uZUBjLnVzXG4gICAgICAgICAgaWYgKGNoYXRJZCAmJiB0eXBlb2YgY2xpZW50LmxvYWRFYXJsaWVyTWVzc2FnZXMgPT09ICdmdW5jdGlvbicpIHtcbiAgICAgICAgICAgIHJlcS5sb2dnZXIuaW5mbyhgTWVzc2FnZSAke21lc3NhZ2VJZH0gbm90IGZvdW5kIGluIGNhY2hlLiBBdHRlbXB0aW5nIGxvYWRFYXJsaWVyTWVzc2FnZXMgZm9yICR7Y2hhdElkfWApO1xuICAgICAgICAgICAgdHJ5IHtcbiAgICAgICAgICAgICAgLy8gTG9hZCBlYXJsaWVyIG1lc3NhZ2VzIChmZXRjaGVzIGEgYmF0Y2ggZnJvbSBXaGF0c0FwcCBzZXJ2ZXIgdG8gV2ViIGNsaWVudCBtZW1vcnkpXG4gICAgICAgICAgICAgIGF3YWl0IGNsaWVudC5sb2FkRWFybGllck1lc3NhZ2VzKGNoYXRJZCk7XG4gICAgICAgICAgICAgIC8vIFF1ZXJ5IGFnYWluXG4gICAgICAgICAgICAgIHRyeSB7XG4gICAgICAgICAgICAgICAgbWVzc2FnZSA9IGF3YWl0IGNsaWVudC5nZXRNZXNzYWdlQnlJZChtZXNzYWdlSWQpO1xuICAgICAgICAgICAgICB9IGNhdGNoIChyZXRyeUVycjogYW55KSB7XG4gICAgICAgICAgICAgICAgcmVxLmxvZ2dlci5lcnJvcihgUmV0cnkgZ2V0TWVzc2FnZUJ5SWQgZmFpbGVkOiAke3JldHJ5RXJyLm1lc3NhZ2UgfHwgcmV0cnlFcnJ9YCk7XG4gICAgICAgICAgICAgIH1cbiAgICAgICAgICAgIH0gY2F0Y2ggKGxvYWRFcnIpIHtcbiAgICAgICAgICAgICAgcmVxLmxvZ2dlci5lcnJvcihgRXJyb3IgZXhlY3V0aW5nIGxvYWRFYXJsaWVyTWVzc2FnZXM6ICR7bG9hZEVycn1gKTtcbiAgICAgICAgICAgIH1cbiAgICAgICAgICB9XG4gICAgICAgIH1cbiAgICAgIH1cbiAgICB9XG5cbiAgICBpZiAoIW1lc3NhZ2UpIHtcbiAgICAgIHJldHVybiByZXMuc3RhdHVzKDQwMCkuanNvbih7XG4gICAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgICAgbWVzc2FnZTogYE1lc3NhZ2UgJHttZXNzYWdlSWR9IG5vdCBmb3VuZGAsXG4gICAgICB9KTtcbiAgICB9XG5cbiAgICAvLyBFbnN1cmUgaXQgY29udGFpbnMgbWVkaWEgcHJvcGVydGllcyBvciBoYXMgbWltZXR5cGVcbiAgICBjb25zdCBtZWRpYVVybCA9IG1lc3NhZ2UuY2xpZW50VXJsIHx8IG1lc3NhZ2UuZGVwcmVjYXRlZE1tczNVcmw7XG4gICAgaWYgKCFtZWRpYVVybCkge1xuICAgICAgaWYgKHR5cGVvZiAoY2xpZW50IGFzIGFueSkuZG93bmxvYWRNZWRpYSA9PT0gJ2Z1bmN0aW9uJykge1xuICAgICAgICByZXEubG9nZ2VyLmluZm8oYE1lc3NhZ2UgJHttZXNzYWdlSWR9IGRvZXMgbm90IGhhdmUgY2xpZW50VXJsLiBUcnlpbmcgY2xpZW50LmRvd25sb2FkTWVkaWEuLi5gKTtcbiAgICAgICAgdHJ5IHtcbiAgICAgICAgICBsZXQgdGltZXI6IGFueTtcbiAgICAgICAgICBjb25zdCBkb3dubG9hZFByb21pc2UgPSAoY2xpZW50IGFzIGFueSkuZG93bmxvYWRNZWRpYShtZXNzYWdlSWQpLmZpbmFsbHkoKCkgPT4ge1xuICAgICAgICAgICAgaWYgKHRpbWVyKSBjbGVhclRpbWVvdXQodGltZXIpO1xuICAgICAgICAgIH0pO1xuICAgICAgICAgIGNvbnN0IHRpbWVvdXRQcm9taXNlID0gbmV3IFByb21pc2U8c3RyaW5nPigoXywgcmVqZWN0KSA9PiB7XG4gICAgICAgICAgICB0aW1lciA9IHNldFRpbWVvdXQoKCkgPT4gcmVqZWN0KG5ldyBFcnJvcignVGltZW91dCBkb3dubG9hZGluZyBtZWRpYSB2aWEgUHVwcGV0ZWVyJykpLCAzMDAwMCk7XG4gICAgICAgICAgfSk7XG4gICAgICAgICAgbGV0IGJhc2U2NDogc3RyaW5nID0gYXdhaXQgUHJvbWlzZS5yYWNlKFtkb3dubG9hZFByb21pc2UsIHRpbWVvdXRQcm9taXNlXSk7XG4gICAgICAgICAgaWYgKGJhc2U2NCkge1xuICAgICAgICAgICAgbGV0IG1pbWV0eXBlID0gbWVzc2FnZS5taW1ldHlwZSB8fCAnYXVkaW8vb2dnJztcbiAgICAgICAgICAgIGlmIChiYXNlNjQuc3RhcnRzV2l0aCgnZGF0YTonKSkge1xuICAgICAgICAgICAgICBjb25zdCBtYXRjaGVzID0gYmFzZTY0Lm1hdGNoKC9eZGF0YTooLio/KTtiYXNlNjQsKC4qKSQvKTtcbiAgICAgICAgICAgICAgaWYgKG1hdGNoZXMpIHtcbiAgICAgICAgICAgICAgICBtaW1ldHlwZSA9IG1hdGNoZXNbMV07XG4gICAgICAgICAgICAgICAgYmFzZTY0ID0gbWF0Y2hlc1syXTtcbiAgICAgICAgICAgICAgfVxuICAgICAgICAgICAgfVxuICAgICAgICAgICAgcmV0dXJuIHJlcy5zdGF0dXMoMjAwKS5qc29uKHsgYmFzZTY0LCBtaW1ldHlwZSB9KTtcbiAgICAgICAgICB9XG4gICAgICAgIH0gY2F0Y2ggKGRvd25sb2FkRXJyKSB7XG4gICAgICAgICAgcmVxLmxvZ2dlci5lcnJvcihgRXJyb3IgaW4gY2xpZW50LmRvd25sb2FkTWVkaWEgZmFsbGJhY2s6ICR7ZG93bmxvYWRFcnJ9YCk7XG4gICAgICAgIH1cbiAgICAgIH1cbiAgICAgIHJldHVybiByZXMuc3RhdHVzKDQwMCkuanNvbih7XG4gICAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgICAgbWVzc2FnZTogJ01lc3NhZ2UgZG9lcyBub3QgY29udGFpbiBtZWRpYSBkb3dubG9hZCBVUkwnLFxuICAgICAgfSk7XG4gICAgfVxuXG4gICAgdHJ5IHtcbiAgICAgIGNvbnN0IGJ1ZmZlciA9IGF3YWl0IGNsaWVudC5kZWNyeXB0RmlsZShtZXNzYWdlKTtcbiAgICAgIHJlc1xuICAgICAgICAuc3RhdHVzKDIwMClcbiAgICAgICAgLmpzb24oeyBiYXNlNjQ6IGJ1ZmZlci50b1N0cmluZygnYmFzZTY0JyksIG1pbWV0eXBlOiBtZXNzYWdlLm1pbWV0eXBlIHx8ICdhdWRpby9vZ2cnIH0pO1xuICAgIH0gY2F0Y2ggKGRlY3J5cHRFcnIpIHtcbiAgICAgIHJlcS5sb2dnZXIuZXJyb3IoYGRlY3J5cHRGaWxlIGZhaWxlZCwgdHJ5aW5nIGJyb3dzZXItc2lkZSByZWNvdmVyeTogJHtkZWNyeXB0RXJyfWApO1xuICAgICAgXG4gICAgICAvLyBBdHRlbXB0IGJyb3dzZXItc2lkZSByZWNvdmVyeTogZmV0Y2ggdGhlIG1lc3NhZ2UgZnJlc2ggZnJvbSBXaGF0c0FwcCBXZWIgdG8gZ2V0IHVwZGF0ZWQgQ0ROIFVSTHNcbiAgICAgIGxldCBmcmVzaE1lc3NhZ2U6IGFueSA9IG51bGw7XG4gICAgICB0cnkge1xuICAgICAgICBmcmVzaE1lc3NhZ2UgPSBhd2FpdCBjbGllbnQuZ2V0TWVzc2FnZUJ5SWQobWVzc2FnZUlkKTtcbiAgICAgIH0gY2F0Y2ggKGVycikge31cblxuICAgICAgaWYgKCFmcmVzaE1lc3NhZ2UgJiYgbWVzc2FnZUlkKSB7XG4gICAgICAgIGNvbnN0IHBhcnRzID0gbWVzc2FnZUlkLnNwbGl0KCdfJyk7XG4gICAgICAgIGlmIChwYXJ0cy5sZW5ndGggPj0gMikge1xuICAgICAgICAgIGNvbnN0IGNoYXRJZCA9IHBhcnRzWzFdO1xuICAgICAgICAgIGlmIChjaGF0SWQgJiYgdHlwZW9mIGNsaWVudC5sb2FkRWFybGllck1lc3NhZ2VzID09PSAnZnVuY3Rpb24nKSB7XG4gICAgICAgICAgICB0cnkge1xuICAgICAgICAgICAgICBhd2FpdCBjbGllbnQubG9hZEVhcmxpZXJNZXNzYWdlcyhjaGF0SWQpO1xuICAgICAgICAgICAgICBmcmVzaE1lc3NhZ2UgPSBhd2FpdCBjbGllbnQuZ2V0TWVzc2FnZUJ5SWQobWVzc2FnZUlkKTtcbiAgICAgICAgICAgIH0gY2F0Y2ggKGVycikge31cbiAgICAgICAgICB9XG4gICAgICAgIH1cbiAgICAgIH1cblxuICAgICAgaWYgKGZyZXNoTWVzc2FnZSkge1xuICAgICAgICB0cnkge1xuICAgICAgICAgIHJlcS5sb2dnZXIuaW5mbyhgRm91bmQgZnJlc2ggbWVzc2FnZSBpbiBicm93c2VyIGZvciAke21lc3NhZ2VJZH0sIGF0dGVtcHRpbmcgZGVjcnlwdGlvbi4uLmApO1xuICAgICAgICAgIGNvbnN0IGJ1ZmZlciA9IGF3YWl0IGNsaWVudC5kZWNyeXB0RmlsZShmcmVzaE1lc3NhZ2UpO1xuICAgICAgICAgIHJldHVybiByZXMuc3RhdHVzKDIwMCkuanNvbih7XG4gICAgICAgICAgICBiYXNlNjQ6IGJ1ZmZlci50b1N0cmluZygnYmFzZTY0JyksXG4gICAgICAgICAgICBtaW1ldHlwZTogZnJlc2hNZXNzYWdlLm1pbWV0eXBlIHx8ICdhdWRpby9vZ2cnXG4gICAgICAgICAgfSk7XG4gICAgICAgIH0gY2F0Y2ggKGZyZXNoRGVjcnlwdEVycikge1xuICAgICAgICAgIHJlcS5sb2dnZXIuZXJyb3IoYERlY3J5cHRpb24gb2YgZnJlc2ggYnJvd3NlciBtZXNzYWdlIGZhaWxlZDogJHtmcmVzaERlY3J5cHRFcnJ9YCk7XG4gICAgICAgIH1cbiAgICAgIH1cblxuICAgICAgLy8gRmluYWwgZmFsbGJhY2sgdG8gV1BQQ29ubmVjdCdzIGRvd25sb2FkTWVkaWFcbiAgICAgIGlmICh0eXBlb2YgKGNsaWVudCBhcyBhbnkpLmRvd25sb2FkTWVkaWEgPT09ICdmdW5jdGlvbicpIHtcbiAgICAgICAgdHJ5IHtcbiAgICAgICAgICBsZXQgdGltZXI6IGFueTtcbiAgICAgICAgICBjb25zdCBkb3dubG9hZFByb21pc2UgPSAoY2xpZW50IGFzIGFueSkuZG93bmxvYWRNZWRpYShtZXNzYWdlSWQpLmZpbmFsbHkoKCkgPT4ge1xuICAgICAgICAgICAgaWYgKHRpbWVyKSBjbGVhclRpbWVvdXQodGltZXIpO1xuICAgICAgICAgIH0pO1xuICAgICAgICAgIGNvbnN0IHRpbWVvdXRQcm9taXNlID0gbmV3IFByb21pc2U8c3RyaW5nPigoXywgcmVqZWN0KSA9PiB7XG4gICAgICAgICAgICB0aW1lciA9IHNldFRpbWVvdXQoKCkgPT4gcmVqZWN0KG5ldyBFcnJvcignVGltZW91dCBkb3dubG9hZGluZyBtZWRpYSB2aWEgUHVwcGV0ZWVyJykpLCAzMDAwMCk7XG4gICAgICAgICAgfSk7XG4gICAgICAgICAgbGV0IGJhc2U2NDogc3RyaW5nID0gYXdhaXQgUHJvbWlzZS5yYWNlKFtkb3dubG9hZFByb21pc2UsIHRpbWVvdXRQcm9taXNlXSk7XG4gICAgICAgICAgaWYgKGJhc2U2NCkge1xuICAgICAgICAgICAgbGV0IG1pbWV0eXBlID0gKGZyZXNoTWVzc2FnZSB8fCBtZXNzYWdlKS5taW1ldHlwZSB8fCAnYXVkaW8vb2dnJztcbiAgICAgICAgICAgIGlmIChiYXNlNjQuc3RhcnRzV2l0aCgnZGF0YTonKSkge1xuICAgICAgICAgICAgICBjb25zdCBtYXRjaGVzID0gYmFzZTY0Lm1hdGNoKC9eZGF0YTooLio/KTtiYXNlNjQsKC4qKSQvKTtcbiAgICAgICAgICAgICAgaWYgKG1hdGNoZXMpIHtcbiAgICAgICAgICAgICAgICBtaW1ldHlwZSA9IG1hdGNoZXNbMV07XG4gICAgICAgICAgICAgICAgYmFzZTY0ID0gbWF0Y2hlc1syXTtcbiAgICAgICAgICAgICAgfVxuICAgICAgICAgICAgfVxuICAgICAgICAgICAgcmV0dXJuIHJlcy5zdGF0dXMoMjAwKS5qc29uKHsgYmFzZTY0LCBtaW1ldHlwZSB9KTtcbiAgICAgICAgICB9XG4gICAgICAgIH0gY2F0Y2ggKGRvd25sb2FkRXJyKSB7XG4gICAgICAgICAgcmVxLmxvZ2dlci5lcnJvcihgRXJyb3IgaW4gY2xpZW50LmRvd25sb2FkTWVkaWEgZmFsbGJhY2sgYWZ0ZXIgZGVjcnlwdGlvbiBlcnJvcjogJHtkb3dubG9hZEVycn1gKTtcbiAgICAgICAgfVxuICAgICAgfVxuICAgICAgdGhyb3cgZGVjcnlwdEVycjsgLy8gcmV0aHJvdyB0byB0cmlnZ2VyIHRoZSA1MDAgYmxvY2sgaWYgYm90aCBmYWlsZWRcbiAgICB9XG4gIH0gY2F0Y2ggKGV4KSB7XG4gICAgcmVxLmxvZ2dlci5lcnJvcihleCk7XG4gICAgcmVzLnN0YXR1cyg1MDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgbWVzc2FnZTogJ0ZhaWxlZCB0byBkZWNyeXB0IGZpbGUnLFxuICAgICAgZXJyb3I6IGV4IGluc3RhbmNlb2YgRXJyb3IgPyBleC5tZXNzYWdlIDogZXgsXG4gICAgfSk7XG4gIH1cbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIGdldFNlc3Npb25TdGF0ZShyZXE6IFJlcXVlc3QsIHJlczogUmVzcG9uc2UpIHtcbiAgLyoqXG4gICAgICNzd2FnZ2VyLnRhZ3MgPSBbXCJBdXRoXCJdXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ2dldFNlc3Npb25TdGF0ZSdcbiAgICAgI3N3YWdnZXIuc3VtbWFyeSA9ICdSZXRyaWV2ZSBzdGF0dXMgb2YgYSBzZXNzaW9uJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keSA9IGZhbHNlXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAqL1xuICB0cnkge1xuICAgIGNvbnN0IHsgd2FpdFFyQ29kZSA9IGZhbHNlIH0gPSByZXEuYm9keTtcbiAgICBjb25zdCBjbGllbnQgPSByZXEuY2xpZW50O1xuICAgIGNvbnN0IHFyID1cbiAgICAgIGNsaWVudD8udXJsY29kZSAhPSBudWxsICYmIGNsaWVudD8udXJsY29kZSAhPSAnJ1xuICAgICAgICA/IGF3YWl0IFFSQ29kZS50b0RhdGFVUkwoY2xpZW50LnVybGNvZGUpXG4gICAgICAgIDogbnVsbDtcblxuICAgIGlmICgoY2xpZW50ID09IG51bGwgfHwgY2xpZW50LnN0YXR1cyA9PSBudWxsKSAmJiAhd2FpdFFyQ29kZSlcbiAgICAgIHJlcy5zdGF0dXMoMjAwKS5qc29uKHsgc3RhdHVzOiAnQ0xPU0VEJywgcXJjb2RlOiBudWxsIH0pO1xuICAgIGVsc2UgaWYgKGNsaWVudCAhPSBudWxsKVxuICAgICAgcmVzLnN0YXR1cygyMDApLmpzb24oe1xuICAgICAgICBzdGF0dXM6IGNsaWVudC5zdGF0dXMsXG4gICAgICAgIHFyY29kZTogcXIsXG4gICAgICAgIHVybGNvZGU6IGNsaWVudC51cmxjb2RlLFxuICAgICAgICB2ZXJzaW9uOiB2ZXJzaW9uLFxuICAgICAgfSk7XG4gIH0gY2F0Y2ggKGV4KSB7XG4gICAgcmVxLmxvZ2dlci5lcnJvcihleCk7XG4gICAgcmVzLnN0YXR1cyg1MDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgbWVzc2FnZTogJ1RoZSBzZXNzaW9uIGlzIG5vdCBhY3RpdmUnLFxuICAgICAgZXJyb3I6IGV4LFxuICAgIH0pO1xuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBnZXRRckNvZGUocmVxOiBSZXF1ZXN0LCByZXM6IFJlc3BvbnNlKSB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiQXV0aFwiXVxuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5vcGVyYXRpb25JZCA9ICdnZXRRckNvZGUnXG4gICAgICNzd2FnZ2VyLnNlY3VyaXR5ID0gW3tcbiAgICAgICAgICAgIFwiYmVhcmVyQXV0aFwiOiBbXVxuICAgICB9XVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wic2Vzc2lvblwiXSA9IHtcbiAgICAgIHNjaGVtYTogJ05FUkRXSEFUU19BTUVSSUNBJ1xuICAgICB9XG4gICAqL1xuICB0cnkge1xuICAgIGlmIChyZXE/LmNsaWVudD8udXJsY29kZSkge1xuICAgICAgLy8gV2UgYWRkIG9wdGlvbnMgdG8gZ2VuZXJhdGUgdGhlIFFSIGNvZGUgaW4gaGlnaGVyIHJlc29sdXRpb25cbiAgICAgIC8vIFRoZSAvcXJjb2RlLXNlc3Npb24gcmVxdWVzdCB3aWxsIG5vdyByZXR1cm4gYSByZWFkYWJsZSBxcmNvZGUuXG4gICAgICBjb25zdCBxck9wdGlvbnMgPSB7XG4gICAgICAgIGVycm9yQ29ycmVjdGlvbkxldmVsOiAnTScgYXMgY29uc3QsXG4gICAgICAgIHR5cGU6ICdpbWFnZS9wbmcnIGFzIGNvbnN0LFxuICAgICAgICBzY2FsZTogNSxcbiAgICAgICAgd2lkdGg6IDUwMCxcbiAgICAgIH07XG4gICAgICBjb25zdCBxciA9IHJlcS5jbGllbnQudXJsY29kZVxuICAgICAgICA/IGF3YWl0IFFSQ29kZS50b0RhdGFVUkwocmVxLmNsaWVudC51cmxjb2RlLCBxck9wdGlvbnMpXG4gICAgICAgIDogbnVsbDtcbiAgICAgIGNvbnN0IGltZyA9IEJ1ZmZlci5mcm9tKFxuICAgICAgICAocXIgYXMgYW55KS5yZXBsYWNlKC9eZGF0YTppbWFnZVxcLyhwbmd8anBlZ3xqcGcpO2Jhc2U2NCwvLCAnJyksXG4gICAgICAgICdiYXNlNjQnXG4gICAgICApO1xuICAgICAgcmVzLndyaXRlSGVhZCgyMDAsIHtcbiAgICAgICAgJ0NvbnRlbnQtVHlwZSc6ICdpbWFnZS9wbmcnLFxuICAgICAgICAnQ29udGVudC1MZW5ndGgnOiBpbWcubGVuZ3RoLFxuICAgICAgfSk7XG4gICAgICByZXMuZW5kKGltZyk7XG4gICAgfSBlbHNlIGlmICh0eXBlb2YgcmVxLmNsaWVudCA9PT0gJ3VuZGVmaW5lZCcpIHtcbiAgICAgIHJlcy5zdGF0dXMoMjAwKS5qc29uKHtcbiAgICAgICAgc3RhdHVzOiBudWxsLFxuICAgICAgICBtZXNzYWdlOlxuICAgICAgICAgICdTZXNzaW9uIG5vdCBzdGFydGVkLiBQbGVhc2UsIHVzZSB0aGUgL3N0YXJ0LXNlc3Npb24gcm91dGUsIGZvciBpbml0aWFsaXphdGlvbiB5b3VyIHNlc3Npb24nLFxuICAgICAgfSk7XG4gICAgfSBlbHNlIHtcbiAgICAgIHJlcy5zdGF0dXMoMjAwKS5qc29uKHtcbiAgICAgICAgc3RhdHVzOiByZXEuY2xpZW50LnN0YXR1cyxcbiAgICAgICAgbWVzc2FnZTogJ1FSQ29kZSBpcyBub3QgYXZhaWxhYmxlLi4uJyxcbiAgICAgIH0pO1xuICAgIH1cbiAgfSBjYXRjaCAoZXgpIHtcbiAgICByZXEubG9nZ2VyLmVycm9yKGV4KTtcbiAgICByZXNcbiAgICAgIC5zdGF0dXMoNTAwKVxuICAgICAgLmpzb24oeyBzdGF0dXM6ICdlcnJvcicsIG1lc3NhZ2U6ICdFcnJvciByZXRyaWV2aW5nIFFSQ29kZScsIGVycm9yOiBleCB9KTtcbiAgfVxufVxuXG5leHBvcnQgYXN5bmMgZnVuY3Rpb24ga2lsbFNlcnZpY2VXb3JrZXIocmVxOiBSZXF1ZXN0LCByZXM6IFJlc3BvbnNlKSB7XG4gIC8qKlxuICAgKiAjc3dhZ2dlci5pZ25vcmU9dHJ1ZVxuICAgKiAjc3dhZ2dlci50YWdzID0gW1wiTWVzc2FnZXNcIl1cbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAna2lsbFNlcnZpY2VXb3JraWVyJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgKi9cbiAgdHJ5IHtcbiAgICByZXMuc3RhdHVzKDIwMCkuanNvbih7IHN0YXR1czogJ2Vycm9yJywgcmVzcG9uc2U6ICdOb3QgaW1wbGVtZW50ZWQgeWV0JyB9KTtcbiAgfSBjYXRjaCAoZXgpIHtcbiAgICByZXEubG9nZ2VyLmVycm9yKGV4KTtcbiAgICByZXMuc3RhdHVzKDUwMCkuanNvbih7XG4gICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICBtZXNzYWdlOiAnVGhlIHNlc3Npb24gaXMgbm90IGFjdGl2ZScsXG4gICAgICBlcnJvcjogZXgsXG4gICAgfSk7XG4gIH1cbn1cblxuZXhwb3J0IGFzeW5jIGZ1bmN0aW9uIHJlc3RhcnRTZXJ2aWNlKHJlcTogUmVxdWVzdCwgcmVzOiBSZXNwb25zZSkge1xuICAvKipcbiAgICogI3N3YWdnZXIuaWdub3JlPXRydWVcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIk1lc3NhZ2VzXCJdXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ3Jlc3RhcnRTZXJ2aWNlJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgKi9cbiAgdHJ5IHtcbiAgICByZXMuc3RhdHVzKDIwMCkuanNvbih7IHN0YXR1czogJ2Vycm9yJywgcmVzcG9uc2U6ICdOb3QgaW1wbGVtZW50ZWQgeWV0JyB9KTtcbiAgfSBjYXRjaCAoZXgpIHtcbiAgICByZXEubG9nZ2VyLmVycm9yKGV4KTtcbiAgICByZXMuc3RhdHVzKDUwMCkuanNvbih7XG4gICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICByZXNwb25zZTogeyBtZXNzYWdlOiAnVGhlIHNlc3Npb24gaXMgbm90IGFjdGl2ZScsIGVycm9yOiBleCB9LFxuICAgIH0pO1xuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBzdWJzY3JpYmVQcmVzZW5jZShyZXE6IFJlcXVlc3QsIHJlczogUmVzcG9uc2UpIHtcbiAgLyoqXG4gICAqICNzd2FnZ2VyLnRhZ3MgPSBbXCJNaXNjXCJdXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ3N1YnNjcmliZVByZXNlbmNlJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgICAjc3dhZ2dlci5yZXF1ZXN0Qm9keSA9IHtcbiAgICAgIHJlcXVpcmVkOiB0cnVlLFxuICAgICAgXCJAY29udGVudFwiOiB7XG4gICAgICAgIFwiYXBwbGljYXRpb24vanNvblwiOiB7XG4gICAgICAgICAgc2NoZW1hOiB7XG4gICAgICAgICAgICB0eXBlOiBcIm9iamVjdFwiLFxuICAgICAgICAgICAgcHJvcGVydGllczoge1xuICAgICAgICAgICAgICBwaG9uZTogeyB0eXBlOiBcInN0cmluZ1wiIH0sXG4gICAgICAgICAgICAgIGlzR3JvdXA6IHsgdHlwZTogXCJib29sZWFuXCIgfSxcbiAgICAgICAgICAgICAgYWxsOiB7IHR5cGU6IFwiYm9vbGVhblwiIH0sXG4gICAgICAgICAgICB9XG4gICAgICAgICAgfSxcbiAgICAgICAgICBleGFtcGxlOiB7XG4gICAgICAgICAgICBwaG9uZTogJzU1MjE5OTk5OTk5OTknLFxuICAgICAgICAgICAgaXNHcm91cDogZmFsc2UsXG4gICAgICAgICAgICBhbGw6IGZhbHNlLFxuICAgICAgICAgIH1cbiAgICAgICAgfVxuICAgICAgfVxuICAgICB9XG4gICAqL1xuICB0cnkge1xuICAgIGNvbnN0IHsgcGhvbmUsIGlzR3JvdXAgPSBmYWxzZSwgYWxsID0gZmFsc2UsIGlzTGlkID0gZmFsc2UgfSA9IHJlcS5ib2R5O1xuXG4gICAgY29uc3Qgc3Vic2NyaWJlT25lID0gYXN5bmMgKGNvbnRhdG86IHN0cmluZykgPT4ge1xuICAgICAgLy8gUHJlZmVyIHRoZSBtb2Rlcm4gV1BQLmNvbnRhY3Quc3Vic2NyaWJlUHJlc2VuY2Ugd2hpY2ggd29ya3Mgd2l0aFxuICAgICAgLy8gY3VycmVudCBXaGF0c0FwcCBXZWIuIFRoZSBsZWdhY3kgcmVxLmNsaWVudC5zdWJzY3JpYmVQcmVzZW5jZSB1c2VzXG4gICAgICAvLyB0aGUgaW50ZXJuYWwgV0FQSSB0aGF0IGNhbGxzIFN0b3JlLlByZXNlbmNlLmZpbmQoKSDigJQgYnJva2VuIGluIG5ld2VyXG4gICAgICAvLyBXQSB2ZXJzaW9ucyBhbmQgcmV0dXJucyA1MDAuIFdlIGZhbGwgYmFjayB0byB0aGUgbGVnYWN5IHBhdGggaWYgdGhlXG4gICAgICAvLyBXUFAgQVBJIGlzIG5vdCBhdmFpbGFibGUuXG4gICAgICBjb25zdCBwYWdlID0gKHJlcS5jbGllbnQgYXMgYW55KS5wYWdlO1xuICAgICAgaWYgKHBhZ2UpIHtcbiAgICAgICAgdHJ5IHtcbiAgICAgICAgICBhd2FpdCBwYWdlLmV2YWx1YXRlKChpZDogc3RyaW5nKSA9PiB7XG4gICAgICAgICAgICBjb25zdCB3cHAgPSAod2luZG93IGFzIGFueSkuV1BQO1xuICAgICAgICAgICAgaWYgKHdwcCAmJiB3cHAuY29udGFjdCAmJiB0eXBlb2Ygd3BwLmNvbnRhY3Quc3Vic2NyaWJlUHJlc2VuY2UgPT09ICdmdW5jdGlvbicpIHtcbiAgICAgICAgICAgICAgcmV0dXJuIHdwcC5jb250YWN0LnN1YnNjcmliZVByZXNlbmNlKGlkKTtcbiAgICAgICAgICAgIH1cbiAgICAgICAgICAgIC8vIEZhbGxiYWNrIHRvIFdQUC53aGF0c2FwcC5QcmVzZW5jZVV0aWxzIGlmIGF2YWlsYWJsZVxuICAgICAgICAgICAgaWYgKHdwcCAmJiB3cHAud2hhdHNhcHAgJiYgd3BwLndoYXRzYXBwLlByZXNlbmNlVXRpbHMpIHtcbiAgICAgICAgICAgICAgcmV0dXJuIHdwcC53aGF0c2FwcC5QcmVzZW5jZVV0aWxzLnN1YnNjcmliZVRvUHJlc2VuY2UoaWQpO1xuICAgICAgICAgICAgfVxuICAgICAgICAgICAgdGhyb3cgbmV3IEVycm9yKCdXUFAuY29udGFjdC5zdWJzY3JpYmVQcmVzZW5jZSBub3QgYXZhaWxhYmxlJyk7XG4gICAgICAgICAgfSwgY29udGF0byk7XG4gICAgICAgICAgcmVxLmxvZ2dlci5pbmZvKGBbc3Vic2NyaWJlUHJlc2VuY2VdIFdQUCBzdWJzY3JpYmVkOiAke2NvbnRhdG99YCk7XG4gICAgICAgICAgcmV0dXJuO1xuICAgICAgICB9IGNhdGNoICh3cHBFcnIpIHtcbiAgICAgICAgICByZXEubG9nZ2VyLndhcm4oYFtzdWJzY3JpYmVQcmVzZW5jZV0gV1BQIGZhbGxiYWNrIGZvciAke2NvbnRhdG99OiAke3dwcEVycn1gKTtcbiAgICAgICAgfVxuICAgICAgfVxuICAgICAgLy8gTGVnYWN5IGZhbGxiYWNrXG4gICAgICBhd2FpdCByZXEuY2xpZW50LnN1YnNjcmliZVByZXNlbmNlKGNvbnRhdG8pO1xuICAgIH07XG5cbiAgICBpZiAoYWxsKSB7XG4gICAgICBsZXQgY29udGFjdHM7XG4gICAgICBpZiAoaXNHcm91cCkge1xuICAgICAgICBjb25zdCBncm91cHMgPSBhd2FpdCByZXEuY2xpZW50LmdldEFsbEdyb3VwcyhmYWxzZSk7XG4gICAgICAgIGNvbnRhY3RzID0gZ3JvdXBzLm1hcCgocDogYW55KSA9PiBwLmlkLl9zZXJpYWxpemVkKTtcbiAgICAgIH0gZWxzZSB7XG4gICAgICAgIGNvbnN0IGNoYXRzID0gYXdhaXQgcmVxLmNsaWVudC5nZXRBbGxDb250YWN0cygpO1xuICAgICAgICBjb250YWN0cyA9IGNoYXRzLm1hcCgoYzogYW55KSA9PiBjLmlkLl9zZXJpYWxpemVkKTtcbiAgICAgIH1cbiAgICAgIGZvciAoY29uc3QgY29udGF0byBvZiBjb250YWN0cykge1xuICAgICAgICBhd2FpdCBzdWJzY3JpYmVPbmUoY29udGF0byk7XG4gICAgICB9XG4gICAgfSBlbHNlIHtcbiAgICAgIGZvciAoY29uc3QgY29udGF0byBvZiBjb250YWN0VG9BcnJheShwaG9uZSwgaXNHcm91cCwgZmFsc2UsIGlzTGlkKSkge1xuICAgICAgICBhd2FpdCBzdWJzY3JpYmVPbmUoY29udGF0byk7XG4gICAgICB9XG4gICAgfVxuXG4gICAgcmVzLnN0YXR1cygyMDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnc3VjY2VzcycsXG4gICAgICByZXNwb25zZTogeyBtZXNzYWdlOiAnU3Vic2NyaWJlIHByZXNlbmNlIGV4ZWN1dGVkJyB9LFxuICAgIH0pO1xuICB9IGNhdGNoIChlcnJvcikge1xuICAgIHJlcS5sb2dnZXIuZXJyb3IoZXJyb3IpO1xuICAgIHJlcy5zdGF0dXMoNTAwKS5qc29uKHtcbiAgICAgIHN0YXR1czogJ2Vycm9yJyxcbiAgICAgIG1lc3NhZ2U6ICdFcnJvciBvbiBzdWJzY3JpYmUgcHJlc2VuY2UnLFxuICAgICAgZXJyb3I6IGVycm9yLFxuICAgIH0pO1xuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBzZXRPbmxpbmVQcmVzZW5jZShyZXE6IFJlcXVlc3QsIHJlczogUmVzcG9uc2UpIHtcbiAgLyoqXG4gICAqICNzd2FnZ2VyLnRhZ3MgPSBbXCJNaXNjXCJdXG4gICAgICNzd2FnZ2VyLm9wZXJhdGlvbklkID0gJ3NldE9ubGluZVByZXNlbmNlJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgICAjc3dhZ2dlci5yZXF1ZXN0Qm9keSA9IHtcbiAgICAgIHJlcXVpcmVkOiB0cnVlLFxuICAgICAgXCJAY29udGVudFwiOiB7XG4gICAgICAgIFwiYXBwbGljYXRpb24vanNvblwiOiB7XG4gICAgICAgICAgc2NoZW1hOiB7XG4gICAgICAgICAgICB0eXBlOiBcIm9iamVjdFwiLFxuICAgICAgICAgICAgcHJvcGVydGllczoge1xuICAgICAgICAgICAgICBpc09ubGluZTogeyB0eXBlOiBcImJvb2xlYW5cIiB9LFxuICAgICAgICAgICAgfVxuICAgICAgICAgIH0sXG4gICAgICAgICAgZXhhbXBsZToge1xuICAgaXNPbmxpbmU6IGZhbHNlLFxuICAgICAgICAgIH1cbiAgICAgICAgfVxuICAgICAgfVxuICAgICB9XG4gICAqL1xuICB0cnkge1xuICAgIGNvbnN0IHsgaXNPbmxpbmUgPSB0cnVlIH0gPSByZXEuYm9keTtcblxuICAgIGF3YWl0IHJlcS5jbGllbnQuc2V0T25saW5lUHJlc2VuY2UoaXNPbmxpbmUpO1xuXG4gICAgcmVzLnN0YXR1cygyMDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnc3VjY2VzcycsXG4gICAgICByZXNwb25zZTogeyBtZXNzYWdlOiAnU2V0IE9ubGluZSBQcmVzZW5jZSBTdWNjZXNzZnVsbHknIH0sXG4gICAgfSk7XG4gIH0gY2F0Y2ggKGVycm9yKSB7XG4gICAgcmVzLnN0YXR1cyg1MDApLmpzb24oe1xuICAgICAgc3RhdHVzOiAnZXJyb3InLFxuICAgICAgbWVzc2FnZTogJ0Vycm9yIG9uIHNldCBvbmxpbmUgcHJlc2VuY2UnLFxuICAgICAgZXJyb3I6IGVycm9yLFxuICAgIH0pO1xuICB9XG59XG5cbmV4cG9ydCBhc3luYyBmdW5jdGlvbiBlZGl0QnVzaW5lc3NQcm9maWxlKHJlcTogUmVxdWVzdCwgcmVzOiBSZXNwb25zZSkge1xuICAvKipcbiAgICogI3N3YWdnZXIudGFncyA9IFtcIlByb2ZpbGVcIl1cbiAgICAgI3N3YWdnZXIub3BlcmF0aW9uSWQgPSAnZWRpdEJ1c2luZXNzUHJvZmlsZSdcbiAgICogI3N3YWdnZXIuZGVzY3JpcHRpb24gPSAnRWRpdCB5b3VyIGJ1c3NpbmVzcyBwcm9maWxlJ1xuICAgICAjc3dhZ2dlci5hdXRvQm9keT1mYWxzZVxuICAgICAjc3dhZ2dlci5zZWN1cml0eSA9IFt7XG4gICAgICAgICAgICBcImJlYXJlckF1dGhcIjogW11cbiAgICAgfV1cbiAgICAgI3N3YWdnZXIucGFyYW1ldGVyc1tcInNlc3Npb25cIl0gPSB7XG4gICAgICBzY2hlbWE6ICdORVJEV0hBVFNfQU1FUklDQSdcbiAgICAgfVxuICAgICAjc3dhZ2dlci5wYXJhbWV0ZXJzW1wib2JqXCJdID0ge1xuICAgICAgaW46ICdib2R5JyxcbiAgICAgIHNjaGVtYToge1xuICAgICAgICAkYWRyZXNzOiAnQXYuIE5vc3NhIFNlbmhvcmEgZGUgQ29wYWNhYmFuYSwgMzE1JyxcbiAgICAgICAgJGVtYWlsOiAndGVzdEB0ZXN0LmNvbS5icicsXG4gICAgICAgICRjYXRlZ29yaWVzOiB7XG4gICAgICAgICAgJGlkOiBcIjEzMzQzNjc0MzM4ODIxN1wiLFxuICAgICAgICAgICRsb2NhbGl6ZWRfZGlzcGxheV9uYW1lOiBcIkFydGVzIGUgZW50cmV0ZW5pbWVudG9cIixcbiAgICAgICAgICAkbm90X2FfYml6OiBmYWxzZSxcbiAgICAgICAgfSxcbiAgICAgICAgJHdlYnNpdGU6IFtcbiAgICAgICAgICBcImh0dHBzOi8vd3d3LndwcGNvbm5lY3QuaW9cIixcbiAgICAgICAgICBcImh0dHBzOi8vd3d3LnRlc3RlMi5jb20uYnJcIixcbiAgICAgICAgXSxcbiAgICAgIH1cbiAgICAgfVxuICAgICBcbiAgICAgI3N3YWdnZXIucmVxdWVzdEJvZHkgPSB7XG4gICAgICByZXF1aXJlZDogdHJ1ZSxcbiAgICAgIFwiQGNvbnRlbnRcIjoge1xuICAgICAgICBcImFwcGxpY2F0aW9uL2pzb25cIjoge1xuICAgICAgICAgIHNjaGVtYToge1xuICAgICAgICAgICAgdHlwZTogXCJvYmplY3RcIixcbiAgICAgICAgICAgIHByb3BlcnRpZXM6IHtcbiAgICAgICAgICAgICAgYWRyZXNzOiB7IHR5cGU6IFwic3RyaW5nXCIgfSxcbiAgICAgICAgICAgICAgZW1haWw6IHsgdHlwZTogXCJzdHJpbmdcIiB9LFxuICAgICAgICAgICAgICBjYXRlZ29yaWVzOiB7IHR5cGU6IFwib2JqZWN0XCIgfSxcbiAgICAgICAgICAgICAgd2Vic2l0ZXM6IHsgdHlwZTogXCJhcnJheVwiIH0sXG4gICAgICAgICAgICB9XG4gICAgICAgICAgfSxcbiAgICAgICAgICBleGFtcGxlOiB7XG4gICAgICAgICAgICBhZHJlc3M6ICdBdi4gTm9zc2EgU2VuaG9yYSBkZSBDb3BhY2FiYW5hLCAzMTUnLFxuICAgICAgICAgICAgZW1haWw6ICd0ZXN0QHRlc3QuY29tLmJyJyxcbiAgICAgICAgICAgIGNhdGVnb3JpZXM6IHtcbiAgICAgICAgICAgICAgJGlkOiBcIjEzMzQzNjc0MzM4ODIxN1wiLFxuICAgICAgICAgICAgICAkbG9jYWxpemVkX2Rpc3BsYXlfbmFtZTogXCJBcnRlcyBlIGVudHJldGVuaW1lbnRvXCIsXG4gICAgICAgICAgICAgICRub3RfYV9iaXo6IGZhbHNlLFxuICAgICAgICAgICAgfSxcbiAgICAgICAgICAgIHdlYnNpdGU6IFtcbiAgICAgICAgICAgICAgXCJodHRwczovL3d3dy53cHBjb25uZWN0LmlvXCIsXG4gICAgICAgICAgICAgIFwiaHR0cHM6Ly93d3cudGVzdGUyLmNvbS5iclwiLFxuICAgICAgICAgICAgXSxcbiAgICAgICAgICB9XG4gICAgICAgIH1cbiAgICAgIH1cbiAgICAgfVxuICAgKi9cbiAgdHJ5IHtcbiAgICByZXMuc3RhdHVzKDIwMCkuanNvbihhd2FpdCByZXEuY2xpZW50LmVkaXRCdXNpbmVzc1Byb2ZpbGUocmVxLmJvZHkpKTtcbiAgfSBjYXRjaCAoZXJyb3IpIHtcbiAgICByZXMuc3RhdHVzKDUwMCkuanNvbih7XG4gICAgICBzdGF0dXM6ICdlcnJvcicsXG4gICAgICBtZXNzYWdlOiAnRXJyb3Igb24gZWRpdCBidXNpbmVzcyBwcm9maWxlJyxcbiAgICAgIGVycm9yOiBlcnJvcixcbiAgICB9KTtcbiAgfVxufVxuIl0sIm1hcHBpbmdzIjoiOzs7Ozs7Ozs7Ozs7Ozs7OztBQWlCQSxJQUFBQSxHQUFBLEdBQUFDLHNCQUFBLENBQUFDLE9BQUE7QUFDQSxJQUFBQyxVQUFBLEdBQUFGLHNCQUFBLENBQUFDLE9BQUE7QUFDQSxJQUFBRSxPQUFBLEdBQUFILHNCQUFBLENBQUFDLE9BQUE7OztBQUdBLElBQUFHLFFBQUEsR0FBQUgsT0FBQTtBQUNBLElBQUFJLE9BQUEsR0FBQUwsc0JBQUEsQ0FBQUMsT0FBQTtBQUNBLElBQUFLLGtCQUFBLEdBQUFOLHNCQUFBLENBQUFDLE9BQUE7QUFDQSxJQUFBTSxVQUFBLEdBQUFOLE9BQUE7QUFDQSxJQUFBTyxhQUFBLEdBQUFSLHNCQUFBLENBQUFDLE9BQUE7QUFDQSxJQUFBUSxZQUFBLEdBQUFSLE9BQUEsd0JBQXlFLENBM0J6RTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0EsR0FlQSxNQUFNUyxXQUFXLEdBQUcsSUFBSUMsMEJBQWlCLENBQUMsQ0FBQyxDQUUz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QUMsR0FBRzlJLEdBQUcsQ0FBQytCLElBQUk7O0lBRXBDLE1BQU0vQixHQUFHLENBQUN2QixNQUFNLENBQUNvSyxpQkFBaUIsQ0FBQ0MsUUFBUSxDQUFDOztJQUU1QzdJLEdBQUcsQ0FBQ2EsTUFBTSxDQUFDLEdBQUcsQ0FBQyxDQUFDQyxJQUFJLENBQUM7TUFDbkJELE1BQU0sRUFBRSxTQUFTO01BQ2pCRSxRQUFRLEVBQUUsRUFBRXhDLE9BQU8sRUFBRSxrQ0FBa0MsQ0FBQztJQUMxRCxDQUFDLENBQUM7RUFDSixDQUFDLENBQUMsT0FBT2dCLEtBQUssRUFBRTtJQUNkUyxHQUFHLENBQUNhLE1BQU0sQ0FBQyxHQUFHLENBQUMsQ0FBQ0MsSUFBSSxDQUFDO01BQ25CRCxNQUFNLEVBQUUsT0FBTztNQUNmdEMsT0FBTyxFQUFFLDhCQUE4QjtNQUN2Q2dCLEtBQUssRUFBRUE7SUFDVCxDQUFDLENBQUM7RUFDSjtBQUNGOztBQUVPLGVBQWV1SixtQkFBbUJBLENBQUMvSSxHQUFZLEVBQUVDLEdBQWEsRUFBRTtFQUNyRTtBQUNGO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtFQUNFLElBQUk7SUFDRkEsR0FBRyxDQUFDYSxNQUFNLENBQUMsR0FBRyxDQUFDLENBQUNDLElBQUksQ0FBQyxNQUFNZixHQUFHLENBQUN2QixNQUFNLENBQUNzSyxtQkFBbUIsQ0FBQy9JLEdBQUcsQ0FBQytCLElBQUksQ0FBQyxDQUFDO0VBQ3RFLENBQUMsQ0FBQyxPQUFPdkMsS0FBSyxFQUFFO0lBQ2RTLEdBQUcsQ0FBQ2EsTUFBTSxDQUFDLEdBQUcsQ0FBQyxDQUFDQyxJQUFJLENBQUM7TUFDbkJELE1BQU0sRUFBRSxPQUFPO01BQ2Z0QyxPQUFPLEVBQUUsZ0NBQWdDO01BQ3pDZ0IsS0FBSyxFQUFFQTtJQUNULENBQUMsQ0FBQztFQUNKO0FBQ0YiLCJpZ25vcmVMaXN0IjpbXX0=