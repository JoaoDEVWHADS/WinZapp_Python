import { Socket } from 'socket.io';

import { clientsArray } from './sessionUtil';

const MAX_AUDIO_FRAME_BYTES = 64 * 1024;
const MAX_MIC_QUEUE_FRAMES = 75;
const micQueues = new Map<string, Buffer[]>();
const micDraining = new Set<string>();

function installCallMediaBridgeInPage(): boolean {
  const win = window as any;
  if (win.__winzappCallMediaBridge?.version === 1) return true;
  if (!navigator.mediaDevices?.getUserMedia || !win.RTCPeerConnection) return false;

  const AudioContextCtor = win.AudioContext || win.webkitAudioContext;
  if (!AudioContextCtor) return false;

  const state: any = {
    version: 1,
    enabled: false,
    context: null,
    micDestination: null,
    micProcessor: null,
    micQueue: [] as Float32Array[],
    micOffset: 0,
    remotePipelines: new Map<string, any>(),
    micFramesPushed: 0,
    micBytesPushed: 0,
    micSamplesConsumed: 0,
  };

  const ensureContext = () => {
    if (!state.context || state.context.state === 'closed') {
      state.context = new AudioContextCtor({
        latencyHint: 'interactive',
        sampleRate: 48000,
      });
    }
    if (state.context.state === 'suspended') {
      state.context.resume().catch(() => undefined);
    }
    return state.context;
  };

  const decodePcm16 = (base64: string): Float32Array => {
    const binary = atob(base64 || '');
    const frames = Math.floor(binary.length / 2);
    const samples = new Float32Array(frames);
    for (let i = 0; i < frames; i += 1) {
      const lo = binary.charCodeAt(i * 2);
      const hi = binary.charCodeAt(i * 2 + 1);
      let value = (hi << 8) | lo;
      if (value & 0x8000) value -= 0x10000;
      samples[i] = Math.max(-1, Math.min(1, value / 32768));
    }
    return samples;
  };

  const encodePcm16 = (samples: Float32Array): string => {
    const bytes = new Uint8Array(samples.length * 2);
    for (let i = 0; i < samples.length; i += 1) {
      const clipped = Math.max(-1, Math.min(1, samples[i] || 0));
      const value = clipped < 0 ? Math.round(clipped * 32768) : Math.round(clipped * 32767);
      bytes[i * 2] = value & 0xff;
      bytes[i * 2 + 1] = (value >> 8) & 0xff;
    }
    let binary = '';
    const step = 0x8000;
    for (let i = 0; i < bytes.length; i += step) {
      binary += String.fromCharCode(...bytes.subarray(i, i + step));
    }
    return btoa(binary);
  };

  const ensureMicTrack = () => {
    const context = ensureContext();
    if (state.micDestination?.stream?.getAudioTracks?.()[0]?.readyState === 'live') {
      return state.micDestination.stream.getAudioTracks()[0];
    }

    const processor = context.createScriptProcessor(1024, 0, 1);
    const destination = context.createMediaStreamDestination();
    processor.onaudioprocess = (event: AudioProcessingEvent) => {
      const output = event.outputBuffer.getChannelData(0);
      output.fill(0);
      if (!state.enabled) return;

      let written = 0;
      while (written < output.length && state.micQueue.length) {
        const head: Float32Array = state.micQueue[0];
        const available = head.length - state.micOffset;
        const take = Math.min(output.length - written, available);
        output.set(head.subarray(state.micOffset, state.micOffset + take), written);
        written += take;
        state.micOffset += take;
        if (state.micOffset >= head.length) {
          state.micQueue.shift();
          state.micOffset = 0;
        }
      }
      state.micSamplesConsumed += written;
    };
    processor.connect(destination);
    // A zero-input ScriptProcessor is not scheduled reliably by Chromium
    // unless it also has an audible graph sink. Keep that sink muted; the
    // MediaStreamDestination remains the only call track source.
    const schedulerSink = context.createGain();
    schedulerSink.gain.value = 0;
    processor.connect(schedulerSink);
    schedulerSink.connect(context.destination);
    state.micProcessor = processor;
    state.micDestination = destination;
    return destination.stream.getAudioTracks()[0];
  };

  state.enable = () => {
    state.enabled = true;
    ensureMicTrack();
    ensureContext().resume().catch(() => undefined);
    return true;
  };

  state.pushMicrophone = (base64: string) => {
    if (!state.enabled) return;
    ensureContext();
    const samples = decodePcm16(base64);
    if (!samples.length) return;
    state.micQueue.push(samples);
    state.micFramesPushed += 1;
    state.micBytesPushed += Math.floor(base64.length * 3 / 4);
    while (state.micQueue.length > 75) state.micQueue.shift();
  };

  state.reset = () => {
    state.enabled = false;
    state.micQueue.length = 0;
    state.micOffset = 0;
    for (const pipeline of state.remotePipelines.values()) {
      try { pipeline.source.disconnect(); } catch (_) {}
      try { pipeline.processor.disconnect(); } catch (_) {}
      try { pipeline.sink.disconnect(); } catch (_) {}
    }
    state.remotePipelines.clear();
  };

  const attachRemoteTrack = (track: MediaStreamTrack) => {
    if (!track || track.kind !== 'audio') return;
    const id = track.id || String(Math.random());
    if (state.remotePipelines.has(id)) return;

    const context = ensureContext();
    const stream = new MediaStream([track]);
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(1024, 1, 1);
    const sink = context.createGain();
    sink.gain.value = 0;
    processor.onaudioprocess = (event: AudioProcessingEvent) => {
      if (!state.enabled) return;
      const input = event.inputBuffer.getChannelData(0);
      const callback = win.__winzappOnCallRemoteAudio;
      if (typeof callback === 'function' && input.length) {
        callback(encodePcm16(input), context.sampleRate).catch?.(() => undefined);
      }
      event.outputBuffer.getChannelData(0).fill(0);
    };
    source.connect(processor);
    processor.connect(sink);
    sink.connect(context.destination);
    state.remotePipelines.set(id, { source, processor, sink, track });
    track.addEventListener('ended', () => {
      const pipeline = state.remotePipelines.get(id);
      if (!pipeline) return;
      try { pipeline.source.disconnect(); } catch (_) {}
      try { pipeline.processor.disconnect(); } catch (_) {}
      try { pipeline.sink.disconnect(); } catch (_) {}
      state.remotePipelines.delete(id);
    }, { once: true });
  };

  const attachPeerConnection = (pc: RTCPeerConnection) => {
    const tagged = pc as any;
    if (tagged.__winzappCallMediaAttached) return pc;
    tagged.__winzappCallMediaAttached = true;
    pc.addEventListener('track', (event) => attachRemoteTrack(event.track));
    // WhatsApp can obtain a stream before the bridge wrapper is installed and
    // then add that stream later. Replace only outgoing audio at the final
    // WebRTC boundary so Python PCM is always the media source.
    try {
      const nativeAddTrack = pc.addTrack.bind(pc);
      tagged.__winzappNativeAddTrack = nativeAddTrack;
      pc.addTrack = ((track: MediaStreamTrack, ...streams: MediaStream[]) => {
        if (state.enabled && track?.kind === 'audio') {
          const micTrack = ensureMicTrack().clone();
          const micStream = new MediaStream([micTrack]);
          return nativeAddTrack(micTrack, micStream);
        }
        return nativeAddTrack(track, ...streams);
      }) as typeof pc.addTrack;
    } catch (_) {}
    return pc;
  };

  const NativeRTCPeerConnection = win.RTCPeerConnection;
  try {
    const nativeSetRemoteDescription = NativeRTCPeerConnection.prototype.setRemoteDescription;
    NativeRTCPeerConnection.prototype.setRemoteDescription = function (...args: any[]) {
      attachPeerConnection(this);
      return nativeSetRemoteDescription.apply(this, args);
    };
  } catch (_) {}
  try {
    const WrappedRTCPeerConnection = new Proxy(NativeRTCPeerConnection, {
      construct(target, args) {
        return attachPeerConnection(Reflect.construct(target, args));
      },
    });
    WrappedRTCPeerConnection.prototype = NativeRTCPeerConnection.prototype;
    win.RTCPeerConnection = WrappedRTCPeerConnection;
    if (win.webkitRTCPeerConnection) win.webkitRTCPeerConnection = WrappedRTCPeerConnection;
  } catch (_) {}

  const nativeGetUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  const permissionResult = (
    permissionName: string,
    stateValue: PermissionState = 'granted'
  ): PermissionStatus => ({
    name: permissionName,
    state: stateValue,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  } as unknown as PermissionStatus);

  try {
    const nativePermissionQuery = navigator.permissions?.query?.bind(navigator.permissions);
    if (nativePermissionQuery) {
      Object.defineProperty(navigator.permissions, 'query', {
        configurable: true,
        writable: true,
        value: async (descriptor: PermissionDescriptor) => {
          const name = String((descriptor as any)?.name || '');
          if (name === 'microphone' || name === 'camera') {
            return permissionResult(name, 'granted');
          }
          return nativePermissionQuery(descriptor);
        },
      });
    }
  } catch (_) {}

  const bridgedGetUserMedia = async (constraints: MediaStreamConstraints = {}) => {
    if (!constraints?.audio) return nativeGetUserMedia(constraints);

    // Never let WhatsApp Web open the physical microphone. Even while the
    // Python call engine is not active, expose a live silent synthetic track so
    // the native VoIP bootstrap can complete without touching audio hardware.
    // Once state.enabled becomes true, Python PCM is written into this track.
    const micTrack = ensureMicTrack().clone();
    if (!constraints.video) return new MediaStream([micTrack]);
    const videoOnly = await nativeGetUserMedia({ video: constraints.video, audio: false });
    videoOnly.addTrack(micTrack);
    return videoOnly;
  };
  try {
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {
      configurable: true,
      writable: true,
      value: bridgedGetUserMedia,
    });
  } catch (_) {
    (navigator.mediaDevices as any).getUserMedia = bridgedGetUserMedia;
  }
  try {
    win.navigator.getUserMedia = (constraints: MediaStreamConstraints, ok: any, fail: any) => {
      bridgedGetUserMedia(constraints).then(ok, fail);
    };
    win.navigator.webkitGetUserMedia = win.navigator.getUserMedia;
  } catch (_) {}

  win.__winzappCallMediaBridge = state;
  return true;
}

