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
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
import { create, SocketState, StatusFind } from '@wppconnect-team/wppconnect';
import { exec, execFile, execSync } from 'child_process';
import { Request } from 'express';

import { download } from '../controller/sessionController';
import { WhatsAppServer } from '../types/WhatsAppServer';
import chatWootClient from './chatWootClient';
import { autoDownload, callWebHook, startHelper } from './functions';
import { clientsArray, eventEmitter } from './sessionUtil';
import Factory from './tokenStore/factory';

/**
 * Kill the actual Puppeteer/Chrome browser process (and its tree of child
 * renderer/GPU processes) behind `page`, given a live handle to it.
 *
 * This is the precise, preferred kill path — used whenever a `page` is
 * actually available (e.g. closeSession() on an already-created session).
 * `page.browser().process()` returns Node's own ChildProcess for a
 * locally-launched browser; Node's `ChildProcess.kill()` alone only signals
 * that one process on Windows (Windows has no process-group SIGKILL
 * cascade), so this shells out to `taskkill /T` for the actual tree-kill —
 * the same thing @puppeteer/browsers' own Process.kill() does internally.
 * Falls back to forceKillByUserDataDir() (below) when no page/pid is
 * available, e.g. mid-pairing, before create() has returned.
 */
function forceKillBrowserProcess(page: any, logger?: any): boolean {
  let pid: number | undefined;
  try {
    pid = page?.browser?.()?.process?.()?.pid;
    if (!pid) return false;
    if (process.platform === 'win32') {
      execSync(`taskkill /pid ${pid} /T /F`, { stdio: 'ignore' });
    } else {
      process.kill(pid, 'SIGKILL');
    }
    logger?.info?.(`[forceKillBrowserProcess] Killed browser process ${pid} and its tree`);
    return true;
  } catch (e: any) {
    logger?.warn?.(
      `[forceKillBrowserProcess] Failed to kill browser process ${pid}: ${e?.message || e}`
    );
    return false;
  }
}

/**
 * Best-effort fallback: kill whatever process (Chrome + its children) has
 * this session's userDataDir on its command line, used when there is no
 * live `page`/`pid` handle to kill precisely (e.g. shouldClose fires inside
 * catchQR/catchLinkCode, which run synchronously *during* `create()` —
 * before the `wppClient` it returns is even assigned, so nothing in this
 * file can reach the browser directly yet).
 *
 * This used to be `exec('pkill -9 -f "<userDataDir>"')` unconditionally.
 * `pkill` does not exist on Windows at all — Node's child_process.exec
 * spawns it via cmd.exe, which can't find the command, and the callback
 * here discarded the error — so on Windows this silently killed nothing,
 * ever. That's the root cause behind WinZapp's WhatsApp Web session
 * occasionally coming back "logged out" after exiting: closeSession()'s
 * fast path (see sessionController.ts) skips the graceful
 * `await client.close()` whenever the session isn't fully CONNECTED and
 * relies entirely on this function instead — silently doing nothing left
 * Chrome running, so WinZapp's own exit routine eventually had to
 * `taskkill /F /T` the whole Node process tree once its grace period ran
 * out, tearing down Chrome's profile (a LevelDB store) mid-write.
 */
