import type { Request, Response } from 'express';

// Joining a group of a community the account is not in, or asking to: what
// WhatsApp Web's own "Join group" / "Request to join" / "Cancel request" button
// does (WAWebSubgroupJoinModal.react), read over CDP on 2026-10-18:
//
// 1. WAWebQuerySubGroupAction.querySubgroupInfo(subgroup, community) reads
//    the group: `suspended` (no longer available), `hiddenSubgroup` (only its
//    owner can add anyone), `membershipApprovalMode` (joining needs an
//    admin's approval) and `membershipApprovalRequest` (already asked).
// 2. WAWebJoinSubgroupAction.joinSubgroup({parentGroupId, request,
//    subgroupId}) with `request` = membershipApprovalMode. A status 200 is
//    "joined", or "request sent" when it was a request. When the server and
//    the flag disagree it throws UnexpectedJoinSubgroupResponse carrying the
//    real membershipApprovalMode, which the modal takes as the answer; a
//    ServerStatusCodeError 304 means a request already exists.
// 3. WAWebMembershipApprovalRequestAction.cancelMembershipApprovalRequest(subgroup)
//    withdraws a request.
// 4. WAWebUpdateSubgroupsCommunityAction.updateMembershipApprovalRequest(subgroup, sent)
//    records whether a request is pending, as the modal does after 2 and 3.
//
// WAWebJoinSubgroupAction belongs to the lazily loaded join modal: until
// someone opens it, the module does not exist. Its code is loaded through the
// Bootloader without showing anything, as communityCommentsRuntime.ts does
// for the comments modal.
//
// Never retried: a join or a request that timed out may have reached the
// server, and the client decides what to do next.
//
// Runs inside the page: self-contained, no closure over anything here.
export async function communitySubgroupMembership({ communityId, subgroupId, operation }: {
  communityId: string; subgroupId: string; operation: string;
}): Promise<any> {
  const root = globalThis as any;
  const isGroup = (value: unknown) => typeof value === 'string' && /^[0-9-]+@g\.us$/.test(value);
  if (!isGroup(communityId) || !isGroup(subgroupId) || !['join', 'cancel'].includes(operation)) {
    return { ok: false, code: 'invalid_request' };
  }
  const load = (name: string) => {
    try {
      return typeof root.require === 'function' ? root.require(name) : undefined;
    } catch (_) {
      return undefined;
    }
  };
  const parent = root.WPP?.whatsapp?.GroupMetadataStore?.get?.(communityId);
  if (!parent || parent.isParentGroup !== true) return { ok: false, code: 'not_community' };
  const createWid = root.WPP?.whatsapp?.WidFactory?.createWid;
  if (typeof createWid !== 'function') return { ok: false, code: 'unavailable' };
  const subgroup = createWid(subgroupId);
  const recordRequest = (sent: boolean) => {
    try {
      load('WAWebUpdateSubgroupsCommunityAction')?.updateMembershipApprovalRequest?.(subgroup, sent);
    } catch (_) {
      // Bookkeeping only: the answer stands without it.
    }
  };

  if (operation === 'cancel') {
    const approval = load('WAWebMembershipApprovalRequestAction');
    if (typeof approval?.cancelMembershipApprovalRequest !== 'function') {
      return { ok: false, code: 'unavailable' };
    }
    try {
      await approval.cancelMembershipApprovalRequest(subgroup);
    } catch (_) {
      return { ok: false, code: 'cancel_failed' };
    }
    recordRequest(false);
    return { ok: true, state: 'cancelled' };
  }

  let join = load('WAWebJoinSubgroupAction');
  if (typeof join?.joinSubgroup !== 'function') {
    const module = load('Bootloader');
    const bootloader = module?.default || module;
    if (typeof bootloader?.loadModules === 'function') {
      try {
        await new Promise<void>((resolve, reject) => {
          const timer = setTimeout(() => reject(new Error('unavailable')), 8000);
          bootloader.loadModules(['WAWebSubgroupJoinModal.react'],
            () => { clearTimeout(timer); resolve(); }, 'WinZapp');
        });
      } catch (_) {
        // Answered below: the action is still missing.
      }
      join = load('WAWebJoinSubgroupAction');
    }
  }
  const query = load('WAWebQuerySubGroupAction');
  if (typeof join?.joinSubgroup !== 'function' || typeof query?.querySubgroupInfo !== 'function') {
    return { ok: false, code: 'unavailable' };
  }
  let info: any;
  try {
    info = await query.querySubgroupInfo(subgroup, parent.id);
  } catch (_) {
    return { ok: false, code: 'join_failed' };
  }
  if (info?.suspended) return { ok: false, code: 'group_unavailable' };
  if (info?.hiddenSubgroup) return { ok: false, code: 'hidden_group' };
  if (info?.membershipApprovalRequest) {
    recordRequest(true);
    return { ok: true, state: 'request_pending' };
  }
  const request = info?.membershipApprovalMode === true;
  const errors = load('WAWebBackendErrors');
  let state: string;
  try {
    const result = await join.joinSubgroup({ parentGroupId: parent.id, request, subgroupId: subgroup });
    if (result?.status !== 200) return { ok: false, code: 'join_failed' };
    state = request ? 'requested' : 'joined';
  } catch (error: any) {
    if (errors?.UnexpectedJoinSubgroupResponse && error instanceof errors.UnexpectedJoinSubgroupResponse) {
      state = error.membershipApprovalMode ? 'requested' : 'joined';
    } else if (errors?.ServerStatusCodeError && error instanceof errors.ServerStatusCodeError
               && error.status === 304) {
      state = 'request_pending';
    } else {
      return { ok: false, code: 'join_failed' };
    }
  }
  if (state !== 'joined') recordRequest(true);
  return { ok: true, state };
}

const FAILURE_STATUS: Record<string, number> = {
  invalid_request: 400,
  not_community: 404,
  group_unavailable: 409,
  hidden_group: 409,
};

async function run(req: Request, res: Response, operation: 'join' | 'cancel') {
  const communityId = req.params.communityId;
  const subgroupId = req.params.subgroupId;
  try {
    const page: any = (req.client as any)?.page;
    if (!page || page.isClosed?.()) throw new Error('unavailable');
    const result = await page.evaluate(communitySubgroupMembership, { communityId, subgroupId, operation });
    if (result?.ok === true && typeof result.state === 'string') {
      return res.status(200).json({ status: 'success', response: { state: result.state } });
    }
    const code = typeof result?.code === 'string' ? result.code : 'unavailable';
    return res.status(FAILURE_STATUS[code] || 502).json({ status: 'error', code, retrySafe: false });
  } catch (_) {
    // Never the native error: it can carry group names and ids.
    return res.status(502).json({ status: 'error', code: 'unavailable', retrySafe: false });
  }
}

export const joinSubgroup = (req: Request, res: Response) => run(req, res, 'join');
export const cancelJoinRequest = (req: Request, res: Response) => run(req, res, 'cancel');