function toBuffer(value: any): Buffer | null {
  if (typeof value === 'string') {
    try { return Buffer.from(value, 'base64'); } catch (_) { return null; }
  }
  if (Buffer.isBuffer(value)) return value;
  if (value instanceof Uint8Array) return Buffer.from(value);
  if (Array.isArray(value)) return Buffer.from(value);
  if (value?.type === 'Buffer' && Array.isArray(value.data)) return Buffer.from(value.data);
  return null;
}

export async function ensureCallMediaBridge(client: any, io: any, logger: any): Promise<boolean> {
  const page = client?.waPage || client?.page;
  if (!page) return false;

  try {
    await page.exposeFunction(
      '__winzappOnCallRemoteAudio',
      (base64: string, sampleRate: number) => {
        if (typeof base64 !== 'string' || base64.length > MAX_AUDIO_FRAME_BYTES * 2) return;
        const pcmBytes = Math.floor((base64.length * 3) / 4);
        if (!pcmBytes || pcmBytes > MAX_AUDIO_FRAME_BYTES) return;
        io.emit('call:audio:remote', {
          session: client.session,
          sampleRate: Number(sampleRate) || 48000,
          encoding: 'base64',
          pcm: base64,
        });
      }
    );
  } catch (_) {
    // Puppeteer bindings survive navigation; duplicate registration is expected.
  }

  try {
    if (!(client as any).__winzappCallMediaNewDocumentInstalled) {
      await page.evaluateOnNewDocument(installCallMediaBridgeInPage);
      (client as any).__winzappCallMediaNewDocumentInstalled = true;
    }
    const installed = await page.evaluate(installCallMediaBridgeInPage);
    if (installed) logger?.info?.(`[${client.session}] WinZapp call media bridge ready`);
    return !!installed;
  } catch (error: any) {
    logger?.warn?.(
      `[${client.session}] WinZapp call media bridge unavailable: ${error?.message || error}`
    );
    return false;
  }
}

