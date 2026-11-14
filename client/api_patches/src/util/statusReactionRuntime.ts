/*
 * In-page runtime for the status like: the CALL into WhatsApp Web's private
 * WAWebSendStatusReactionAction module (see deviceController.reactMessage,
 * which finds the status model and the module and hands both over).
 *
 * This is the part that keeps breaking. The module is private, and in the six
 * weeks since WinZapp started calling it (2026-08-24) a new WhatsApp Web build
 * broke the like three times: once by moving the module into a lazily fetched
 * script (reactMessage's side, not this file's) and twice by changing how an
 * export is called (docs/traps/send-contract.md has the measurements):
 *
 *   sendStatusReaction(status, reaction)
 *     -> sendStatusReaction(status, reaction, key, previous)      2026-09-04
 *   applyOptimisticStatusReaction(status, reaction, key)
 *     -> applyOptimisticStatusReaction({msgKey, parentStatusMsg, reaction})
 *                                   2026-10-06, build 2.3000.1049387914
 *
 * Two rules come out of that history, and they are what this file is for:
 *
 * 1. Only what the send needs is required. Read from WhatsApp's own source
 *    over CDP: sendStatusReaction builds, processes and sends the reaction
 *    by itself. applyOptimisticStatusReaction only paints the like into the
 *    page's in-memory ReactionsCollection before the send, for WhatsApp Web's
 *    own screen, which nobody looks at here (WinZapp keeps the liked state in
 *    settings.json). So it is called when it can be, in the shape its arity
 *    asks for, and a failure there is reported and never stops the like. The
 *    last breakage was exactly that step throwing before anything was sent.
 * 2. A failure names itself. The detail carries the stage that threw and the
 *    name/arity of every export, so the next change is read from log.log
 *    instead of needing a debugger on a live session.
 *
 * plan() is the one place that decides the call shape. The startup probe
 * (getSendCapabilities) asks it too, so the probe and the send cannot disagree.
 *
 * It is ONE self-contained plain-JS function (no TypeScript, no closure over
 * Node variables, no backticks and no dollar-brace sequences), kept as a
 * string so that exactly this text runs in the page and in the Node-run
 * contract tests (tests/test_status_reaction_runtime.py).
 *
 * Contract of call(): resolves { ok: true, detail } once WhatsApp's
 * sendStatusReaction resolved, { ok: false, detail } otherwise. It never
 * throws and never calls sendStatusReaction twice.
 */

export const STATUS_REACTION_RUNTIME_GLOBAL = '__winzappStatusReaction';

export const STATUS_REACTION_RUNTIME_SOURCE = String.raw`function () {
  const describe = (error) =>
    String((error && error.message) || error).slice(0, 300);

  const exportsOf = (action) => {
    try {
      return Object.keys(action || {})
        .sort()
        .map((name) => {
          const value = action[name];
          return (
            name + '/' + (typeof value === 'function' ? value.length : typeof value)
          );
        })
        .join(',');
    } catch (error) {
      return 'unreadable';
    }
  };

  // Pure: reads the exports, calls nothing.
  const plan = (action) => {
    const seen = exportsOf(action);
    const send = action && action.sendStatusReaction;
    if (typeof send !== 'function') {
      return { supported: false, signature: 'missing', optimistic: 'none', exports: seen };
    }
    const hasMint = typeof action.mintStatusReactionKey === 'function';
    if (!hasMint) {
      // Three or more parameters means a reaction key is expected, and only
      // WhatsApp's own mint builds one with the right participant.
      return send.length >= 3
        ? { supported: false, signature: 'unsupported', optimistic: 'none', exports: seen }
        : { supported: true, signature: 'legacy-2', optimistic: 'none', exports: seen };
    }
    const apply = action.applyOptimisticStatusReaction;
    let optimistic = 'none';
    if (typeof apply === 'function') {
      // One parameter is the object form, three were the positional one.
      optimistic = apply.length <= 1 ? 'object' : 'positional';
    }
    return {
      supported: true,
      signature: 'current-' + send.length,
      optimistic: optimistic,
      exports: seen,
    };
  };

  const call = async (args) => {
    const action = args && args.action;
    const model = args && args.model;
    const reactionText = (args && args.reactionText) || '';
    const shape = plan(action);
    if (shape.signature === 'missing') {
      return {
        ok: false,
        detail: 'native-status-reaction-action-not-found; exports=' + shape.exports,
      };
    }
    if (!shape.supported) {
      return {
        ok: false,
        detail:
          'native-status-reaction-signature-unsupported; arity=' +
          action.sendStatusReaction.length +
          '; exports=' +
          shape.exports,
      };
    }

    let stage = 'send';
    let optimistic = shape.optimistic;
    try {
      if (shape.signature === 'legacy-2') {
        await action.sendStatusReaction(model, reactionText);
      } else {
        stage = 'mint';
        const reactionKey = await action.mintStatusReactionKey(model);
        let previousOptimisticReaction;
        if (optimistic !== 'none') {
          try {
            previousOptimisticReaction =
              optimistic === 'object'
                ? await action.applyOptimisticStatusReaction({
                    msgKey: reactionKey,
                    parentStatusMsg: model,
                    reaction: reactionText,
                  })
                : await action.applyOptimisticStatusReaction(
                    model,
                    reactionText,
                    reactionKey
                  );
          } catch (error) {
            // Cosmetic for WhatsApp Web's own screen: say so and send anyway.
            previousOptimisticReaction = undefined;
            optimistic = 'failed(' + optimistic + ': ' + describe(error) + ')';
          }
        }
        stage = 'send';
        await action.sendStatusReaction(
          model,
          reactionText,
          reactionKey,
          previousOptimisticReaction
        );
      }
    } catch (error) {
      return {
        ok: false,
        detail:
          'native-status-reaction-failed; stage=' +
          stage +
          '; error=' +
          describe(error) +
          '; signature=' +
          shape.signature +
          '; optimistic=' +
          optimistic +
          '; exports=' +
          shape.exports,
      };
    }
    return {
      ok: true,
      detail: 'signature=' + shape.signature + '; optimistic=' + optimistic,
    };
  };

  return { plan: plan, call: call };
}`;

/** Expression that (re)installs the runtime on the page. Idempotent and cheap:
 * run it before every use, a reloaded page has lost the global. */
export function buildStatusReactionInstallExpression(): string {
  return `window.${STATUS_REACTION_RUNTIME_GLOBAL} = (${STATUS_REACTION_RUNTIME_SOURCE})(); true`;
}
