from pathlib import Path

ROOT = Path.cwd()


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding='utf-8')


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding='utf-8')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise SystemExit(f'missing expected block: {label}')
    return text.replace(old, new, 1)


def insert_before(text: str, marker: str, insert: str, label: str) -> str:
    if insert.strip() in text:
        return text
    if marker not in text:
        raise SystemExit(f'missing marker: {label}')
    return text.replace(marker, insert + marker, 1)


# Python side: keep group_jid/useGroupChat instead of losing the real group context.
path = 'client/main.py'
text = read(path)
text = replace_once(
    text,
    '    def start_group_voice_call(\n        self, group_jid: str, participant_jids: list[str], name: str = ""\n    ):\n',
    '    def start_group_voice_call(\n        self, group_jid: str, participant_jids: list[str], name: str = "",\n        *, full_group_selected: bool = False\n    ):\n',
    'start_group_voice_call signature',
)
text = replace_once(
    text,
    '                        {"participants": participants, "isVideo": False},\n',
    '                        {\n                            "participants": participants,\n                            "groupJid": group_jid,\n                            "useGroupChat": bool(full_group_selected),\n                            "isVideo": False,\n                        },\n',
    'group offer payload',
)
write(path, text)

path = 'client/ui/conversations.py'
text = read(path)
text = replace_once(
    text,
    '        self.main_window.start_group_voice_call(group_jid, selected, group_name)\n',
    '        self.main_window.start_group_voice_call(\n            group_jid, selected, group_name, full_group_selected=len(selected) == len(candidates)\n        )\n',
    'group call picker call site',
)
write(path, text)

# Node side: if the user selected the whole real group, use WhatsApp Web's
# ChatModel group-call path. Keep WID-list calls only for ad-hoc subsets.
path = 'client/api_patches/src/controller/callController.ts'
text = read(path)
text = replace_once(
    text,
    '  participants?: string[];\n};\n',
    '  participants?: string[];\n  groupJid?: string;\n  useGroupChat?: boolean;\n};\n',
    'CallActionPayload group fields',
)
helper = """      const groupJidOf = (call: any): string => serializeId(\n        call?.groupJid ||\n        call?.group?.id ||\n        call?.groupWid ||\n        call?.groupMetadata?.id ||\n        call?.get?.('groupJid') ||\n        call?.get?.('groupWid')\n      );\n\n"""
text = insert_before(text, '      const summarizeCall = (call: any) => ({\n', helper, 'groupJidOf helper')
text = replace_once(
    text,
    '        peerJid: peerJidOf(call),\n        state: callStateOf(call),\n',
    '        peerJid: peerJidOf(call),\n        groupJid: groupJidOf(call),\n        state: callStateOf(call),\n',
    'summary groupJid field',
)
text = replace_once(
    text,
    "        if (participantIds.length < 2) {\n          throw new Error('At least two participants are required to start a group voice call');\n        }\n\n        await ensureVoipRuntimeReady();\n",
    "        if (participantIds.length < 2) {\n          throw new Error('At least two participants are required to start a group voice call');\n        }\n        const requestedGroupJid = String(payload.groupJid || '').trim();\n        const useGroupChat = !!payload.useGroupChat && requestedGroupJid.endsWith('@g.us');\n\n        await ensureVoipRuntimeReady();\n",
    'group payload extraction',
)
start = text.find("        const callStart = win.require?.('WAWebVoipStartCall');\n", text.find("      if (action === 'offer-group')"))
end = text.find("\n      }\n\n      if (action === 'offer') {", start)
if start == -1 or end == -1:
    raise SystemExit('could not locate offer-group call controller block')
