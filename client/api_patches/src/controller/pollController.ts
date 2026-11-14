import type { Request, Response } from 'express';
import { readPollVoters, readPollVotes, writePollVote } from '../util/pollRuntime';

const MESSAGE_ID = /^(true|false)_[\w.:-]+@[\w.]+_[\w]+(_[\w.:-]+@[\w.]+)?$/;

function pageOf(req: Request) {
  const page = (req.client as any)?.page;
  return page && !page.isClosed() ? page : undefined;
}

export async function readPollVotesRoute(req: Request, res: Response) {
  const { messageIds } = req.body || {};
  if (!Array.isArray(messageIds) || messageIds.length < 1 || messageIds.length > 50
      || !messageIds.every((id) => typeof id === 'string' && MESSAGE_ID.test(id))) {
    return res.status(400).json({ status: 'error', code: 'invalid_message_ids' });
  }
  const page = pageOf(req);
  if (!page) return res.status(503).json({ status: 'error', code: 'poll_votes_unavailable' });
  try {
    const response = await page.evaluate(readPollVotes, { messageIds });
    return res.status(200).json({ status: 'success', response });
  } catch (_) {
    // Native errors can include phone numbers and message content.
    return res.status(503).json({ status: 'error', code: 'poll_votes_unavailable' });
  }
}

export async function votePollRoute(req: Request, res: Response) {
  const { messageId, localIds } = req.body || {};
  if (typeof messageId !== 'string' || !MESSAGE_ID.test(messageId)
      || !Array.isArray(localIds) || localIds.length > 12) {
    return res.status(400).json({ status: 'error', code: 'invalid_vote' });
  }
  const page = pageOf(req);
  if (!page) return res.status(503).json({ status: 'error', code: 'poll_vote_unavailable' });
  try {
    const outcome = await page.evaluate(writePollVote, { messageId, localIds });
    if (!outcome?.ok) {
      return res.status(outcome?.error === 'poll_vote_invalid' ? 400 : 503)
        .json({ status: 'error', code: outcome?.error || 'poll_vote_failed' });
    }
    return res.status(200).json({ status: 'success' });
  } catch (_) {
    return res.status(503).json({ status: 'error', code: 'poll_vote_failed' });
  }
}

export async function readPollVotersRoute(req: Request, res: Response) {
  const { messageId } = req.body || {};
  if (typeof messageId !== 'string' || !MESSAGE_ID.test(messageId)) {
    return res.status(400).json({ status: 'error', code: 'invalid_message_id' });
  }
  const page = pageOf(req);
  if (!page) return res.status(503).json({ status: 'error', code: 'poll_voters_unavailable' });
  try {
    const outcome = await page.evaluate(readPollVoters, { messageId });
    if (!outcome?.ok) {
      return res.status(503).json({ status: 'error', code: 'poll_voters_unavailable' });
    }
    return res.status(200).json({ status: 'success', response: outcome });
  } catch (_) {
    return res.status(503).json({ status: 'error', code: 'poll_voters_unavailable' });
  }
}