export async function warmCallVoipRuntime(client: any, logger: any): Promise<boolean> {
  const page = client?.waPage || client?.page;
  if (!page) return false;

  const pending = (client as any).__winzappVoipWarmupPromise;
  if (pending) return pending;

  const warmup = (async (): Promise<boolean> => {
    try {
      const result = await page.evaluate(async () => {
        const win = window as any;
        const delay = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));
        let lastError = '';

        for (let attempt = 0; attempt < 10; attempt += 1) {
          try {
            const enable = win.WPP?.call?.enableCallInterface;
            if (typeof enable !== 'function') {
              lastError = 'WPP.call.enableCallInterface is not ready';
              await delay(250);
              continue;
            }
            await enable();

            const functions = win.WPP?.whatsapp?.functions || {};
            const requireBackend =
              functions.requireVoipJsBackend || win.WPP?.whatsapp?.requireVoipJsBackend;
            if (typeof requireBackend === 'function') {
              const backend = await requireBackend();
              const init = backend?.WAWebVoipInit?.initWAWebVoip || backend?.initWAWebVoip;
              if (typeof init === 'function') {
                const initModule = backend?.WAWebVoipInit || backend;
                await init.call(initModule, 'winzapp_session_warmup');
                const emitter = initModule?.VoipInitEventEmitter;
                if (
                  emitter?.getIsVoipInited?.() !== true &&
                  emitter?.getDidVoipInitError?.() === true &&
                  typeof initModule?.retryWAWebVoipInitAfterFailure === 'function'
                ) {
                  await initModule.retryWAWebVoipInitAfterFailure();
                }
                if (emitter?.getIsVoipInited?.() === false) {
                  lastError = 'WhatsApp VoIP initializer did not become ready';
                  await delay(250 * (attempt + 1));
                  continue;
                }
              }
            }

            const getStack =
              functions.getVoipStackInterface || win.WPP?.whatsapp?.getVoipStackInterface;
            if (typeof getStack !== 'function') {
              lastError = 'getVoipStackInterface is not ready';
              await delay(250);
              continue;
            }
            const stack = await getStack();
            if (stack) {
              // WA-JS exposes the stack before WhatsApp's worker-side
              // initialization has completed.  The connection model is the
              // only public readiness signal in newer builds; accepting the
              // stack object alone causes RPC attempted without successful
              // voipInit during the first call.
              const conn =
                win.WPP?.whatsapp?.ConnStore ||
                win.Store?.Conn ||
                win.WPP?.whatsapp?.Conn;
              if (conn && conn.isVoipInitialized === false) {
                lastError = 'WhatsApp VoIP connection initialization is pending';
                await delay(250 * (attempt + 1));
                continue;
              }
              return {
                ready: true,
                acceptCall: typeof stack.acceptCall === 'function',
                rejectCall: typeof stack.rejectCall === 'function',
                endCall: typeof stack.endCall === 'function',
              };
            }
            lastError = 'VoIP stack interface returned no value';
          } catch (error: any) {
            lastError = String(error?.message || error || 'unknown error');
          }
          await delay(250 * (attempt + 1));
        }

        return { ready: false, error: lastError };
      });

      if (result?.ready) {
        logger?.info?.(
          `[${client.session}] WinZapp VoIP runtime warmed ` +
            `(accept=${!!result.acceptCall}, reject=${!!result.rejectCall}, end=${!!result.endCall})`
        );
        return true;
      }
      logger?.warn?.(
        `[${client.session}] WinZapp VoIP runtime warmup incomplete: ${result?.error || 'unknown error'}`
      );
      return false;
    } catch (error: any) {
      logger?.warn?.(
        `[${client.session}] WinZapp VoIP runtime warmup failed: ${error?.message || error}`
      );
      return false;
    }
  })();

  (client as any).__winzappVoipWarmupPromise = warmup;
  try {
    return await warmup;
  } finally {
    if ((client as any).__winzappVoipWarmupPromise === warmup) {
      delete (client as any).__winzappVoipWarmupPromise;
    }
  }
}

