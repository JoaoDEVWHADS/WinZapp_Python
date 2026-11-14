"""A status like must survive WhatsApp Web changing how its private action is called.

Measured 2026-10-06 over CDP on WhatsApp Web 2.3000.1049387914: every like
answered 500 with ``Cannot read properties of undefined (reading 'id')``.
``WAWebSendStatusReactionAction.applyOptimisticStatusReaction`` had gone from
``(status, reaction, key)`` to one object ``{msgKey, parentStatusMsg,
reaction}``; WinZapp still called it positionally, so ``parentStatusMsg`` was
undefined and the step threw before anything was sent. The same module had
already changed ``sendStatusReaction`` from two parameters to four on
2026-09-04.

client/api_patches/src/util/statusReactionRuntime.ts now makes the call. Read
from WhatsApp's source in the same session: ``sendStatusReaction`` builds,
processes and sends the reaction by itself, and the optimistic step only paints
WhatsApp Web's own screen. So that step is called in the shape its arity asks
for and is never allowed to stop the send.

The code under test is a string evaluated in a real page, so, as in
tests/test_forward_messages_lazy_resources.py: source contracts, plus the very
same text run by ``node`` against a fake module.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "client" / "api_patches" / "src"
RUNTIME = SRC / "util" / "statusReactionRuntime.ts"
CONTROLLER = SRC / "controller" / "deviceController.ts"


@pytest.fixture(scope="module")
def page_source() -> str:
    match = re.search(r"String\.raw`(.*?)`;", RUNTIME.read_text(encoding="utf-8"), re.S)
    assert match, "the in-page function must stay a String.raw template"
    return match.group(1)


@pytest.fixture(scope="module")
def controller() -> str:
    return CONTROLLER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def react_branch(controller: str) -> str:
    start = controller.index("export async function reactMessage")
    return controller[start:controller.index("export async function", start + 10)]


@pytest.fixture(scope="module")
def probe(controller: str) -> str:
    start = controller.index("export async function getSendCapabilities")
    return controller[start:controller.index("export async function", start + 10)]


class TestWiring:
    def test_the_send_goes_through_the_runtime(self, react_branch):
        assert "buildStatusReactionInstallExpression()" in react_branch
        assert "runtime.call({" in react_branch
        assert "status-reaction-runtime-not-installed" in react_branch

    def test_the_handler_no_longer_calls_the_private_exports_itself(self, react_branch):
        # A second copy of the call is a second place to forget next time.
        for export in ("sendStatusReaction(", "mintStatusReactionKey(",
                       "applyOptimisticStatusReaction("):
            assert export not in react_branch, export

    def test_the_runtime_is_installed_before_it_is_used(self, react_branch, probe):
        for section in (react_branch, probe):
            install = section.index("buildStatusReactionInstallExpression()")
            assert install < section.index("runtimeGlobal]")

    def test_the_probe_asks_the_same_plan_the_send_uses(self, probe):
        assert "[runtimeGlobal]?.plan?.(reactionModule)" in probe
        assert "checks.statusReaction = reactionShape?.supported === true" in probe
        # The optimistic step is optional for the send, so it must not be what
        # makes the probe tell the user that liking a status is unsupported.
        assert "applyOptimisticStatusReaction" not in probe

    def test_the_probe_logs_the_shape_of_the_private_module(self, probe):
        assert "statusReactionShape: reactionShape" in probe

    def test_the_file_is_in_every_list(self):
        name = "src/util/statusReactionRuntime.ts"
        for path in ("setup_api.py", "build.py", "client/ui/dialogs/api_setup.py",
                     "tests/test_api_patches_in_sync.py"):
            assert name in (ROOT / path).read_text(encoding="utf-8"), path


class TestSourceContracts:
    def test_it_is_self_contained(self, page_source):
        assert "`" not in page_source and "${" not in page_source

    def test_there_is_one_send_per_shape_and_no_retry(self, page_source):
        # One call site for the two-parameter form, one for the current one.
        assert page_source.count("action.sendStatusReaction(") == 2

    def test_both_shapes_of_the_optimistic_step_are_known(self, page_source):
        assert "parentStatusMsg: model" in page_source
        assert "msgKey: reactionKey" in page_source
        assert "apply.length <= 1 ? 'object' : 'positional'" in page_source


HARNESS = r"""
const fs = require('fs');
const [, , tsPath] = process.argv;
const ts = fs.readFileSync(tsPath, 'utf8');
const src = /String\.raw`([\s\S]*?)`;/.exec(ts)[1];
const world = JSON.parse(process.env.WORLD);
const calls = { mint: 0, apply: [], send: [] };

// What WhatsApp Web's ReactionsCollection holds for a status: my reaction.
const collection = Object.assign({}, world.collection || {});
const model = { id: { toString: () => 'false_status@broadcast_AAA_poster@lid' } };
const key = { toString: () => 'true_status@broadcast_KEY_poster@lid' };

