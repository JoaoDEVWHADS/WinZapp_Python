"""Run the shipped Node controller and sampled readback on synthetic pages."""
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="Node required for offline controller")


def run(world):
    util = (ROOT / "client/api_patches/src/util/onlinePresenceDiagnostics.ts").read_text(encoding="utf-8")
    util = util.replace("export ", "").replace("WeakMap<object, number>", "WeakMap").replace(": any", "")
    controller = (ROOT / "client/api_patches/src/controller/sessionController.ts").read_text(encoding="utf-8")
    controller = "async function setOnlinePresence(" + controller.split("export async function setOnlinePresence(", 1)[1].split("\nexport async function", 1)[0]
    controller = controller.replace("req: Request", "req").replace("res: Response", "res")
    harness = r"""
const vm = require('vm');
const input = JSON.parse(process.argv[1]), w = input.world;
const logs = [], calls = [], reads = [];
const window = { WPP: w.noWpp ? null : { conn: { markAvailable(){} }, whatsapp: {
  Stream: w.noStream ? null : {available: w.localAvailable ?? false} } } };
const page = { evaluate: expression => {
  reads.push(1);
  if (w.timeout) return new Promise(()=>{});
  if (w.readError) throw Error('PRIVATE_READ_ERROR');
  if (w.readReject) return Promise.reject(Error('PRIVATE_READ_REJECTION'));
  if (w.rawRuntime) return Promise.resolve(w.rawRuntime);
  return Promise.resolve(vm.runInNewContext(expression, {window}));
}};
const req = { headers: w.headers || {}, body: w.body || {isOnline: w.online ?? false},
  logger: {info: text => {if(w.logError) throw Error('PRIVATE_LOG_ERROR');logs.push(text);}}, client: {
    page: w.noPage ? null : page,
    setOnlinePresence: async value => { calls.push(value); if(w.sendError) throw Error('PRIVATE_SEND_ERROR'); return w.native; }
  }};
const res = {code:0, body:null, status(code){this.code=code;return this;},json(body){this.body=body;}};
let now = 1000;
const context = {console, WeakMap, Date:{now:()=>now},
  setTimeout: fn => { if(w.timeout) queueMicrotask(fn); return 1; }, clearTimeout:()=>{}};
vm.createContext(context);
vm.runInContext(input.util + '\n' + input.controller, context);
context.req=req; context.res=res;
(async()=>{
 await vm.runInContext('setOnlinePresence(req,res)',context);
 const first = {code:res.code,body:res.body};
 if(w.repeat) {
   now += w.advance || 0;
   if(w.newClient) req.client={...req.client};
   await vm.runInContext('setOnlinePresence(req,res)',context);
 }
 process.stdout.write(JSON.stringify({first,last:res.body,logs,calls,reads:reads.length}));
})().catch(e=>{process.stderr.write(String(e));process.exitCode=1;});
"""
    result = subprocess.run([NODE, "-e", harness, json.dumps(dict(world=world, util=util, controller=controller))],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


HEADERS = {"x-winzapp-presence-trace": "1", "x-winzapp-presence-sequence": "12", "x-winzapp-presence-epoch": "2"}


def test_old_client_response_and_call_remain_unchanged_without_trace():
    result = run({"native": True})
    assert result["first"] == {"code": 200, "body": {"status": "success", "response": {"message": "Set Online Presence Successfully"}}}
    assert result["calls"] == [False] and result["reads"] == 0 and result["logs"] == []


@pytest.mark.parametrize("online", [True, False])
def test_readback_is_local_observation_and_never_receiver_confirmation(online):
    result = run({"headers": HEADERS, "online": online, "localAvailable": online, "native": True})
    diag = result["first"]["body"]["diagnostic"]
    assert diag["sequence"] == 12 and diag["epoch"] == 2
    assert diag["requested"] is online and diag["runtime"]["available"] is online
    assert diag["receiverConfirmed"] is False and diag["native"] == "true"
    assert result["calls"] == [online] and result["reads"] == 1


@pytest.mark.parametrize("field,value", [("x-winzapp-presence-sequence", "PRIVATE_TOKEN"),
                                         ("x-winzapp-presence-epoch", "12345678"),
                                         ("x-winzapp-presence-sequence", ["1"]),
                                         ("x-winzapp-presence-trace", "0")])
def test_invalid_or_unsampled_trace_never_starts_readback(field, value):
    result = run({"headers": {**HEADERS, field: value}})
    assert "diagnostic" not in result["first"]["body"] and result["reads"] == 0


@pytest.mark.parametrize("world,status", [({"timeout": True}, "timeout"), ({"readError": True}, "failed"), ({"noPage": True}, "unavailable")])
def test_diagnostic_failure_does_not_change_a_successful_presence_call(world, status):
    result = run({**world, "headers": HEADERS, "native": False})
    assert result["first"]["code"] == 200
    assert result["first"]["body"]["diagnostic"]["runtime"]["status"] == status
    assert "PRIVATE" not in " ".join(result["logs"])


def test_send_failure_retains_http_error_and_logs_only_fixed_classes():
    result = run({"headers": HEADERS, "sendError": True})
    assert result["first"]["code"] == 500 and result["reads"] == 0
    assert "PRIVATE" not in " ".join(result["logs"])
    assert '"native":"error"' in result["logs"][0]


def test_server_bounds_repeated_trace_headers_per_client():
    result = run({"headers": HEADERS, "repeat": True})
    assert result["reads"] == len(result["logs"]) == 1
    assert len(result["calls"]) == 2 and "diagnostic" not in result["last"]


@pytest.mark.parametrize("native,expected", [(False, "false"), (None, "other"),
                                         ({"private": "PRIVATE_NATIVE"}, "other"),
                                         (["PRIVATE_NATIVE"], "other"), ("PRIVATE_NATIVE", "other")])
def test_native_result_is_only_a_fixed_class_not_a_claim_of_remote_success(native, expected):
    result = run({"headers": HEADERS, "native": native})
    diag = result["first"]["body"]["diagnostic"]
    assert diag["native"] == expected and diag["receiverConfirmed"] is False
    assert result["first"]["code"] == 200
    assert "PRIVATE_NATIVE" not in json.dumps(diag) + " ".join(result["logs"])


def test_void_native_and_omitted_body_field_preserve_the_default_online_call():
    result = run({"headers": HEADERS, "body": {}})
    diag = result["first"]["body"]["diagnostic"]
    assert result["calls"] == [True] and diag["requested"] is True
    assert diag["native"] == "void"


@pytest.mark.parametrize("world,status", [({"noWpp": True}, "unavailable"),
                                        ({"noStream": True}, "unavailable"),
                                        ({"readReject": True}, "failed"),
                                        ({"rawRuntime": {"status": "PRIVATE_RUNTIME", "available": "PRIVATE_STATE"}}, "failed")])
def test_missing_or_invalid_runtime_is_unknown_and_does_not_leak_payload(world, status):
    result = run({"headers": HEADERS, **world})
    diag = result["first"]["body"]["diagnostic"]
    assert diag["runtime"]["status"] == status and diag["runtime"]["available"] is None
    assert "PRIVATE" not in json.dumps(diag) + " ".join(result["logs"])
    assert result["first"]["code"] == 200


@pytest.mark.parametrize("advance,new_client,expected", [(999, False, 1), (1000, False, 2),
                                                      (0, True, 2)])
def test_trace_boundary_and_account_isolation(advance, new_client, expected):
    result = run({"headers": HEADERS, "repeat": True, "advance": advance, "newClient": new_client})
    assert result["reads"] == len(result["logs"]) == expected
    assert len(result["calls"]) == 2


def test_logger_failure_cannot_turn_a_successful_presence_request_into_an_error():
    result = run({"headers": HEADERS, "logError": True})
    assert result["first"]["code"] == 200 and result["logs"] == []
