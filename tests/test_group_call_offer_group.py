"""An incoming group call is never shown as the caller's private call.

Two paths lost the group on the WPPConnect side. The ring: emitIncomingOffer
waited 1 s for CallModel.groupJid and then announced the call without it. The
record: WhatsApp Web writes the call log of a call that ended for us with
{isGroup: false} unless the reason is group_call_ended
(WAWebVoipActionWebHandleIncomingSignalingMessage, read over CDP on
2026-10-28), so a group call that rang out was filed in the caller's private
chat. createSessionUtil.ts keeps each offer's group-jid by call id
(WAWebHandleVoipCall.handleCall) and hands it to both. This runs that page
code verbatim under Node with fake WhatsApp Web modules.
"""
import json
import re
import shutil
import subprocess
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SESSION_UTIL = ROOT / "client" / "api_patches" / "src" / "util" / "createSessionUtil.ts"


def _node():
    bundled = ROOT / "client" / "node" / "node.exe"
    if bundled.exists():
        return str(bundled)
    return shutil.which("node")


def _block() -> str:
    src = SESSION_UTIL.read_text(encoding="utf-8")
    start = src.index("          const rememberOfferedGroup = (stanza: any) => {")
    end_marker = "          if (!installGroupCallFixes()) {"
    end = src.index("          }\n", src.index(end_marker)) + len("          }\n")
    block = src[start:end].replace("(window as any)", "window")
    block = block.replace("(wrapped as any)", "wrapped").replace(" as string", "")
    block = block.replace("(): boolean =>", "() =>")
    block = re.sub(r"\((\w+): any\)", r"(\1)", block)
    block = re.sub(r"\((\w+): string\): any =>", r"(\1) =>", block)
    block = block.replace("function (this: any, stanza: any, ...rest: any[])",
                          "function (stanza, ...rest)")
    block = block.replace("function (this: any, details: any, ...rest: any[])",
                          "function (details, ...rest)")
    return block


def test_the_group_of_an_offer_is_read_where_the_model_lacks_it():
    src = SESSION_UTIL.read_text(encoding="utf-8")
    group_of = src[src.index("          const groupJidOf = (call: any) =>"):]
    group_of = group_of[:group_of.index(");") + 2]
    assert "offeredGroups.get(callIdOf(call))" in group_of
    assert src.index("const offeredGroups = new Map") < src.index("const groupJidOf = (call: any)")


_HARNESS = r"""
const offeredGroups = new Map();
const callIdOf = (c) => String(c?.id || '');
const models = new Map();
const findCall = (id) => models.get(id) || null;
const groupJidOf = (call) => String(call?.groupJid?.toString?.() || offeredGroups.get(callIdOf(call)) || '');
const handled = [], notices = [];
const modules = {
  WAWebWidFactory: { createWid: (s) => ({ wid: s, toString() { return s; } }) },
};
let loaded = false;
const voip = {
  WAWebHandleVoipCall: { handleCall: (stanza) => { handled.push(stanza); return 'ACK'; } },
  WAWebVoipActionWriteCallLogOfferNotice: { generateCallLogOfferNotice: (d) => { notices.push(d); } },
};
let retryFn = null, cleared = false;
const window = {
  require: (name) => {
    if (modules[name]) return modules[name];
    if (loaded && voip[name]) return voip[name];
    throw new Error('not loaded ' + name);
  },
  setInterval: (fn) => { retryFn = fn; return 1; },
  clearInterval: () => { cleared = true; },
};
BLOCK
const out = {};
out.installed_before_load = retryFn !== null;
loaded = true;
retryFn();
out.retry_cleared = cleared;
out.second_install_keeps_one_wrapper = installGroupCallFixes() &&
  voip.WAWebHandleVoipCall.handleCall.__winzappGroups === true;
const gid = { toString() { return '1203@g.us'; } };
out.ack = voip.WAWebHandleVoipCall.handleCall({ tag: 'call', content: [
  { tag: 'offer', attrs: { 'call-id': 'G1', 'group-jid': gid } }] });
voip.WAWebHandleVoipCall.handleCall({ tag: 'call', content: [
  { tag: 'offer', attrs: { 'call-id': 'P1' } }] });
out.handled = handled.length;
out.remembered = offeredGroups.get('G1') || null;
out.private_remembered = offeredGroups.has('P1');
const notice = voip.WAWebVoipActionWriteCallLogOfferNotice.generateCallLogOfferNotice;
notice({ callId: 'G1', isGroup: false, callOutcome: 'Missed' });
notice({ callId: 'P1', isGroup: false, callOutcome: 'Missed' });
models.set('G2', { id: 'G2', groupJid: { toString() { return '1299@g.us'; }, model: true } });
notice({ callId: 'G2', isGroup: false });
notice({ callId: 'G3', isGroup: true, groupJid: 'kept' });
out.notices = notices.map((d) => ({ id: d.callId, isGroup: d.isGroup,
  group: d.groupJid ? String(d.groupJid) : null, model: !!d.groupJid?.model,
  outcome: d.callOutcome || null }));
for (let i = 0; i < 250; i++) voip.WAWebHandleVoipCall.handleCall({ content: [
  { attrs: { 'call-id': 'X' + i, 'group-jid': '9' + i + '@g.us' } }] });
out.bounded = offeredGroups.size;
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def outcomes(tmp_path_factory):
    node = _node()
    if not node:
        pytest.skip("no Node runtime available")
    script = tmp_path_factory.mktemp("groups") / "groups.js"
    script.write_text(_HARNESS.replace("BLOCK", _block()), encoding="utf-8")
    run = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout.strip().splitlines()[-1])


def test_the_fix_installs_once_the_voip_modules_load(outcomes):
    assert outcomes["installed_before_load"] and outcomes["retry_cleared"]
    assert outcomes["second_install_keeps_one_wrapper"]


def test_the_offer_s_group_is_kept_and_call_handling_goes_on(outcomes):
    assert outcomes["ack"] == "ACK" and outcomes["handled"] == 2
    assert outcomes["remembered"] == "1203@g.us" and not outcomes["private_remembered"]
    assert outcomes["bounded"] <= 200


def test_a_missed_group_call_is_recorded_in_its_group(outcomes):
    notices = {n["id"]: n for n in outcomes["notices"]}
    assert notices["G1"] == {"id": "G1", "isGroup": True, "group": "1203@g.us",
                             "model": False, "outcome": "Missed"}
    assert notices["P1"]["isGroup"] is False and notices["P1"]["group"] is None
    # the CallModel's own Wid is preferred when it has one
    assert notices["G2"]["isGroup"] is True and notices["G2"]["model"] is True
    assert notices["G3"] == {"id": "G3", "isGroup": True, "group": "kept",
                             "model": False, "outcome": None}