const paint = (parent, msgKey, reaction) => {
  const parentKey = parent.id.toString();
  const previous = collection[parentKey];
  collection[parentKey] = { msgKey: msgKey.toString(), reactionText: reaction };
  return previous;
};
const send4 = async function (status, reaction, msgKey, previous) {
  calls.send.push({
    status: status.id.toString(),
    reaction,
    // The real one fails inside msgKey.toString() without a key.
    key: msgKey.toString(),
    previous: previous === undefined ? null : previous,
  });
  if (world.sendThrows) throw new Error('Status reaction send error');
};
const mint = async function (status) {
  calls.mint += 1;
  if (world.mintThrows) throw new Error('newId failed');
  status.id.toString();
  return key;
};
// Structurally the function read from 2.3000.1049387914 on 2026-10-06:
//   function p(e){var t=e.msgKey,n=e.parentStatusMsg,r=e.reaction,
//     a=ReactionsCollection.gadd({id:n.id}).reactionByMe; ...; return a}
const applyObject = function (e) {
  var t = e.msgKey, n = e.parentStatusMsg, r = e.reaction;
  calls.apply.push('object');
  if (world.applyThrows) throw new Error('optimistic write failed');
  return paint({ id: n.id }, t, r);
};
const applyPositional = function (status, reaction, msgKey) {
  calls.apply.push('positional');
  if (world.applyThrows) throw new Error('optimistic write failed');
  return paint(status, msgKey, reaction);
};

const actions = {
  // 2.3000.1049387914, as exported on 2026-10-06.
  object: {
    sendStatusReaction: send4,
    mintStatusReactionKey: mint,
    applyOptimisticStatusReaction: applyObject,
    rollBackOptimisticStatusReaction: async function (a, b, c, d) {},
    buildStatusReactionMsgData: async function (a) {},
  },
  // 2026-09-04 to 2026-10: the same module with the positional step.
  positional: {
    sendStatusReaction: send4,
    mintStatusReactionKey: mint,
    applyOptimisticStatusReaction: applyPositional,
  },
  // Before 2026-09-04.
  legacy: {
    sendStatusReaction: async function (status, reaction) {
      calls.send.push({ status: status.id.toString(), reaction, key: null, previous: null });
      if (world.sendThrows) throw new Error('Status reaction send error');
    },
  },
  // A future build that drops or renames the optimistic step.
  noOptimistic: { sendStatusReaction: send4, mintStatusReactionKey: mint },
  // A future build that renames the mint: a key is needed and cannot be built.
  noMint: { sendStatusReaction: send4, applyOptimisticStatusReaction: applyObject },
  empty: { somethingElse: 1 },
};

