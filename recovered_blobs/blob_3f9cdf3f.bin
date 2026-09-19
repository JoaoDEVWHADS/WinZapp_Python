/*
 * WinZapp call-control endpoints.
 *
 * WhatsApp Web owns signaling and encryption inside Chromium. WinZapp owns the
 * accessible desktop UI and the Python microphone/speaker pipeline. These
 * endpoints expose the WA-JS call functions WPPConnect Server does not expose
 * yet, while activating the injected media bridge before a call asks for audio.
 */
import { Request, Response } from 'express';

import {
  ensureCallMediaBridge,
  setCallMediaBridgeActive,
  warmCallVoipRuntime,
} from '../util/callMediaBridge';

type CallActionPayload = {
  callId?: string;
  to?: string;
  isVideo?: boolean;
  participants?: string[];
  groupJid?: string;
  useGroupChat?: boolean;
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
  const logger = (req as any).logger;
  const session = String((req.client as any)?.session || 'unknown');
  // Session startup warms the lazy VoIP bundle in the background. Await it in
  // Node, before entering the browser context, so the browser callback never
  // tries to resolve a Node-side helper name.
  await warmCallVoipRuntime(req.client, logger);

  if (action === 'offer-group') {
    logger?.info?.(
      `[${session}] WinZapp group-call request ` +
        JSON.stringify({
          participantCount: Array.isArray(payload.participants) ? payload.participants.length : 0,
          groupJid: payload.groupJid || '',
          useGroupChat: payload.useGroupChat === true,
        })
    );
  }

  let result: any;
  try {
    result = await page.evaluate(
    async ({ action, payload }) => {
      const win = window as any;
      if (!win.WPP?.call) throw new Error('WPP.call is not available');

      const serializeId = (value: any): string => {
        if (!value) return '';
        if (typeof value === 'string') return value;
        return String(value._serialized || value.id || value.toString?.() || value || '');
      };

      const callIdOf = (call: any): string => serializeId(call?.id);
      const peerJidOf = (call: any): string => serializeId(call?.peerJid || call?.sender || call?.from);
      const getCallStore = () => {
        try {
          const module = win.require?.('WAWebCallCollection');
          const nativeStore =
            module?.activeCall !== undefined ? module : module?.get?.() || module;
          if (nativeStore) return nativeStore;
        } catch (_) {}
        return win.WPP?.whatsapp?.CallStore || win.Store?.Call || null;
      };
      const sameCallId = (call: any, wanted: string): boolean => {
        if (!call || !wanted) return false;
        return callIdOf(call) === wanted || serializeId(call?.id?._serialized) === wanted;
      };

      const callStateOf = (call: any): string => {
        // getState() legitimately returns numeric 0 for the terminal/NONE
        // state. Using || erased that value and made a dead CallModel look
        // like it had no state at all, which in turn let /group/offer return
        // HTTP 200 for a call WhatsApp had already abandoned.
        const rawValue =
          call?.getState?.() ?? call?.state ?? call?.get?.('state') ?? '';
        const raw = String(rawValue);
        const numericStates: Record<string, string> = {
          '0': 'NONE',
          '1': 'CALLING',
          '2': 'PREACCEPT_RECEIVED',
          '3': 'INCOMING_RING',
          '4': 'ACCEPT_SENT',
          '5': 'ACCEPT_RECEIVED',
          '6': 'ACTIVE',
          '7': 'HANDLED_REMOTELY',
          '8': 'INCOMING_RING',
          '9': 'REJOINING',
          '10': 'LINK',
          '11': 'CONNECTED_LONELY',
          '12': 'PRE_CALLING',
          '13': 'ENDED',
          '14': 'CALL_B_STARTING',
        };
        return numericStates[raw] || raw;
      };

      const isIncomingCall = (call: any): boolean => {
        const state = callStateOf(call);
        return (
          state === 'INCOMING_RING' ||
          state === 'ReceivedCall' ||
          state === 'ReceivedCallWithoutOffer' ||
          call?.isIncoming === true ||
          call?.direction === 'incoming'
        );
      };

      const isOutgoingOrLiveCall = (call: any): boolean => {
        const state = callStateOf(call);
        return (
          state === 'CALLING' ||
          state === 'PRE_CALLING' ||
          state === 'ACCEPT_SENT' ||
          state === 'ACCEPT_RECEIVED' ||
          state === 'ACTIVE' ||
          state === 'CALL_B_STARTING' ||
          call?.outgoing === true ||
          call?.isOutgoing === true ||
          call?.direction === 'outgoing'
        );
      };

      const getModels = (store: any): any[] => {
        try {
          const models = store?.getModelsArray?.();
          if (Array.isArray(models)) return models;
        } catch (_) {}
        if (Array.isArray(store?.models)) return store.models;
        if (Array.isArray(store?._models)) return store._models;
        return [];
      };

      const findCall = (wanted = ''): any => {
        const store = getCallStore();
        const active = store?.activeCall;
        if (active && (!wanted || sameCallId(active, wanted))) return active;

        if (wanted && typeof store?.get === 'function') {
          try {
            const direct = store.get(wanted);
            if (direct) return direct;
          } catch (_) {}
        }

        const models = getModels(store);
        if (wanted) {
          const exact = models.find((call) => sameCallId(call, wanted));
          if (exact) return exact;
        }
        return (
          models.find((call) => isIncomingCall(call) || isOutgoingOrLiveCall(call) || call?.isGroup) ||
          null
        );
      };

      const groupParticipantCountOf = (call: any): number => {
        const participants =
          call?.groupCallParticipants ??
          call?.get?.('groupCallParticipants') ??
          call?.participants ??
          call?.get?.('participants');
        if (!participants) return 0;
        if (Array.isArray(participants)) return participants.length;
        try {
          const models = participants?.getModelsArray?.();
          if (Array.isArray(models)) return models.length;
        } catch (_) {}
        if (Array.isArray(participants?.models)) return participants.models.length;
        if (Array.isArray(participants?._models)) return participants._models.length;
        if (typeof participants?.size === 'number') return participants.size;
        if (typeof participants?.length === 'number') return participants.length;
        return 0;
      };

      const summarizeCall = (call: any) => ({
        id: callIdOf(call),
        peerJid: peerJidOf(call),
        state: callStateOf(call),
        isVideo: !!call?.isVideo,
        isGroup: !!call?.isGroup,
        groupParticipantCount: groupParticipantCountOf(call),
        outgoing: !!call?.outgoing,
      });

      const functionDiagnostic = (fn: any) => {
        if (typeof fn !== 'function') return { type: typeof fn, arity: null, source: '' };
        let source = '';
        try {
          source = String(fn).replace(/\s+/g, ' ').slice(0, 900);
        } catch (_) {}
        return { type: 'function', arity: fn.length, source };
      };

      const callStoreSnapshot = () => {
        const store = getCallStore();
        const models = getModels(store);
        return {
          activeCall: store?.activeCall ? summarizeCall(store.activeCall) : null,
          modelCount: models.length,
          models: models.slice(-8).map((model) => summarizeCall(model)),
        };
      };

      const forgetIncomingCall = (callId: string) => {
        if (!callId) return;
        try {
          win.__winzappForgetIncomingCall?.(callId);
        } catch (_) {}
      };

      const delay = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

      const getNativeVoipStack = async (): Promise<any> => {
        const getter =
          win.WPP?.whatsapp?.functions?.getVoipStackInterface ||
          win.WPP?.whatsapp?.getVoipStackInterface;
        if (typeof getter !== 'function') return null;
        return getter();
      };

      const isVoipInitialized = (): boolean | undefined => {
        const conn =
          win.WPP?.whatsapp?.ConnStore || win.Store?.Conn || win.WPP?.whatsapp?.Conn;
        if (!conn || typeof conn.isVoipInitialized !== 'boolean') return undefined;
        return conn.isVoipInitialized;
      };

      const ensureVoipRuntimeReady = async (): Promise<any> => {
        const installEarlyWasmProbe = () => {
          try {
            const backendApi = win.require?.('WAWebBackendApi');
            if (
              !backendApi ||
              typeof backendApi.frontendSendAndReceive !== 'function' ||
              backendApi.__winzappWasmProbeInstalled
            ) {
              return;
            }

            const originalFrontendSendAndReceive =
              backendApi.frontendSendAndReceive.bind(backendApi);

            const wrapWasm = (wasm: any) => {
              if (!wasm || typeof wasm.startVoipGroupCall !== 'function') return wasm;
              if (wasm.__winzappStartVoipGroupCallProbe) return wasm;

              const originalStartVoipGroupCall =
                wasm.startVoipGroupCall.bind(wasm);
              wasm.startVoipGroupCall = (...args: any[]) => {
                const status = originalStartVoipGroupCall(...args);
                const listSize = (value: any) => {
                  try {
                    if (typeof value?.size === 'function') return value.size();
                    if (typeof value?.length === 'number') return value.length;
                  } catch (_) {}
                  return null;
                };
                win.__winzappLastStartVoipGroupCallStatus = {
                  at: Date.now(),
                  status,
                  argCount: args.length,
                  pnCount: listSize(args[0]),
                  lidCount: listSize(args[1]),
                  deviceCsvCount: listSize(args[2]),
                  callId: String(args[3] || ''),
                  useVideo: !!args[4],
                  groupJid: String(args[5] || ''),
                  isLightWeight: !!args[6],
                  callFromUi: args[10] ?? null,
                  lobbyEntryPoint: args[11] ?? null,
                };
                return status;
              };
              wasm.__winzappStartVoipGroupCallProbe = true;
              return wasm;
            };

            backendApi.frontendSendAndReceive = async (...args: any[]) => {
              const value = await originalFrontendSendAndReceive(...args);
              if (args[0] === 'initializeVoipWasm') {
                return wrapWasm(value);
              }
              return value;
            };
            backendApi.__winzappWasmProbeInstalled = true;
            win.__winzappEarlyWasmProbeInstalled = true;
          } catch (error: any) {
            win.__winzappEarlyWasmProbeError =
              String(error?.message || error || 'unknown error');
          }
        };

        installEarlyWasmProbe();

        // Keep the VoIP stack on the main thread. WhatsApp's current
        // WorkerProxy fires startGroupCall as a one-way RPC and discards the
        // underlying WASM status, which makes failed group calls look like
        // successful short-lived CALLING models.
        try {
          const abProps = win.require?.('WAWebABProps');
          if (
            abProps &&
            typeof abProps.getABPropConfigValue === 'function' &&
            !abProps.__winzappDirectVoipStack
          ) {
            const originalGetABPropConfigValue =
              abProps.getABPropConfigValue.bind(abProps);
            abProps.getABPropConfigValue = (key: string, ...args: any[]) => {
              if (key === 'enable_web_voip_proxy_and_sctp_workers') return false;
              return originalGetABPropConfigValue(key, ...args);
            };
            abProps.__winzappDirectVoipStack = true;
          }
        } catch (_) {}

        // WA-JS' enableCallInterface flips the calling AB props, but it marks
        // itself enabled before its best-effort backend init. If that first
        // init races the lazy VoIP bundle, later calls never retry it. Retry
        // the actual backend initialization here before every call action.
        const enable = win.WPP?.call?.enableCallInterface;
        if (typeof enable === 'function') await enable();

        const functions = win.WPP?.whatsapp?.functions || {};
        const requireBackend =
          functions.requireVoipJsBackend ||
          win.WPP?.whatsapp?.requireVoipJsBackend;

        let lastError: any = null;
        for (let attempt = 0; attempt < 8; attempt += 1) {
          try {
            if (typeof requireBackend === 'function') {
              const backend = await requireBackend();
              const init =
                backend?.WAWebVoipInit?.initWAWebVoip ||
                backend?.initWAWebVoip;
              if (typeof init === 'function') {
                const initModule = backend?.WAWebVoipInit || backend;
                await init.call(initModule, 'winzapp_call_action');
                const emitter = initModule?.VoipInitEventEmitter;
                if (
                  emitter?.getIsVoipInited?.() !== true &&
                  emitter?.getDidVoipInitError?.() === true &&
                  typeof initModule?.retryWAWebVoipInitAfterFailure === 'function'
                ) {
                  await initModule.retryWAWebVoipInitAfterFailure();
                }
                if (emitter?.getIsVoipInited?.() === false) {
                  throw new Error('WhatsApp VoIP initializer completed without becoming ready');
                }
              }
            }

            const stack = await getNativeVoipStack();
            if (stack && isVoipInitialized() !== false) return stack;
            lastError = stack
              ? new Error('WhatsApp VoIP connection initialization is pending')
              : new Error('VoIP stack interface is not available');
          } catch (error) {
            lastError = error;
          }
          await delay(180 * (attempt + 1));
        }

        const message = String(lastError?.message || lastError || 'unknown error');
        throw new Error(`WhatsApp VoIP initialization failed: ${message}`);
      };

      const isVoipInitError = (error: any): boolean =>
        String(error?.message || error || '').includes('without successful voipInit');

      const runNativeVoipAction = async (fn: (stack: any) => Promise<any>): Promise<any> => {
        let lastError: any = null;
        const maxAttempts = 8;
        for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
          const stack = await ensureVoipRuntimeReady();
          try {
            return await fn(stack);
          } catch (error) {
            lastError = error;
            if (!isVoipInitError(error) || attempt >= maxAttempts - 1) throw error;
            // The interface object can exist before its worker-side RPC has
            // completed voipInit. Give that lazy backend a bounded window to
            // settle, then reacquire/reinitialize it on the next iteration.
            await delay(Math.min(1500, 300 * (attempt + 1)));
          }
        }
        throw lastError;
      };

      if (action === 'accept') {
        const callId = String(payload.callId || '');
        const call = findCall(callId);
        if (call) {
          const result = await runNativeVoipAction(async (voipStack: any) => {
            if (typeof voipStack?.acceptCall !== 'function') {
              throw new Error('Native VoIP acceptCall is not available');
            }
            await voipStack.acceptCall(true, call?.isVideo === true);
            return { handled: true, via: 'native-voip', call: summarizeCall(call) };
          });
          forgetIncomingCall(callId || callIdOf(call));
          return result;
        }
        const result = await win.WPP.call.accept(callId || undefined);
        forgetIncomingCall(callId);
        return result;
      }

      if (action === 'reject') {
        const callId = String(payload.callId || '');
        const call = findCall(callId);
        if (call) {
          const result = await runNativeVoipAction(async (voipStack: any) => {
            if (typeof voipStack?.rejectCall !== 'function') {
              throw new Error('Native VoIP rejectCall is not available');
            }
            call.userEndedCall = true;
            await voipStack.rejectCall();
            return { handled: true, via: 'native-voip', call: summarizeCall(call) };
          });
          forgetIncomingCall(callId || callIdOf(call));
          return result;
        }
        const reject = win.WPP.call.rejectCall || win.WPP.call.reject;
        if (typeof reject !== 'function') throw new Error('WPP.call.reject is not available');
        const result = await reject(callId || undefined);
        forgetIncomingCall(callId);
        return result;
      }

      if (action === 'end') {
        const requestedCallId = String(payload.callId || '');
        const call = findCall(requestedCallId);
        const handledCallId = requestedCallId || callIdOf(call);
        const result = await runNativeVoipAction(async (voipStack: any) => {
          if (typeof voipStack?.endCall === 'function') {
            if (call) call.userEndedCall = true;
            await voipStack.endCall(2, true);
            return { handled: true, via: 'native-voip', call: call ? summarizeCall(call) : null };
          }
          return win.WPP.call.end();
        });
        forgetIncomingCall(handledCallId);
        return result;
      }

      if (action === 'offer-group') {
        if (payload.isVideo) {
          throw new Error('Video group calls are not supported by WinZapp');
        }
        const participantIds = Array.isArray(payload.participants)
          ? payload.participants.map((value) => String(value || '').trim()).filter(Boolean)
          : [];
        if (participantIds.length < 2) {
          throw new Error('At least two participants are required to start a group voice call');
        }

        const groupJid = String(payload.groupJid || '').trim();
        const useGroupChat =
          payload.useGroupChat === true && groupJid.endsWith('@g.us');

        await ensureVoipRuntimeReady();

        // Probe the real Emscripten/WASM return code. WhatsApp's Web stack
        // intentionally logs non-zero startVoipGroupCall() results but does
        // not return them to callers. On the direct stack the backend API
        // exposes the same WASM module instance, so wrap just this method and
        // leave all behavior/return values unchanged.
        let wasmProbe: any = {
          installed: false,
          earlyHookInstalled: !!win.__winzappEarlyWasmProbeInstalled,
          earlyHookError: String(win.__winzappEarlyWasmProbeError || ''),
          error: '',
          lastStatus: win.__winzappLastStartVoipGroupCallStatus || null,
        };
        try {
          const backendApi = win.require?.('WAWebBackendApi');
          const frontendSendAndReceive = backendApi?.frontendSendAndReceive;
          if (typeof frontendSendAndReceive === 'function') {
            const wasm = await frontendSendAndReceive.call(
              backendApi,
              'initializeVoipWasm'
            );
            if (wasm && typeof wasm.startVoipGroupCall === 'function') {
              if (!wasm.__winzappStartVoipGroupCallProbe) {
                const originalStartVoipGroupCall =
                  wasm.startVoipGroupCall.bind(wasm);
                wasm.startVoipGroupCall = (...args: any[]) => {
                  const status = originalStartVoipGroupCall(...args);
                  const listSize = (value: any) => {
                    try {
                      if (typeof value?.size === 'function') return value.size();
                      if (typeof value?.length === 'number') return value.length;
                    } catch (_) {}
                    return null;
                  };
                  win.__winzappLastStartVoipGroupCallStatus = {
                    at: Date.now(),
                    status,
                    argCount: args.length,
                    pnCount: listSize(args[0]),
                    lidCount: listSize(args[1]),
                    deviceCsvCount: listSize(args[2]),
                    callId: String(args[3] || ''),
                    useVideo: !!args[4],
                    groupJid: String(args[5] || ''),
                    isLightWeight: !!args[6],
                    callFromUi: args[10] ?? null,
                    lobbyEntryPoint: args[11] ?? null,
                  };
                  return status;
                };
                wasm.__winzappStartVoipGroupCallProbe = true;
              }
              wasmProbe.installed = true;
              wasmProbe.earlyHookInstalled =
                !!win.__winzappEarlyWasmProbeInstalled;
              wasmProbe.earlyHookError =
                String(win.__winzappEarlyWasmProbeError || '');
            } else {
              wasmProbe.error = 'initializeVoipWasm returned no startVoipGroupCall function';
            }
          } else {
            wasmProbe.error = 'WAWebBackendApi.frontendSendAndReceive is unavailable';
          }
        } catch (error: any) {
          wasmProbe.error = String(error?.message || error || 'unknown error');
        }

        const callStart = win.require?.('WAWebVoipStartCall');
        if (!callStart) {
          throw new Error('WhatsApp native group-call controller is unavailable');
        }

        // WAWebVoipStackInterfaceWeb.startGroupCall() checks the exported
        // WAWebVoipGatingUtils.isGroupCallingEnabled() immediately before it
        // calls the native/WASM startVoipGroupCall(). WA-JS already patches
        // the AB props, but explicitly validate this last gate here because a
        // false value makes WhatsApp return silently after creating local
        // pending state — exactly the "CALLING but nobody rings" symptom.
        let gating: any = null;
        try {
          gating = win.require?.('WAWebVoipGatingUtils');
        } catch (_) {}
        const gateBefore =
          typeof gating?.isGroupCallingEnabled === 'function'
            ? !!gating.isGroupCallingEnabled()
            : null;
        if (gating && gateBefore === false) {
          gating.isGroupCallingEnabled = () => true;
          if (typeof gating.isWebGroupCallingUsable === 'function') {
            gating.isWebGroupCallingUsable = () => true;
          }
        }
        const gateAfter =
          typeof gating?.isGroupCallingEnabled === 'function'
            ? !!gating.isGroupCallingEnabled()
            : null;
        if (gateAfter === false) {
          throw new Error('WhatsApp Web group calling gate is disabled');
        }

        const functions = win.WPP?.whatsapp?.functions || {};
        const stackForDiagnostics = await getNativeVoipStack();
        let backendForDiagnostics: any = null;
        try {
          const requireBackend =
            functions.requireVoipJsBackend || win.WPP?.whatsapp?.requireVoipJsBackend;
          if (typeof requireBackend === 'function') {
            backendForDiagnostics = await requireBackend();
          }
        } catch (_) {}

        let abProps: any = null;
        let environment: any = null;
        try {
          abProps = win.require?.('WAWebABProps');
        } catch (_) {}
        try {
          environment = win.require?.('WAWebEnvironment');
        } catch (_) {}

        const readAb = (key: string) => {
          try {
            return abProps?.getABPropConfigValue?.(key);
          } catch (_) {
            return undefined;
          }
        };

        const diagnostics: any = {
          voip: {
            isVoipInitialized: isVoipInitialized(),
            stackType: stackForDiagnostics?.type || '',
            stackStartGroupCall: functionDiagnostic(stackForDiagnostics?.startGroupCall),
            stackKeys: stackForDiagnostics ? Object.keys(stackForDiagnostics).sort() : [],
            backendKeys: backendForDiagnostics ? Object.keys(backendForDiagnostics).sort() : [],
            emitterReady:
              backendForDiagnostics?.WAWebVoipInit?.VoipInitEventEmitter?.getIsVoipInited?.(),
            emitterFailed:
              backendForDiagnostics?.WAWebVoipInit?.VoipInitEventEmitter?.getDidVoipInitError?.(),
          },
          environment: {
            isWindows: environment?.isWindows,
            isWeb: environment?.isWeb,
            isGuest: environment?.isGuest,
            userAgent: navigator.userAgent,
            webdriver: navigator.webdriver,
            hardwareConcurrency: navigator.hardwareConcurrency,
            crossOriginIsolated: win.crossOriginIsolated,
          },
          gating: {
            gateBefore,
            gateAfter,
            isWebGroupCallingUsable:
              typeof gating?.isWebGroupCallingUsable === 'function'
                ? !!gating.isWebGroupCallingUsable()
                : null,
            isWebTransportConfigured:
              typeof gating?.isWebTransportConfigured === 'function'
                ? !!gating.isWebTransportConfigured()
                : null,
            isWebTransportEnabled:
              typeof gating?.isWebTransportEnabled === 'function'
                ? !!gating.isWebTransportEnabled()
                : null,
            isCurrentCallGroup:
              typeof gating?.isCurrentCallGroup === 'function'
                ? !!gating.isCurrentCallGroup()
                : null,
          },
          ab: {
            enable_web_calling: readAb('enable_web_calling'),
            enable_web_group_calling: readAb('enable_web_group_calling'),
            enable_web_voip_proxy_and_sctp_workers:
              readAb('enable_web_voip_proxy_and_sctp_workers'),
            winzappDirectVoipStack:
              !!win.require?.('WAWebABProps')?.__winzappDirectVoipStack,
            enable_web_voip_webtransport: readAb('enable_web_voip_webtransport'),
            enable_web_voip_webtransport_group_calls:
              readAb('enable_web_voip_webtransport_group_calls'),
            web_voip_deferred_boot_init: readAb('web_voip_deferred_boot_init'),
          },
          native: {
            fromChat: functionDiagnostic(callStart.startWAWebVoipGroupCallFromChat),
            fromWids: functionDiagnostic(callStart.startWAWebVoipGroupCallFromWids),
          },
          wasmProbe,
          before: callStoreSnapshot(),
          timeline: [],
        };

        const widFactory =
          win.WPP?.whatsapp?.WidFactory ||
          win.Store?.WidFactory ||
          win.require?.('WAWebWidFactory');
        const createWid = widFactory?.createWid;
        if (typeof createWid !== 'function') {
          throw new Error('WhatsApp contact ID factory is not available');
        }

        const callFromUiModule = win.require?.('WAWebWamEnumCallFromUi');
        const lobbyEntryModule = win.require?.('WAWebWamEnumLobbyEntryPointType');
        // WinZapp deliberately uses the participant-picker semantics even
        // when every member was selected. FromChat was observed to abort
        // before remote ringing, while FromWids is the same native route used
        // by WhatsApp's working "New call" multi-person flow.
        const callFromUi =
          callFromUiModule?.CALL_FROM_UI?.GROUP_CHAT_PICKER ?? 24;
        const lobbyEntryPoint =
          lobbyEntryModule?.LOBBY_ENTRY_POINT_TYPE?.NOT_OPENED ?? 5;

        const callStore = getCallStore();
        const previousActiveId = callIdOf(callStore?.activeCall);
        const preexistingIds = new Set(
          getModels(callStore).map((model) => callIdOf(model)).filter(Boolean)
        );

        let via = '';
        if (typeof callStart.startWAWebVoipGroupCallFromWids !== 'function') {
          throw new Error(
            'WhatsApp selected-participant group-call controller is unavailable'
          );
        }

        const queryExistsModule = win.require?.('WAWebQueryExistsJob');
        const queryWidExists = queryExistsModule?.queryWidExists;
        const publicQueryWidExists = win.WPP?.contact?.queryWidExists;
        if (
          typeof queryWidExists !== 'function' &&
          typeof publicQueryWidExists !== 'function'
        ) {
          throw new Error('WhatsApp participant resolver is not available');
        }

        const participantWids = await Promise.all(
          participantIds.map(async (participantId) => {
            const requestedWid = createWid.call(widFactory, participantId);
            if (
              !requestedWid ||
              requestedWid.isGroup?.() ||
              (typeof requestedWid.isUser === 'function' && !requestedWid.isUser())
            ) {
              throw new Error(`Invalid group call participant: ${participantId}`);
            }

            const result =
              typeof queryWidExists === 'function'
                ? await queryWidExists.call(queryExistsModule, requestedWid)
                : await publicQueryWidExists.call(win.WPP.contact, participantId);
            if (!result?.wid && !result?.lid) {
              throw new Error(
                `Group call participant is not registered or reachable: ${participantId}`
              );
            }
            // Keep the phone WID selected by the caller. Current query-exists
            // can return the account's LID as `wid`; passing that back into
            // FromWids makes its native PN/LID conversion start with two LIDs
            // and the local group call loses both remote participants before
            // signaling. The query above remains the reachability check.
            return requestedWid;
          })
        );

        diagnostics.resolvedParticipantWids = participantWids.map((wid) => serializeId(wid));
        diagnostics.requestedGroupJid = groupJid;
        diagnostics.requestedUseGroupChat = useGroupChat;
        diagnostics.routingDecision = 'force-selected-participants';
        const nativeStartedAt = Date.now();
        await callStart.startWAWebVoipGroupCallFromWids(
          participantWids,
          false,
          callFromUi,
          lobbyEntryPoint
        );
        diagnostics.nativeInvocationMs = Date.now() - nativeStartedAt;
        diagnostics.nativePath = 'startWAWebVoipGroupCallFromWids';
        via = 'native-group-wids';

        let startedCall: any = null;
        const startedAt = Date.now();
        while (Date.now() - startedAt < 5000) {
          const current = getCallStore()?.activeCall;
          const activeId = callIdOf(current);
          const state = callStateOf(current);
          if (
            current?.outgoing &&
            current?.isGroup &&
            activeId &&
            activeId !== previousActiveId &&
            !preexistingIds.has(activeId) &&
            state &&
            state !== 'NONE' &&
            state !== 'ENDED' &&
            groupParticipantCountOf(current) >= 2
          ) {
            startedCall = current;
            break;
          }
          await delay(100);
        }

        if (!startedCall) {
          diagnostics.timeline.push({ atMs: Date.now() - startedAt, ...callStoreSnapshot() });
          throw new Error(
            'WhatsApp group-call controller did not create a live outgoing group call'
          );
        }

        // Temporary high-detail diagnostics for the current group-call bug.
        // Keep the samples sparse enough not to hammer CallStore while still
        // showing whether signaling progresses past CALLING.
        diagnostics.timeline.push({ atMs: Date.now() - startedAt, ...callStoreSnapshot() });
        for (const waitMs of [250, 500, 1000, 2000]) {
          await delay(waitMs);
          diagnostics.timeline.push({ atMs: Date.now() - startedAt, ...callStoreSnapshot() });
        }
        diagnostics.wasmProbe.lastStatus =
          win.__winzappLastStartVoipGroupCallStatus || null;

        const finalActiveCall = getCallStore()?.activeCall;
        const finalState = callStateOf(finalActiveCall || startedCall);
        if (
          !finalActiveCall ||
          finalState === 'NONE' ||
          finalState === 'ENDED' ||
          groupParticipantCountOf(finalActiveCall) < 2
        ) {
          // Do not throw inside page.evaluate here. Puppeteer serializes an
          // Error down to message/stack and drops custom diagnostic fields.
          // Return a structured failure envelope so Node can log the complete
          // VoIP/AB/timeline snapshot before converting it into HTTP 500.
          return {
            __winzappGroupCallFailure: true,
            error:
              'WhatsApp aborted the outgoing group call before remote signaling remained active',
            finalCall: finalActiveCall ? summarizeCall(finalActiveCall) : null,
            finalState,
            diagnostics,
          };
        }

        return {
          ...summarizeCall(finalActiveCall),
          via,
          groupJid: useGroupChat ? groupJid : '',
          useGroupChat,
          gateBefore,
          gateAfter,
          callFromUi,
          lobbyEntryPoint,
          diagnostics,
        };
      }

      if (action === 'offer') {
        let call: any = null;
        const storeBeforeOffer = getCallStore();
        const preexistingIds = new Set(
          getModels(storeBeforeOffer).map((model) => callIdOf(model)).filter(Boolean)
        );
        const previousActiveId = callIdOf(storeBeforeOffer?.activeCall);

        for (let attempt = 0; attempt < 3 && !call; attempt += 1) {
          await ensureVoipRuntimeReady();
          const offered = await win.WPP.call.offer(payload.to, { isVideo: !!payload.isVideo });

          // Current WhatsApp Web promotes the real ongoing call through
          // CallStore.activeCall.  The value returned by the legacy collection
          // lookup may point at an older call model, so prefer a newly-active
          // call and only trust the direct return value when it is not stale.
          for (let waitAttempt = 0; waitAttempt < 50 && !call; waitAttempt += 1) {
            const store = getCallStore();
            const active = store?.activeCall;
            const activeId = callIdOf(active);
            if (
              active &&
              isOutgoingOrLiveCall(active) &&
              (!previousActiveId || activeId !== previousActiveId)
            ) {
              call = active;
              break;
            }

            const offeredId = callIdOf(offered);
            if (offered && offeredId && !preexistingIds.has(offeredId)) {
              call = offered;
              break;
            }

            const freshModel = getModels(store).find((model) => {
              const modelId = callIdOf(model);
              return !!modelId && !preexistingIds.has(modelId) && isOutgoingOrLiveCall(model);
            });
            if (freshModel) {
              call = freshModel;
              break;
            }
            await delay(100);
          }
          if (!call && attempt < 2) await delay(300 * (attempt + 1));
        }
        if (!call) throw new Error('WhatsApp did not create an outgoing call model');
        return summarizeCall(call);
      }

      throw new Error(`Unsupported call action: ${action}`);
    },
    { action, payload }
    );
  } catch (error: any) {
    if (action === 'offer-group') {
      logger?.error?.(
        `[${session}] WinZapp group-call browser failure ` +
          JSON.stringify({
            message: String(error?.message || error || ''),
            stack: String(error?.stack || ''),
          })
      );
    }
    throw error;
  }

  if (action === 'offer-group') {
    logger?.info?.(
      `[${session}] WinZapp group-call result ` +
        JSON.stringify(result)
    );
    if (result?.__winzappGroupCallFailure) {
      const error: any = new Error(
        String(
          result?.error ||
            'WhatsApp aborted the outgoing group call before remote signaling remained active'
        )
      );
      error.winzappGroupCallDiagnostics = result?.diagnostics || null;
      throw error;
    }
  }

  return result;
}