export async function setCallMediaBridgeActive(client: any, active: boolean): Promise<boolean> {
  const page = client?.waPage || client?.page;
  if (!page) return false;
  try {
    return !!(await page.evaluate((activeInPage: boolean) => {
      const bridge = (window as any).__winzappCallMediaBridge;
      if (!bridge) return false;
      if (activeInPage) return !!bridge.enable?.();
      bridge.reset?.();
      return true;
    }, active));
  } catch (_) {
    return false;
  }
}

async function drainMicrophoneQueue(session: string, logger: any): Promise<void> {
  if (micDraining.has(session)) return;
  micDraining.add(session);
  try {
    const queue = micQueues.get(session);
    while (queue?.length) {
      const client: any = (clientsArray as any)[session];
      const page = client?.waPage || client?.page;
      if (!page) {
        queue.length = 0;
        break;
      }
      const frame = queue.shift();
      if (!frame) continue;
      const base64 = frame.toString('base64');
      try {
        await page.evaluate((payload: string) => {
          const bridge = (window as any).__winzappCallMediaBridge;
          bridge?.pushMicrophone?.(payload);
        }, base64);
      } catch (error: any) {
        logger?.debug?.(
          `[${session}] call microphone frame dropped: ${error?.message || error}`
        );
      }
    }
  } finally {
    micDraining.delete(session);
  }
}

export function registerCallAudioSocket(socket: Socket, logger: any): void {
  socket.on('call:audio:mic', (payload: any) => {
    const session = String(payload?.session || '');
    const pcm =
      payload?.encoding === 'base64' && typeof payload?.pcm === 'string'
        ? Buffer.from(payload.pcm, 'base64')
        : toBuffer(payload?.pcm);
    if (!session || !pcm?.length || pcm.length > MAX_AUDIO_FRAME_BYTES) return;
    if (!(clientsArray as any)[session]) return;
    const queue = micQueues.get(session) || [];
    queue.push(pcm);
    while (queue.length > MAX_MIC_QUEUE_FRAMES) queue.shift();
    micQueues.set(session, queue);
    void drainMicrophoneQueue(session, logger);
  });

  socket.on('call:audio:stop', (payload: any) => {
    const session = String(payload?.session || '');
    if (!session) return;
    micQueues.delete(session);
    const client: any = (clientsArray as any)[session];
    const page = client?.waPage || client?.page;
    page
      ?.evaluate(() => (window as any).__winzappCallMediaBridge?.reset?.())
      .catch(() => undefined);
  });
}