const runtime = eval('(' + src + ')')();
(async () => {
  const action = actions[world.action];
  if (world.mode === 'old-call') {
    // What WinZapp did until this fix, against the current module.
    let error = null;
    try {
      const reactionKey = await action.mintStatusReactionKey(model);
      action.applyOptimisticStatusReaction(model, world.reaction, reactionKey);
    } catch (e) {
      error = String(e && e.message);
    }
    console.log(JSON.stringify({ error, calls }));
    return;
  }
  const plan = runtime.plan(action);
  const callsAfterPlan = JSON.parse(JSON.stringify(calls));
  let result = null;
  let thrown = null;
  try {
    result = await runtime.call({ action, model, reactionText: world.reaction });
  } catch (e) {
    thrown = String(e && e.message);
  }
  console.log(JSON.stringify({ plan, callsAfterPlan, result, thrown, calls, collection }));
})();
"""

MODEL_ID = "false_status@broadcast_AAA_poster@lid"
KEY_ID = "true_status@broadcast_KEY_poster@lid"


def _node() -> str | None:
    # The bundled runtime first: it is the one that ships, and a dev machine
    # usually has no other node on PATH.
    bundled = ROOT / "client" / "node" / ("node.exe" if os.name == "nt" else "node")
    return str(bundled) if bundled.is_file() else shutil.which("node")


def _run(tmp_path, action: str, reaction: str = "❤️", **world):
    world.update(action=action, reaction=reaction)
    script = tmp_path / "harness.js"
    script.write_text(HARNESS, encoding="utf-8")
    env = dict(os.environ, WORLD=json.dumps(world))
    done = subprocess.run(
        [_node(), str(script), str(RUNTIME)],
        capture_output=True, text=True, encoding="utf-8", timeout=20, env=env,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


needs_node = pytest.mark.skipif(_node() is None, reason="node missing")


@needs_node
class TestTheBreakageOf20261006:
    def test_the_old_positional_call_is_what_failed(self, tmp_path):
        """Pins the fake to the real symptom: the exact error log.log carried."""
        out = _run(tmp_path, "object", mode="old-call")
        assert out["error"] == "Cannot read properties of undefined (reading 'id')"

    def test_the_like_is_sent_on_the_current_build(self, tmp_path):
        out = _run(tmp_path, "object")
        assert out["thrown"] is None
        assert out["result"]["ok"] is True
        assert out["calls"]["apply"] == ["object"]
        assert out["calls"]["send"] == [
            {"status": MODEL_ID, "reaction": "❤️", "key": KEY_ID, "previous": None}
        ]
        assert out["result"]["detail"] == "signature=current-4; optimistic=object"

    def test_the_previous_reaction_reaches_the_send_for_its_rollback(self, tmp_path):
        before = {"msgKey": "true_status@broadcast_OLD_poster@lid", "reactionText": "❤️"}
        out = _run(tmp_path, "object", reaction="", collection={MODEL_ID: before})
        assert out["calls"]["send"][0]["previous"] == before
        # Removing the like is an empty reaction, never a missing argument.
        assert out["calls"]["send"][0]["reaction"] == ""


@needs_node
class TestEveryKnownShape:
    def test_the_positional_optimistic_step_still_works(self, tmp_path):
        out = _run(tmp_path, "positional")
        assert out["result"] == {"ok": True,
                                 "detail": "signature=current-4; optimistic=positional"}
        assert out["calls"]["apply"] == ["positional"]
        assert out["calls"]["send"][0]["key"] == KEY_ID

    def test_the_two_parameter_send_still_works(self, tmp_path):
        out = _run(tmp_path, "legacy")
        assert out["result"] == {"ok": True,
                                 "detail": "signature=legacy-2; optimistic=none"}
        assert out["calls"]["mint"] == 0
        assert out["calls"]["send"] == [
            {"status": MODEL_ID, "reaction": "❤️", "key": None, "previous": None}
        ]


@needs_node
class TestTheNextChange:
    def test_an_optimistic_step_that_throws_does_not_stop_the_like(self, tmp_path):
        """The 2026-10-06 failure mode, whatever the next shape turns out to be."""
        out = _run(tmp_path, "object", applyThrows=True)
        assert out["result"]["ok"] is True
        assert len(out["calls"]["send"]) == 1
        assert out["calls"]["send"][0]["key"] == KEY_ID
        assert out["calls"]["send"][0]["previous"] is None
        assert "optimistic=failed(object: optimistic write failed)" in out["result"]["detail"]

    def test_a_missing_optimistic_step_does_not_stop_the_like(self, tmp_path):
        out = _run(tmp_path, "noOptimistic")
        assert out["result"] == {"ok": True,
                                 "detail": "signature=current-4; optimistic=none"}
        assert len(out["calls"]["send"]) == 1

    def test_a_send_that_needs_a_key_nobody_can_mint_sends_nothing(self, tmp_path):
        out = _run(tmp_path, "noMint")
        assert out["plan"]["supported"] is False
        assert out["result"]["ok"] is False
        assert out["result"]["detail"].startswith(
            "native-status-reaction-signature-unsupported; arity=4; exports="
        )
        assert out["calls"] == {"mint": 0, "apply": [], "send": []}

    def test_a_module_without_the_action_is_reported_with_what_it_has(self, tmp_path):
        out = _run(tmp_path, "empty")
        assert out["result"] == {
            "ok": False,
            "detail": "native-status-reaction-action-not-found; exports=somethingElse/number",
        }


@needs_node
class TestAFailureNamesItself:
    def test_a_rejected_send_says_where_and_is_not_retried(self, tmp_path):
        out = _run(tmp_path, "object", sendThrows=True)
        assert out["thrown"] is None, "the runtime never throws"
        assert out["result"]["ok"] is False
        detail = out["result"]["detail"]
        assert detail.startswith(
            "native-status-reaction-failed; stage=send; error=Status reaction send error;"
        )
        assert len(out["calls"]["send"]) == 1

    def test_the_detail_carries_every_export_with_its_arity(self, tmp_path):
        """What made 2026-10-06 need a debugger: the log had the error and
        nothing about the module it came from."""
        out = _run(tmp_path, "object", sendThrows=True)
        assert out["result"]["detail"].endswith(
            "exports=applyOptimisticStatusReaction/1,buildStatusReactionMsgData/1,"
            "mintStatusReactionKey/1,rollBackOptimisticStatusReaction/4,"
            "sendStatusReaction/4"
        )

    def test_a_failed_mint_sends_nothing(self, tmp_path):
        out = _run(tmp_path, "object", mintThrows=True)
        assert out["result"]["ok"] is False
        assert "stage=mint; error=newId failed" in out["result"]["detail"]
        assert out["calls"]["send"] == [] and out["calls"]["apply"] == []


@needs_node
class TestThePlan:
    def test_it_calls_nothing(self, tmp_path):
        out = _run(tmp_path, "object")
        assert out["callsAfterPlan"] == {"mint": 0, "apply": [], "send": []}

    @pytest.mark.parametrize("action,supported,signature,optimistic", [
        ("object", True, "current-4", "object"),
        ("positional", True, "current-4", "positional"),
        ("legacy", True, "legacy-2", "none"),
        ("noOptimistic", True, "current-4", "none"),
        ("noMint", False, "unsupported", "none"),
        ("empty", False, "missing", "none"),
    ])
    def test_the_verdict_for_each_module(self, tmp_path, action, supported,
                                         signature, optimistic):
        plan = _run(tmp_path, action)["plan"]
        assert (plan["supported"], plan["signature"], plan["optimistic"]) == (
            supported, signature, optimistic)