function ok(res: Response, response: any) {
  res.status(200).json({ status: 'success', response });
}

function fail(req: Request, res: Response, action: string, error: unknown) {
  req.logger.error(error);
  const diagnostics = (error as any)?.winzappGroupCallDiagnostics;
  if (diagnostics) {
    req.logger.error(
      `[${String((req.client as any)?.session || 'unknown')}] WinZapp group-call diagnostics ` +
        JSON.stringify(diagnostics)
    );
  }
  const message = error instanceof Error ? error.message : String(error);
  res.status(500).json({ status: 'error', message: `Error on ${action}`, error: message });
}

async function installAudioBridge(req: Request): Promise<boolean> {
  const client = req.client as any;
  const installed = await ensureCallMediaBridge(client, req.io, req.logger);
  if (!installed) throw new Error('WinZapp call media bridge is not available');
  return true;
}

async function prepareAudioBridge(req: Request): Promise<boolean> {
  await installAudioBridge(req);
  const enabled = await setCallMediaBridgeActive(req.client as any, true);
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

export async function enableCallAudio(req: Request, res: Response) {
  try {
    ok(res, { enabled: await prepareAudioBridge(req) });
  } catch (error) {
    fail(req, res, 'enableCallAudio', error);
  }
}

export async function rejectCall(req: Request, res: Response) {
  try {
    await installAudioBridge(req);
    await stopAudioBridge(req);
    ok(res, await evaluateWppCall(req, 'reject', req.body || {}));
  } catch (error) {
    fail(req, res, 'rejectCall', error);
  }
}

export async function endCall(req: Request, res: Response) {
  try {
    await installAudioBridge(req);
    await stopAudioBridge(req);
    ok(res, await evaluateWppCall(req, 'end', req.body || {}));
  } catch (error) {
    fail(req, res, 'endCall', error);
  }
}

export async function offerGroupCall(req: Request, res: Response) {
  try {
    const body = req.body || {};
    if (!Array.isArray(body.participants) || body.participants.length < 2) {
      res.status(400).json({
        status: 'error',
        message: 'At least two participants are required!',
      });
      return;
    }
    if (body.isVideo === true) {
      res.status(400).json({ status: 'error', message: 'Video group calls are not supported!' });
      return;
    }
    await prepareAudioBridge(req);
    const result = await evaluateWppCall(req, 'offer-group', body);
    req.logger.info(
      `[${req.params.session}] group call offer result: ${JSON.stringify(result)}`
    );
    ok(res, result);
  } catch (error) {
    await stopAudioBridge(req);
    fail(req, res, 'offerGroupCall', error);
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

export async function callDiagnostics(req: Request, res: Response) {
  try {
    const page = getWhatsappPage(req);
    const response = await page.evaluate(async () => {
      const win = window as any;
      const functions = win.WPP?.whatsapp?.functions || {};
      const conn = win.WPP?.whatsapp?.ConnStore || win.Store?.Conn || win.WPP?.whatsapp?.Conn;
      let backend: any = null;
      let backendError = '';
      try {
        backend = await functions.requireVoipJsBackend?.();
      } catch (error: any) {
        backendError = String(error?.stack || error?.message || error);
      }
      const stack = await functions.getVoipStackInterface?.().catch?.((error: any) => {
        backendError ||= String(error?.stack || error?.message || error);
        return null;
      });
      const permission = async (name: string) => {
        try {
          return (await navigator.permissions.query({ name } as any)).state;
        } catch (error: any) {
          return `error:${error?.message || error}`;
        }
      };
      return {
        userAgent: navigator.userAgent,
        webdriver: navigator.webdriver,
        secureContext: window.isSecureContext,
        mediaDevices: !!navigator.mediaDevices,
        getUserMedia: typeof navigator.mediaDevices?.getUserMedia,
        audioPermission: await permission('microphone'),
        videoPermission: await permission('camera'),
        rtcPeerConnection: typeof win.RTCPeerConnection,
        audioContext: typeof (win.AudioContext || win.webkitAudioContext),
        worker: typeof win.Worker,
        sharedWorker: typeof win.SharedWorker,
        webAssembly: typeof win.WebAssembly,
        crossOriginIsolated: win.crossOriginIsolated,
        requireBackend: typeof functions.requireVoipJsBackend,
        backendKeys: backend ? Object.keys(backend).sort() : [],
        backendError,
        initFunction: typeof (backend?.WAWebVoipInit?.initWAWebVoip || backend?.initWAWebVoip),
        stack: !!stack,
        stackMethods: stack ? Object.keys(stack).sort() : [],
        stackVoipInitArity: stack?.voipInit?.length,
        stackVoipInitSource: stack?.voipInit ? String(stack.voipInit).slice(0, 1200) : '',
        backendInitArity: (backend?.WAWebVoipInit?.initWAWebVoip || backend?.initWAWebVoip)?.length,
        backendInitSource: (backend?.WAWebVoipInit?.initWAWebVoip || backend?.initWAWebVoip)
          ? String(backend?.WAWebVoipInit?.initWAWebVoip || backend?.initWAWebVoip).slice(0, 1200)
          : '',
        emitterReady: backend?.WAWebVoipInit?.VoipInitEventEmitter?.getIsVoipInited?.(),
        emitterFailed: backend?.WAWebVoipInit?.VoipInitEventEmitter?.getDidVoipInitError?.(),
        callMediaBridge: (() => {
          const bridge = win.__winzappCallMediaBridge;
          return bridge ? {
            enabled: !!bridge.enabled,
            micFramesPushed: bridge.micFramesPushed || 0,
            micBytesPushed: bridge.micBytesPushed || 0,
            micSamplesConsumed: bridge.micSamplesConsumed || 0,
            micTrackLive: bridge.micDestination?.stream?.getAudioTracks?.()[0]?.readyState === 'live',
          } : null;
        })(),
        retryFunction: typeof backend?.WAWebVoipInit?.retryWAWebVoipInitAfterFailure,
        isVoipInitialized: conn?.isVoipInitialized,
        connectionKeys: conn ? Object.keys(conn).filter((key) => /voip|call/i.test(key)).sort() : [],
      };
    });
    ok(res, response);
  } catch (error) {
    fail(req, res, 'callDiagnostics', error);
  }
}