new_block = r'''        const callStart = win.require?.('WAWebVoipStartCall');
        if (!callStart) {
          throw new Error(
            'Group WhatsApp calls are not supported by this WhatsApp Web version: ' +
            'no internal call controller was detected'
          );
        }

        const findGroupChat = async (): Promise<any> => {
          if (!requestedGroupJid) return null;
          const groupWid = createWid.call(widFactory, requestedGroupJid);
          const keys = [groupWid, requestedGroupJid, groupWid?._serialized].filter(Boolean);
          const collections = [
            win.WPP?.whatsapp?.ChatStore,
            win.Store?.Chat,
            win.require?.('WAWebChatCollection')?.ChatCollection,
            win.require?.('WAWebChatCollection')?.default,
            win.require?.('WAWebChatCollection'),
          ].filter(Boolean);

          for (const collection of collections) {
            for (const key of keys) {
              try {
                const chat = collection?.get?.(key);
                if (chat) return chat;
              } catch (_) {}
            }
            try {
              const models = collection?.getModelsArray?.() || collection?.models || collection?._models || [];
              const chat = Array.isArray(models)
                ? models.find((model: any) => serializeId(model?.id) === requestedGroupJid)
                : null;
              if (chat) return chat;
            } catch (_) {}
          }

          const publicGet = win.WPP?.chat?.get;
          if (typeof publicGet === 'function') {
            try {
              const chat = await publicGet.call(win.WPP.chat, requestedGroupJid);
              if (Array.isArray(chat)) return chat[0] || null;
              return chat || null;
            } catch (_) {}
          }
          return null;
        };

        const callStore = getCallStore();
        const previousActiveId = callIdOf(callStore?.activeCall);
        const preexistingIds = new Set(
          getModels(callStore).map((model) => callIdOf(model)).filter(Boolean)
        );

        const waitForFreshOutgoingCall = async (timeoutMs: number): Promise<any> => {
          const startedAt = Date.now();
          while (Date.now() - startedAt < timeoutMs) {
            const call = getCallStore()?.activeCall;
            const activeId = callIdOf(call);
            const state = callStateOf(call);
            if (
              call?.outgoing &&
              activeId &&
              activeId !== previousActiveId &&
              !preexistingIds.has(activeId) &&
              state &&
              state !== 'NONE' &&
              state !== 'ENDED'
            ) {
              return call;
            }
            await delay(100);
          }
          return null;
        };

        // For the whole real group, follow WhatsApp Web's own group-call path:
        // start from the ChatModel. The WID-list path creates an ad-hoc group
        // call and can produce isGroup=true but hasGroup=false.
        if (useGroupChat && typeof callStart?.startWAWebVoipGroupCallFromChat === 'function') {
          const groupChat = await findGroupChat();
          if (!groupChat) {
            throw new Error(`WhatsApp group chat model was not found for ${requestedGroupJid}`);
          }
          await callStart.startWAWebVoipGroupCallFromChat(groupChat, false);
          const call = await waitForFreshOutgoingCall(5000);
          if (call) {
            return {
              ...summarizeCall(call),
              isGroup: true,
              groupJid: groupJidOf(call) || requestedGroupJid,
              via: 'native-group-chat',
            };
          }
          throw new Error('Outgoing WhatsApp group chat call did not create a live active call');
        }

        if (typeof callStart?.startWAWebVoipGroupCallFromWids !== 'function') {
          throw new Error(
            'Group WhatsApp calls are not supported by this WhatsApp Web version: ' +
            'no supported internal call controller was detected'
          );
        }

        await callStart.startWAWebVoipGroupCallFromWids(participantWids, false);
        const directCall = await waitForFreshOutgoingCall(2500);
        if (directCall) {
          return { ...summarizeCall(directCall), via: 'native-group-wids' };
        }

        if (typeof callStart?.startWAWebVoipCall !== 'function') {
          throw new Error(
            'Direct group call stalled and the 1:1 WhatsApp call fallback is unavailable'
          );
        }
        if (typeof callStart?.inviteToCall !== 'function') {
          throw new Error(
            'Direct group call stalled and WhatsApp inviteToCall fallback is unavailable'
          );
        }

        const callFromUiModule = win.require?.('WAWebWamEnumCallFromUi');
        const callFromUi = callFromUiModule?.CALL_FROM_UI?.CONVERSATION;
        await callStart.startWAWebVoipCall(participantWids[0], false, callFromUi);
        const seedCall = await waitForFreshOutgoingCall(5000);
        if (!seedCall) {
          throw new Error(
            'Direct group call stalled and the 1:1 fallback did not create a live outgoing call'
          );
        }

        for (const participantWid of participantWids.slice(1)) {
          await callStart.inviteToCall(participantWid);
          await delay(150);
        }

        return {
          ...summarizeCall(seedCall),
          isGroup: true,
          via: 'one-to-one-plus-invites',
        };'''
text = text[:start] + new_block + text[end:]
write(path, text)

path = 'tests/test_group_voice_call_logic.py'
text = read(path)
text = replace_once(
    text,
    '    assert \'{"participants": participants, "isVideo": False}\' in source\n',
    '    assert \'"groupJid": group_jid\' in source\n    assert \'"useGroupChat": bool(full_group_selected)\' in source\n    assert \'"isVideo": False\' in source\n',
    'group voice call payload test',
)
write(path, text)

path = 'tests/test_group_voice_call_ui.py'
text = read(path)
text = replace_once(
    text,
    '    assert "self.main_window.start_group_voice_call(group_jid, selected, group_name)" in source\n',
    '    assert "full_group_selected=len(selected) == len(candidates)" in source\n',
    'group voice call UI test',
)
write(path, text)

path = 'tests/test_call_control_api_patch.py'
text = read(path)
if 'test_group_voice_call_can_start_from_real_group_chat' not in text:
    text += '''\n\ndef test_group_voice_call_can_start_from_real_group_chat():\n    controller = _source("client/api_patches/src/controller/callController.ts")\n\n    assert "groupJid?: string" in controller\n    assert "useGroupChat?: boolean" in controller\n    assert "const groupJidOf =" in controller\n    assert "requestedGroupJid.endsWith('@g.us')" in controller\n    assert "startWAWebVoipGroupCallFromChat(groupChat, false)" in controller\n    assert "via: 'native-group-chat'" in controller\n    assert "via: 'native-group-wids'" in controller\n    assert "groupJid: groupJidOf(call) || requestedGroupJid" in controller\n'''
write(path, text)
