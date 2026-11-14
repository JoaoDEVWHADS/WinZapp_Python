import type { Request, Response } from 'express';

// What the client needs to show the account's communities: each community
// (the "parent group"), its admins as the page knows them, and its groups,
// joined or not, with the announcement group told apart.
//
// A route of WinZapp's own because nothing upstream answers this. The library
// exposes the community's *actions* (create, deactivate, link and unlink
// groups, promote and demote: routes that already exist and are used as they
// are), and WPP.community.getSubgroups() for one community, but no list of
// communities; and WPP.community.getAnnouncementGroup() looks for
// groupType === "LINKED_ANNOUNCEMENT_GROUP", a field WhatsApp Web no longer
// fills (read over CDP on 2.3000.1049387914: undefined on all 273 groups, so
// the function answered undefined for every one of 39 communities). The
// announcement group is the subgroup whose metadata has defaultSubgroup, which
// is also what the community-comments runtime keys on.
//
// The groups the account is NOT in live elsewhere: parent.unjoinedSubgroups
// lists their ids and WAWebUnjoinedSubgroupMetadataCollection their names,
// and both stay empty until WhatsApp is asked. WhatsApp Web asks when a
// community is opened (WAWebQuerySubGroupAction.queryAndUpdateSubgroupsMetadata,
// a GraphQL read); refreshUnjoinedSubgroups() below asks the same way, for the
// community selected in WinZapp. What it answered is kept by WhatsApp, so the
// plain list carries it from then on. Measured over CDP, 2026-10-18: 0 unjoined
// on all 39 communities before, 2 on the one queried after (170 ms).
//
// Runs inside the page: self-contained, no closure over anything here.
export function readCommunities(): unknown {
  const store = (globalThis as any).WPP?.whatsapp?.GroupMetadataStore;
  if (!store || typeof store.getModelsArray !== 'function') return null;
  let unjoinedStore: any = null;
  try {
    const load = (globalThis as any).require;
    unjoinedStore = typeof load === 'function' ? load('WAWebUnjoinedSubgroupMetadataCollection') : null;
  } catch (_) {
    unjoinedStore = null;
  }
  const text = (value: unknown) => (typeof value === 'string' ? value : '');
  const serialized = (wid: any) =>
    typeof wid === 'string' ? wid : text(wid?._serialized) || (wid ? String(wid) : '');
  const communities: unknown[] = [];
  for (const parent of store.getModelsArray()) {
    if (!parent || parent.isParentGroup !== true) continue;
    const id = serialized(parent.id);
    if (!/^[0-9-]+@g\.us$/.test(id)) continue;
    const admins: unknown[] = [];
    let iAmAdmin = false;
    let iAmSuperAdmin = false;
    try {
      // A community's own participant list holds its admins, not its members.
      for (const participant of parent.participants?.getModelsArray?.() ?? []) {
        if (participant?.isAdmin !== true && participant?.isSuperAdmin !== true) continue;
        const participantId = serialized(participant.id);
        if (participantId) admins.push({ id: participantId, superAdmin: participant.isSuperAdmin === true });
      }
      iAmAdmin = parent.participants?.iAmAdmin?.() === true;
      iAmSuperAdmin = parent.participants?.iAmSuperAdmin?.() === true;
    } catch (_) {
      // Unknown is "not an admin": an admin action is never offered on a guess.
    }
    const subgroups: unknown[] = [];
    for (const wid of Array.isArray(parent.joinedSubgroups) ? parent.joinedSubgroups : []) {
      const subgroupId = serialized(wid);
      if (!/^[0-9-]+@g\.us$/.test(subgroupId)) continue;
      const meta = store.get(subgroupId);
      subgroups.push({
        id: subgroupId,
        subject: text(meta?.subject),
        announcement: meta?.defaultSubgroup === true,
        general: meta?.generalSubgroup === true,
        joined: true,
        approval: false,
      });
    }
    const listed = new Set(subgroups.map((group: any) => group.id));
    for (const wid of Array.isArray(parent.unjoinedSubgroups) ? parent.unjoinedSubgroups : []) {
      const subgroupId = serialized(wid);
      if (!/^[0-9-]+@g\.us$/.test(subgroupId) || listed.has(subgroupId)) continue;
      let meta: any = null;
      try {
        meta = unjoinedStore?.get?.(subgroupId);
      } catch (_) {
        meta = null;
      }
      // WhatsApp shows a hidden group only to the community's admins.
      if (meta?.hiddenSubgroup === true && !iAmAdmin) continue;
      listed.add(subgroupId);
      subgroups.push({
        id: subgroupId,
        subject: text(meta?.subject),
        announcement: meta?.defaultSubgroup === true,
        general: meta?.generalSubgroup === true,
        joined: false,
        approval: meta?.membershipApprovalMode === true,
        // A request to join this account sent and an admin has not answered.
        requested: meta?.membershipApprovalRequest === true,
      });
    }
    communities.push({
      id,
      subject: text(parent.subject),
      description: text(parent.desc),
      closed: parent.isParentGroupClosed === true,
      iAmAdmin,
      iAmSuperAdmin,
      admins,
      subgroups,
    });
  }
  return communities;
}

// Asks WhatsApp for one community's groups, as WhatsApp Web does when the
// community is opened. A read: it joins nothing and changes nothing on the
// server; WhatsApp keeps the answer in its own unjoined-subgroup store.
export async function refreshUnjoinedSubgroups(communityId: string): Promise<boolean> {
  const root = globalThis as any;
  const parent = root.WPP?.whatsapp?.GroupMetadataStore?.get?.(communityId);
  if (!parent || parent.isParentGroup !== true || typeof root.require !== 'function') return false;
  const action = root.require('WAWebQuerySubGroupAction');
  if (typeof action?.queryAndUpdateSubgroupsMetadata !== 'function') return false;
  await action.queryAndUpdateSubgroupsMetadata(
    parent.id, Array.isArray(parent.joinedSubgroups) ? parent.joinedSubgroups : []);
  return true;
}

export async function listCommunities(req: Request, res: Response) {
  try {
    const page: any = (req.client as any)?.page;
    if (!page || page.isClosed?.()) throw new Error('communities_unavailable');
    const communities = await page.evaluate(readCommunities);
    if (!Array.isArray(communities)) throw new Error('communities_unavailable');
    return res.status(200).json({ status: 'success', response: communities });
  } catch (_) {
    // Never the native error: it can carry group names and ids.
    return res.status(503).json({ status: 'error', code: 'communities_unavailable' });
  }
}

// One community, after asking WhatsApp for the groups the account is not in.
export async function refreshCommunity(req: Request, res: Response) {
  const communityId = req.params.communityId;
  if (typeof communityId !== 'string' || !/^[0-9-]+@g\.us$/.test(communityId)) {
    return res.status(400).json({ status: 'error', code: 'invalid_community' });
  }
  try {
    const page: any = (req.client as any)?.page;
    if (!page || page.isClosed?.()) throw new Error('communities_unavailable');
    if (!(await page.evaluate(refreshUnjoinedSubgroups, communityId))) {
      throw new Error('communities_unavailable');
    }
    const communities = await page.evaluate(readCommunities);
    if (!Array.isArray(communities)) throw new Error('communities_unavailable');
    const community = communities.find((item: any) => item?.id === communityId);
    if (!community) return res.status(404).json({ status: 'error', code: 'community_not_found' });
    return res.status(200).json({ status: 'success', response: [community] });
  } catch (_) {
    // Never the native error: it can carry group names and ids.
    return res.status(503).json({ status: 'error', code: 'communities_unavailable' });
  }
}