function forceKillByUserDataDir(userDataDir: string, logger?: any) {
  if (!userDataDir) return;
  if (process.platform === 'win32') {
    // Windows has no built-in "kill by command-line substring" either, so
    // this uses PowerShell's CIM/WMI process query — the closest equivalent
    // to `pkill -f` available without a third-party dependency.
    const psFilter = userDataDir.replace(/'/g, "''").replace(/\\/g, '\\\\');
    const script =
      `Get-CimInstance Win32_Process | ` +
      `Where-Object { $_.CommandLine -like '*${psFilter}*' } | ` +
      `ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }`;
    execFile(
      'powershell.exe',
      ['-NoProfile', '-NonInteractive', '-Command', script],
      (err) => {
        if (err) {
          logger?.warn?.(`[forceKillByUserDataDir] PowerShell kill failed: ${err.message}`);
        }
      }
    );
  } else {
    exec(`pkill -9 -f "${userDataDir}"`, () => {});
  }
}

/**
 * Restore `MsgKey.prototype._serialized` inside the WhatsApp Web page.
 *
 * WhatsApp Web's minified build renamed the `_serialized` getter on MsgKey to
 * `$1` (the Wid class, used for chat/contact ids, was NOT affected — only
 * MsgKey). WPPConnect's serializer is hardcoded against the old name:
 *
 *     WAPI._serializeMessageObj = e => Object.assign(
 *       WAPI._serializeRawObj(e), { id: e.id._serialized, ... })
 *
 * so `id` became `undefined` and JSON.stringify dropped the property outright.
 * Every message returned by get-messages arrived with no id at all, WinZapp
 * normalized it to `key.id = ""`, and DatabaseManager dropped 100% of them as
 * id-less (a chat list with unread counts over a database with zero messages).
 * `quotedMsgId` and `quotedParticipant` were silently lost the same way.
 *
 * The getter below reads `$1` when present and otherwise rebuilds the id from
 * the MsgKey's own fields, which is exactly the format WhatsApp itself uses
 * (`false_120363127023984493@g.us_AC9249DF…`). That second path is what keeps
 * this working if a future build renames `$1` again.
 */
async function restoreMsgKeySerialized(
  page: any,
  logger: any,
  session: string
) {
  if (!page) return;
  try {
    const result = await page.evaluate(() => {
      const install = () => {
        const MK = (window as any).WPP?.whatsapp?.MsgKey;
        // wa-js is injected asynchronously after each navigation, so on the
        // page-reload path MsgKey usually does not exist yet on the first try.
        if (!MK || !MK.prototype) return false;
        // `in` walks the prototype chain — an unaffected build already has it.
        if ('_serialized' in MK.prototype) return true;
        Object.defineProperty(MK.prototype, '_serialized', {
          configurable: true,
          get() {
            if (typeof this.$1 === 'string' && this.$1) return this.$1;
            const jid = (w: any) =>
              typeof w === 'string' ? w : w?._serialized ?? w?.$1 ?? '';
            const remote = jid(this.remote);
            if (!remote || !this.id) return '';
            const participant = jid(this.participant);
            return (
              `${!!this.fromMe}_${remote}_${this.id}` +
              (participant ? `_${participant}` : '')
            );
          },
        });
        return true;
      };
      if (install()) return 'installed';
      // Retry in the background rather than awaiting here: blocking the
      // evaluate would stall session startup for as long as wa-js takes.
      let tries = 0;
      const timer = setInterval(() => {
        if (install() || ++tries > 60) clearInterval(timer);
      }, 500);
      return 'scheduled (wa-js not ready yet)';
    });
    logger.info(`[${session}] MsgKey._serialized shim: ${result}`);
  } catch (e: any) {
    // Never fatal: without the shim messages lose their ids, but the session
    // itself is still perfectly usable.
    logger.error(
      `[${session}] Failed to install MsgKey._serialized shim: ${
        e?.message || e
      }`
    );
  }
}

export default class CreateSessionUtil {
  forceKillSession(session: string, logger?: any) {
    const client: any = clientsArray[session];
    if (!forceKillBrowserProcess(client?.page, logger)) {
      forceKillByUserDataDir(`userDataDir/${session}`, logger);
    }
  }

  startChatWootClient(client: any) {
    if (client.config.chatWoot && !client._chatWootClient)
      client._chatWootClient = new chatWootClient(
        client.config.chatWoot,
        client.session
      );
    return client._chatWootClient;
  }

  async createSessionUtil(
    req: any,
    clientsArray: any,
    session: string,
    res?: any
  ) {
    try {
      let client = this.getClient(session) as any;
      if (client.status != null && client.status !== 'CLOSED') return;
      client.status = 'INITIALIZING';
      client.config = req.body;

      const tokenStore = new Factory();
      const myTokenStore = tokenStore.createTokenStory(client);
      const tokenData = await myTokenStore.getToken(session);

      // we need this to update phone in config every time session starts, so we can ask for code for it again.
      //
      // WinZapp patch: only rewrite the token when we actually read one back.
      // Upstream writes `tokenData ?? {}`, so ANY failure to read the stored
      // token — a transient fs error, a file still locked by a previous
      // instance that was force-killed, a partially-written JSON — is
      // immediately made permanent by overwriting it with an empty object.
      // The saved WhatsApp Web credentials are then gone for good and the next
      // start looks like a logout, even though the phone still lists the linked
      // device. Reading nothing is not a reason to destroy what is on disk.
      if (tokenData) {
        myTokenStore.setToken(session, tokenData);
      } else {
        req.logger?.warn?.(
          `[${session}] Token store returned no data — leaving the stored token untouched.`
        );
      }

      this.startChatWootClient(client);

      if (req.serverOptions.customUserDataDir) {
        req.serverOptions.createOptions.puppeteerOptions = Object.assign(
          { protocolTimeout: 120000 },
          req.serverOptions.createOptions.puppeteerOptions || {},
          { userDataDir: req.serverOptions.customUserDataDir + session }
        );
      } else {
        req.serverOptions.createOptions.puppeteerOptions = Object.assign(
          { protocolTimeout: 120000 },
          req.serverOptions.createOptions.puppeteerOptions || {}
        );
      }

      // Best-effort kill for the shouldClose branches below. `wppClient` is
      // only assigned once `create()` actually returns — catchLinkCode/
      // catchQR/statusFind run synchronously *during* create() itself
      // (before that assignment), so referencing `wppClient` there is a
      // temporal-dead-zone ReferenceError, silently swallowed by their
      // existing `try { wppClient.close() } catch {}`. This has the same
      // problem and stays wrapped for the same reason, but tries the
      // precise process-tree kill first and only falls back to the
      // userDataDir scan when no live page/pid is reachable yet.
      const killBrowserOrFallback = () => {
        let killed = false;
        try {
          killed = forceKillBrowserProcess(wppClient?.page, req.logger);
        } catch (e) {}
        if (!killed) forceKillByUserDataDir(`userDataDir/${session}`, req.logger);
      };

      const wppClient = await create(
        Object.assign(
          {},
          { tokenStore: myTokenStore },
          client.config.proxy
            ? {
                proxy: {
                  url: client.config.proxy?.url,
                  username: client.config.proxy?.username,
                  password: client.config.proxy?.password,
                },
              }
            : {},
          req.serverOptions.createOptions,
          {
            session: session,
            phoneNumber: client.config.phone ?? null,
            deviceName:
              client.config.phone == undefined // bug when using phone code this shouldn't be passed (https://github.com/wppconnect-team/wppconnect-server/issues/1687#issuecomment-2099357874)
                ? client.config?.deviceName ||
                  req.serverOptions.deviceName ||
                  'WppConnect'
                : undefined,
            poweredBy:
              client.config.phone == undefined // bug when using phone code this shouldn't be passed (https://github.com/wppconnect-team/wppconnect-server/issues/1687#issuecomment-2099357874)
                ? client.config?.poweredBy ||
                  req.serverOptions.poweredBy ||
                  'WPPConnect-Server'
                : undefined,
            catchLinkCode: (code: string) => {
              if ((client as any).shouldClose) {
                req.logger.info(`[${session}] shouldClose detected in catchLinkCode. Force-killing browser.`);
                killBrowserOrFallback();
                clientsArray[session] = undefined;
                return;
              }
              this.exportPhoneCode(req, client.config.phone, code, client, res);
            },
            catchQR: (
              base64Qr: any,
              asciiQR: any,
              attempt: any,
              urlCode: string
            ) => {
              if ((client as any).shouldClose) {
                req.logger.info(`[${session}] shouldClose detected in catchQR. Force-killing browser.`);
                killBrowserOrFallback();
                clientsArray[session] = undefined;
                return;
              }
              this.exportQR(req, base64Qr, urlCode, client, res);
            },
            onLoadingScreen: (percent: string, message: string) => {
              req.logger.info(`[${session}] ${percent}% - ${message}`);
            },
            statusFind: (statusFind: StatusFind) => {
              try {
                if ((client as any).shouldClose) {
                  req.logger.info(`[${session}] shouldClose detected in statusFind. Force-killing browser.`);
                  killBrowserOrFallback();
                  clientsArray[session] = undefined;
                  return;
                }
                eventEmitter.emit(
                  `status-${client.session}`,
                  client,
                  statusFind
                );
                if (
                  statusFind === StatusFind.autocloseCalled
                ) {
                  client.status = 'CLOSED';
                  client.qrcode = null;
                  client.close();
                  clientsArray[session] = undefined;
                }
                callWebHook(client, req, 'status-find', {
                  status: statusFind,
                  session: client.session,
                });
                req.logger.info(statusFind + '\n\n');
              } catch (error) {}
            },
          }
        )
      );

      // Poll every 2s: if shouldClose was set while create() is blocked, close browser immediately
      const shouldClosePoller = setInterval(() => {
        if ((client as any).shouldClose) {
          req.logger.info(`[${session}] shouldClose detected by poller. Force-killing browser.`);
          clearInterval(shouldClosePoller);
          killBrowserOrFallback();
          clientsArray[session] = undefined;
        }
      }, 2000);

      if (clientsArray[session] && (clientsArray[session] as any).shouldClose) {
        clearInterval(shouldClosePoller);
        req.logger.info(`[${session}] Session was closed during initialization. Terminating browser.`);
        try {
          await wppClient.close();
        } catch (e) {}
        clientsArray[session] = undefined;
        if (res && !res.headersSent) {
          res.status(200).json({ status: false, message: 'Session closed during initialization' });
        }
        return;
      }
      clearInterval(shouldClosePoller);

      client = clientsArray[session] = Object.assign(wppClient, client);
      if (client.page) {
        client.page.on('console', (msg: any) => {
          const text = msg.text();
          if (text.includes('[browser-evaluate]')) {
            req.logger.info(text);
          }
        });
        // The shim lives on a prototype inside the page, so it dies with every
        // WhatsApp Web reload (and wa-js is re-injected fresh each time).
        // Re-install on load as well as right now, or the first reload
        // silently brings the id-less messages back.
        client.page.on('load', () => {
          restoreMsgKeySerialized(client.page, req.logger, session);
        });
        await restoreMsgKeySerialized(client.page, req.logger, session);
      }
      await this.start(req, client);

      if (req.serverOptions.webhook.onParticipantsChanged) {
        await this.onParticipantsChanged(req, client);
      }

      if (req.serverOptions.webhook.onReactionMessage) {
        await this.onReactionMessage(client, req);
      }

      if (req.serverOptions.webhook.onRevokedMessage) {
        await this.onRevokedMessage(client, req);
      }

      if (req.serverOptions.webhook.onPollResponse) {
        await this.onPollResponse(client, req);
      }
      if (req.serverOptions.webhook.onLabelUpdated) {
        await this.onLabelUpdated(client, req);
      }
    } catch (e) {
      req.logger.error(e);
      if (e instanceof Error && e.name == 'TimeoutError') {
        const client = this.getClient(session) as any;
        client.status = 'CLOSED';
      }
    }
  }

  async opendata(req: Request, session: string, res?: any) {
    await this.createSessionUtil(req, clientsArray, session, res);
  }

  exportPhoneCode(
    req: any,
    phone: any,
    phoneCode: any,
    client: WhatsAppServer,
    res?: any
  ) {
    if ((client as any).shouldClose) return;
    eventEmitter.emit(`phoneCode-${client.session}`, phoneCode, client);

    Object.assign(client, {
      status: 'PHONECODE',
      phoneCode: phoneCode,
      phone: phone,
    });

    req.io.emit('phoneCode', {
      data: phoneCode,
      phone: phone,
      session: client.session,
    });

    callWebHook(client, req, 'phoneCode', {
      phoneCode: phoneCode,
      phone: phone,
      session: client.session,
    });

    if (res && !res._headerSent)
      res.status(200).json({
        status: 'phoneCode',
        phone: phone,
        phoneCode: phoneCode,
        session: client.session,
      });
  }

  exportQR(
    req: any,
    qrCode: any,
    urlCode: any,
    client: WhatsAppServer,
    res?: any
  ) {
    if ((client as any).shouldClose) return;
    eventEmitter.emit(`qrcode-${client.session}`, qrCode, urlCode, client);
    Object.assign(client, {
      status: 'QRCODE',
      qrcode: qrCode,
      urlcode: urlCode,
    });

    qrCode = qrCode.replace('data:image/png;base64,', '');
    const imageBuffer = Buffer.from(qrCode, 'base64');

    req.io.emit('qrCode', {
      data: 'data:image/png;base64,' + imageBuffer.toString('base64'),
      session: client.session,
    });

    callWebHook(client, req, 'qrcode', {
      qrcode: qrCode,
      urlcode: urlCode,
      session: client.session,
    });
    if (res && !res._headerSent)
      res.status(200).json({
        status: 'qrcode',
        qrcode: qrCode,
        urlcode: urlCode,
        session: client.session,
      });
  }

  async onParticipantsChanged(req: any, client: any) {
    await client.isConnected();
    await client.onParticipantsChanged((message: any) => {
      callWebHook(client, req, 'onparticipantschanged', message);
    });
  }

  async start(req: Request, client: WhatsAppServer) {
    try {
      await client.isConnected();
      Object.assign(client, { status: 'CONNECTED', qrcode: null });

      req.logger.info(`Started Session: ${client.session}`);
      //callWebHook(client, req, 'session-logged', { status: 'CONNECTED'});
      req.io.emit('session-logged', { status: true, session: client.session });
      startHelper(client, req);
    } catch (error) {
      req.logger.error(error);
      req.io.emit('session-error', client.session);
    }

    await this.checkStateSession(client, req);
    await this.listenMessages(client, req);

    if (req.serverOptions.webhook.listenAcks) {
      await this.listenAcks(client, req);
    }

    if (req.serverOptions.webhook.onPresenceChanged) {
      await this.onPresenceChanged(client, req);
    }

    await this.onUnreadCountChanged(client, req);
  }

  /**
   * WinZapp patch: forward WA-JS's own `chat.unread_count_changed` event
   * (fired whenever a chat's unread count changes for ANY reason — including
   * the user reading it on their phone or another linked device) to
   * WinZapp's client as a `chats-update` socket event.
   *
   * There is no wppconnect-server webhook/event wrapper for this — every
   * other onXxx() in this file (onReactionMessage, onPollResponse, ...)
   * relies on an ExposedFn binding wppconnect's own page-injection code sets
   * up ahead of time, and this event has none. `page.exposeFunction()`
   * needs no such prior wiring: it lets Node register a callback directly
   * invocable from the page, so a small `WPP.on(...)` installed here is
   * self-contained. Without this, WinZapp's own `on_chats_update` handler
   * (which already exists client-side and does exactly the right thing)
   * never received a single event — a chat read on the phone stayed shown
   * as unread in WinZapp until the user happened to open it there too.
   *
   * `WPP.on` lives on the page and is re-injected fresh on every WhatsApp
   * Web reload, same as the msgKey._serialized shim above — re-install on
   * 'load' too, or the first reload silently drops this listener.
   */
  async onUnreadCountChanged(client: WhatsAppServer, req: Request) {
    try {
      await client.page.exposeFunction(
        '__winzappOnUnreadChanged',
        (chatId: string, unreadCount: number) => {
          req.io.emit('chats-update', {
            data: [{ remoteJid: chatId, unreadCount }],
          });
        }
      );
    } catch (e) {
      // exposeFunction throws if a prior session already registered this
      // name on the same page (e.g. a reconnect reusing the browser) —
      // harmless, the existing binding still works.
    }

    const installListener = () => {
      client.page
        .evaluate(() => {
          const WPP = (window as any).WPP;
          if (!WPP || !WPP.on || (window as any).__winzappUnreadListenerInstalled) {
            return;
          }
          (window as any).__winzappUnreadListenerInstalled = true;
          WPP.on('chat.unread_count_changed', (evt: any) => {
            const chatId = evt?.chat?.id?._serialized || evt?.chat?.id;
            if (!chatId) return;
            (window as any).__winzappOnUnreadChanged(chatId, evt.unreadCount);
          });
        })
        .catch((e: any) => req.logger.warn(`[onUnreadCountChanged] install failed: ${e?.message || e}`));
    };

    // A page reload gets a fresh JS context (window.__winzappUnreadListenerInstalled
    // starts undefined again along with everything else wa-js re-injects), so
    // re-running installListener() here is exactly the reinstall the reload
    // needs — no separate reset step required.
    client.page.on('load', installListener);
    installListener();
  }

  async checkStateSession(client: WhatsAppServer, req: Request) {
    await client.onStateChange((state) => {
      req.logger.info(`State Change ${state}: ${client.session}`);
      const conflits = [SocketState.CONFLICT];

      if (conflits.includes(state)) {
        client.useHere();
      }
    });
  }

  async listenMessages(client: WhatsAppServer, req: Request) {
    await client.onMessage(async (message: any) => {
      eventEmitter.emit(`mensagem-${client.session}`, client, message);
      callWebHook(client, req, 'onmessage', message);
      if (message.type === 'location')
        client.onLiveLocation(message.sender.id, (location) => {
          callWebHook(client, req, 'location', location);
        });
    });

    await client.onAnyMessage(async (message: any) => {
      message.session = client.session;

      if (message.type === 'sticker') {
        download(message, client, req.logger);
      }

      if (
        req.serverOptions?.websocket?.autoDownload ||
        (req.serverOptions?.webhook?.autoDownload && message.fromMe == false)
      ) {
        await autoDownload(client, req, message);
      }

      req.io.emit('received-message', { response: message });
      if (req.serverOptions.webhook.onSelfMessage && message.fromMe)
        callWebHook(client, req, 'onselfmessage', message);
    });

    await client.onIncomingCall(async (call) => {
      req.io.emit('incomingcall', call);
      callWebHook(client, req, 'incomingcall', call);
    });
  }

  async listenAcks(client: WhatsAppServer, req: Request) {
    await client.onAck(async (ack) => {
      req.io.emit('onack', ack);
      callWebHook(client, req, 'onack', ack);
    });
  }

  async onPresenceChanged(client: WhatsAppServer, req: Request) {
    await client.onPresenceChanged(async (presenceChangedEvent) => {
      req.io.emit('onpresencechanged', presenceChangedEvent);
      callWebHook(client, req, 'onpresencechanged', presenceChangedEvent);
    });
  }

  async onReactionMessage(client: WhatsAppServer, req: Request) {
    await client.isConnected();
    await client.onReactionMessage(async (reaction: any) => {
      req.io.emit('onreactionmessage', reaction);
      callWebHook(client, req, 'onreactionmessage', reaction);
    });
  }

  async onRevokedMessage(client: WhatsAppServer, req: Request) {
    await client.isConnected();
    await client.onRevokedMessage(async (response: any) => {
      req.io.emit('onrevokedmessage', response);
      callWebHook(client, req, 'onrevokedmessage', response);
    });
  }
  async onPollResponse(client: WhatsAppServer, req: Request) {
    await client.isConnected();
    await client.onPollResponse(async (response: any) => {
      req.io.emit('onpollresponse', response);
      callWebHook(client, req, 'onpollresponse', response);
    });
  }
  async onLabelUpdated(client: WhatsAppServer, req: Request) {
    await client.isConnected();
    await client.onUpdateLabel(async (response: any) => {
      req.io.emit('onupdatelabel', response);
      callWebHook(client, req, 'onupdatelabel', response);
    });
  }

  encodeFunction(data: any, webhook: any) {
    data.webhook = webhook;
    return JSON.stringify(data);
  }

  decodeFunction(text: any, client: any) {
    const object = JSON.parse(text);
    if (object.webhook && !client.webhook) client.webhook = object.webhook;
    delete object.webhook;
    return object;
  }

  getClient(session: any) {
    let client = clientsArray[session];

    if (!client)
      client = clientsArray[session] = {
        status: null,
        session: session,
      } as any;
    return client;
  }
}
