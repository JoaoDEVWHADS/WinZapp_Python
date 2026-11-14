"""Community routes of the bridge: list, create, link and unlink groups,
promote and demote administrators. The response formats are the ones the
WinZapp client reads (core/communities.py).

A community, in neonize/whatsmeow, is a "parent" group (`GroupParent.IsParent`);
its groups point to it through `GroupLinkedParent`, and `link_group` /
`unlink_group` link and unlink a group. Deactivating a community and joining (or withdrawing the
request for) one of its groups are raw queries, in community_membership.py.
The groups the account is not in come from WhatsApp Web's own MEX query
(SUBGROUPS_QUERY), with neonize's `get_sub_groups` as the fallback.

The pure functions are at the top (tested in test_communities.py);
`register_routes` wires the routes to the server. Nothing here was tested
against a real account.
"""
import asyncio
import logging
import re
import uuid

from aiohttp import web

import raw_queries as rq
from groups import participants_result, user_of

log = logging.getLogger("bridge")

# WhatsApp Web's own query for a community's groups, joined or not
# (WAWebMexFetchAllSubgroupsJobQuery, run by WAWebQuerySubGroupAction when the
# community is opened): the announcement group in `default_sub_group`, every
# other group the account may see in `sub_groups`.
SUBGROUPS_QUERY = "9935467776504344"
SUBGROUPS_FIELD = "xwa2_group_query_by_id"

# The same formats that WinZapp's own routes accept
# (communityAdminController.ts).
_GROUP = re.compile(r"\d+(-\d+)?@g\.us")
_PERSON = re.compile(r"\d+@(c\.us|lid)")


def jid_text(jid) -> str:
    """neonize JID -> 'user@server' (empty if there is none). Same as server.py's."""
    if jid is None or not getattr(jid, "User", ""):
        return ""
    return "%s@%s" % (jid.User, jid.Server)


def is_community(group) -> bool:
    return bool(group.GroupParent.IsParent)


def community_counted(group) -> str:
    """The community whose members a group's size counts, or '': the community
    itself and its announcement group show every member of every group in it,
    as WhatsApp does; their own participant lists are much shorter."""
    if is_community(group):
        return jid_text(group.JID)
    if group.GroupIsDefaultSub.IsDefaultSubGroup:
        return jid_text(group.GroupLinkedParent.LinkedParentJID)
    return ""


def member_total(members) -> int:
    """How many people are among the JIDs of `get_linked_group_participants`."""
    return len({jid_text(j) for j in members if getattr(j, "User", "")})


def person_id(p) -> str:
    """The id with which the community shows a participant: the number, when
    known (like server.py's group-info), otherwise the JID or the LID."""
    return jid_text(p.PhoneNumber) or jid_text(p.JID) or jid_text(p.LID)


def administrators_of(group) -> list:
    """[{id, superAdmin}] of whoever administers the community."""
    return [{"id": person_id(p), "superAdmin": bool(p.IsSuperAdmin)}
            for p in group.Participants
            if (p.IsAdmin or p.IsSuperAdmin) and person_id(p)]


def am_administrator(group, my_users) -> bool:
    """The account is an administrator of the community. `my_users` are the
    account's own number and LID (only the part before the @); unknown is "no"."""
    mine = {u for u in my_users if u}
    for p in group.Participants:
        if (p.IsAdmin or p.IsSuperAdmin) and mine & {p.JID.User, p.LID.User, p.PhoneNumber.User}:
            return True
    return False


def joined_subgroup(group) -> dict:
    return {"id": jid_text(group.JID), "subject": group.GroupName.Name,
            "announcement": bool(group.GroupIsDefaultSub.IsDefaultSubGroup),
            "general": False, "joined": True, "approval": False}


def subgroup_from_target(target) -> dict:
    """GroupLinkTarget (a group of the community, which the account may not
    have joined) -> a subgroup row. neonize does not say whether joining needs
    approval nor whether there is already a request: `approval` and `requested`
    stay false."""
    return {"id": jid_text(target.JID), "subject": target.GroupName.Name,
            "announcement": bool(target.GroupIsDefaultSub.IsDefaultSubGroup),
            "general": False, "joined": False, "approval": False, "requested": False}


def subgroups_query_variables(parent_id, joined_ids) -> dict:
    """The variables of SUBGROUPS_QUERY, as WhatsApp Web sends them: the
    community and, as a hint, one of its groups the account is in."""
    variables = {"group_id": parent_id, "query_context": "INTERACTIVE"}
    if joined_ids:
        variables["sub_group_hint_id"] = joined_ids[0]
    return variables


def _group_id(value) -> str:
    text = str(value or "")
    return text if not text or "@" in text else text + "@g.us"


def subgroups_from_mex(answer) -> list:
    """`xwa2_group_query_by_id` of SUBGROUPS_QUERY -> subgroup rows with
    `joined` false (the route marks the ones the account is in). Like
    WAWebMexFetchAllSubgroupsJob: the announcement group first, then each
    edge; a node without an id is skipped instead of failing the list."""
    if not isinstance(answer, dict):
        return []
    rows = []

    def add(node, announcement):
        if not isinstance(node, dict) or not _group_id(node.get("id")):
            return
        subject = node.get("subject") if isinstance(node.get("subject"), dict) else {}
        properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        requests = node.get("membership_approval_requests")
        requests = requests if isinstance(requests, dict) else {}
        rows.append({"id": _group_id(node["id"]), "subject": subject.get("value") or "",
                     "announcement": announcement,
                     "general": bool(properties.get("general_chat")),
                     "joined": False,
                     "approval": bool(properties.get("membership_approval_mode_enabled")),
                     "requested": (requests.get("total_count") or 0) > 0})

    add(answer.get("default_sub_group"), True)
    connection = answer.get("sub_groups") if isinstance(answer.get("sub_groups"), dict) else {}
    for edge in connection.get("edges") or []:
        add(edge.get("node") if isinstance(edge, dict) else None, False)
    return rows


def community_subgroups_of(community, groups, targets=(), listed=()) -> list:
    """The community's groups: first the ones the account joined (`groups`:
    everything the account takes part in, linked to the parent by
    GroupLinkedParent) and then the ones it did not join, from `listed`
    (subgroups_from_mex) or, without it, from `targets` (get_sub_groups).
    What `listed` says of a joined group (general, approval) is kept."""
    user = community.JID.User
    parent_id = jid_text(community.JID)
    by_id = {row["id"]: row for row in listed}
    rows = []
    for g in groups:
        if g.GroupLinkedParent.LinkedParentJID.User != user or g.JID.User == user:
            continue
        row = joined_subgroup(g)
        seen = by_id.get(row["id"])
        if seen:
            row["general"], row["approval"] = seen["general"], seen["approval"]
        rows.append(row)
    known = {row["id"] for row in rows}
    others = list(listed) or [subgroup_from_target(t) for t in targets]
    for row in others:
        if row["id"] and row["id"] not in known and row["id"] != parent_id:
            known.add(row["id"])
            rows.append(row)
    return rows


def community_to_wpp(community, subgroups, my_users) -> dict:
    """The parent's GroupInfo -> an item of `communities` as the client reads it."""
    return {"id": jid_text(community.JID), "subject": community.GroupName.Name,
            "description": community.GroupTopic.Topic,
            "iAmAdmin": am_administrator(community, my_users),
            "admins": administrators_of(community), "subgroups": subgroups}


def communities_to_wpp(groups, my_users) -> list:
    """All the communities of a list of groups, with only the subgroups the
    account joined (no network per community)."""
    return [community_to_wpp(g, community_subgroups_of(g, groups), my_users)
            for g in groups if is_community(g)]


def group_ids(value):
    """The list of group ids (`groupIds` / `groupsIds`) or None if something
    comes that is not a list of group ids."""
    if not isinstance(value, list):
        return None
    if not all(isinstance(x, str) and _GROUP.fullmatch(x) for x in value):
        return None
    return value


def link_result(key, ok_ids, failures) -> dict:
    """{<key>: [...], failedGroups: [{groupJid, errorText}]}: the response of the
    WPPConnect library for linking (`linkedGroupJids`) and unlinking
    (`unlinkedGroupJids`). `failures` is a list of (id, error text)."""
    return {key: list(ok_ids),
            "failedGroups": [{"groupJid": i, "errorText": t} for i, t in failures]}


def promotion_result(requests, participants) -> dict:
    """Response of promote/demote-community-participant: {participants, success}.
    `success` is false if someone was not accepted; the client treats
    `success: false` as a refusal (core/communities.py, _act)."""
    by_person = participants_result(requests, participants)
    return {"participants": [{"id": request, "code": by_person[request]["code"]}
                             for request in requests],
            "success": all(v["code"] == 200 for v in by_person.values())}


def promotion_accepted(request, participants) -> bool:
    """WhatsApp accepted the promotion/demotion of this person."""
    return participants_result([request], participants)[request]["code"] == 200


def community_people(participants, administrators) -> list:
    """Rows of `community-participants`: {id, isAdmin, isSuperAdmin}.
    `participants` are the JIDs of whoever is in the community and
    `administrators` the parent's GroupParticipant (where who is admin comes from)."""
    admins = {}
    for p in administrators:
        for u in (p.JID.User, p.LID.User, p.PhoneNumber.User):
            if u:
                admins[u] = p
    rows = []
    for jid in participants:
        if not getattr(jid, "User", ""):
            continue
        p = admins.get(jid.User)
        rows.append({"id": jid_text(jid),
                     "isAdmin": bool(p and (p.IsAdmin or p.IsSuperAdmin)),
                     "isSuperAdmin": bool(p and p.IsSuperAdmin)})
    return rows


def register_routes(r, *, session, ok, jid_from_text):
    """Wire the community routes to the aiohttp router `r`."""
    from neonize.utils.enum import ParticipantChange

    async def execute(func, *args):
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)

    def error(message, status=500, code=None):
        body = {"status": "error", "message": str(message)}
        if code:
            body["code"] = code
        return web.json_response(body, status=status)

    def connected(s):
        return s.client is not None and s.status == "CONNECTED"

    def my_users(s):
        return {user_of(s.me or ""), user_of(s.lid or "")} - {""}

    async def create_community(req):
        s = session(req)
        body = await req.json()
        if not connected(s):
            return error("Disconnected", 400)
        name = body.get("name")
        description = body.get("description") or ""
        children = group_ids(body.get("groupIds") or [])
        if not isinstance(name, str) or not name.strip() or children is None:
            return error("invalid request", 400, "invalid_request")
        from neonize.proto.Neonize_pb2 import GroupParent
        try:
            info = await execute(s.client.create_group, name.strip(), [],
                                 None, GroupParent(IsParent=True))
        except Exception as e:
            log.exception("create-community")
            return error(e)
        parent = info.JID
        if description:
            try:
                await execute(s.client.set_group_topic, parent, "",
                              uuid.uuid4().hex.upper(), description)
            except Exception as e:
                # The community exists: the description failing does not undo it.
                log.warning("create-community: description not saved (%s)", type(e).__name__)
        linked, failures = await link(s, parent, children, True)
        return ok(status="success", response={
            "wid": jid_text(parent),
            "subGroups": link_result("linkedGroupJids", linked, failures)})

    async def link(s, parent, children, linking):
        """Links (or unlinks) each group, one by one, returning (done, failures)."""
        func = s.client.link_group if linking else s.client.unlink_group
        done, failures = [], []
        for text in children:
            try:
                await execute(func, parent, jid_from_text(text))
                done.append(text)
            except Exception as e:
                log.warning("community %s: a group refused (%s)",
                            "link" if linking else "unlink", type(e).__name__)
                failures.append((text, str(e)))
        return done, failures

    async def links(req, linking):
        s = session(req)
        body = await req.json()
        if not connected(s):
            return error("Disconnected", 400)
        community = body.get("id")
        children = group_ids(body.get("groupsIds"))
        if not isinstance(community, str) or not _GROUP.fullmatch(community) or not children:
            return error("invalid request", 400, "invalid_request")
        done, failures = await link(s, jid_from_text(community), children, linking)
        if failures and not done:
            return error(failures[0][1], 500)
        key = "linkedGroupJids" if linking else "unlinkedGroupJids"
        return ok(status="success", response=link_result(key, done, failures))

    async def add_community_subgroup(req):
        return await links(req, True)

    async def remove_community_subgroup(req):
        return await links(req, False)

    async def communities(req):
        s = session(req)
        if not connected(s):
            return error("Disconnected", 400)
        try:
            groups = await execute(s.client.get_joined_groups)
        except Exception as e:
            log.exception("communities")
            return error(e, 503, "communities_unavailable")
        return ok(status="success", response=communities_to_wpp(groups, my_users(s)))

    async def community_subgroups(req):
        s = session(req)
        if not connected(s):
            return error("Disconnected", 400)
        parent_id = req.match_info["communityId"]
        if not _GROUP.fullmatch(parent_id):
            return error("invalid community", 400, "invalid_community")
        try:
            groups = await execute(s.client.get_joined_groups)
        except Exception as e:
            log.exception("community-subgroups")
            return error(e, 503, "communities_unavailable")
        parent = next((g for g in groups if is_community(g) and jid_text(g.JID) == parent_id), None)
        if parent is None:
            return error("community not found", 404, "community_not_found")
        listed, targets = await all_subgroups(s, parent, groups)
        subgroups = community_subgroups_of(parent, groups, targets, listed)
        return ok(status="success", response=[
            community_to_wpp(parent, subgroups, my_users(s))])

    async def all_subgroups(s, parent, groups):
        """(listed, targets): the community's groups from WhatsApp Web's query
        when this build sends it, from get_sub_groups otherwise. Without
        either, there are still the groups the account joined."""
        parent_id = jid_text(parent.JID)
        if rq.available(s.client):
            joined = [jid_text(g.JID) for g in groups
                      if g.GroupLinkedParent.LinkedParentJID.User == parent.JID.User]
            try:
                answer = await execute(rq.send_mex, s.client, SUBGROUPS_QUERY,
                                       subgroups_query_variables(parent_id, joined),
                                       SUBGROUPS_FIELD)
                listed = subgroups_from_mex(answer)
                if listed:
                    return listed, []
            except rq.QueryError as e:
                log.warning("community-subgroups: query refused (%s)", e)
        try:
            return [], await execute(s.client.get_sub_groups, parent.JID)
        except Exception as e:
            log.warning("community-subgroups: get_sub_groups failed (%s)", type(e).__name__)
            return [], []

    async def community_participants(req):
        s = session(req)
        if not connected(s):
            return error("Disconnected", 400)
        parent_id = req.match_info["id"]
        if not _GROUP.fullmatch(parent_id):
            return error("invalid community", 400, "invalid_community")
        parent = jid_from_text(parent_id)
        try:
            requests = await execute(s.client.get_linked_group_participants, parent)
        except Exception as e:
            log.exception("community-participants")
            return error(e)
        try:
            administrators = (await execute(s.client.get_group_info, parent)).Participants
        except Exception:
            administrators = []
        return ok(status="success", response=community_people(list(requests), administrators))

    async def change_administrator(s, parent_id, people, action):
        """promote/demote in the parent group; returns neonize's GroupParticipant."""
        return await execute(
            s.client.update_group_participants, jid_from_text(parent_id),
            [jid_from_text(x) for x in people], action)

    async def community_admin_promote(req):
        s = session(req)
        body = await req.json()
        if not connected(s):
            return error("Disconnected", 400)
        parent_id = req.match_info["communityId"]
        person = body.get("participant")
        if not _GROUP.fullmatch(parent_id) or not isinstance(person, str) \
                or not _PERSON.fullmatch(person):
            return error("invalid request", 400, "invalid_request")
        try:
            response = await change_administrator(s, parent_id, [person], ParticipantChange.PROMOTE)
        except Exception as e:
            log.exception("community-admin promote")
            return error(e, 503, "promotion_unavailable")
        if not promotion_accepted(person, response):
            return error("promotion refused", 409, "promotion_refused")
        return ok(status="success", response={"promoted": True})

    async def participants_action(req, action):
        s = session(req)
        body = await req.json()
        if not connected(s):
            return error("Disconnected", 400)
        parent_id = body.get("id")
        people = body.get("participantsId")
        if not isinstance(parent_id, str) or not _GROUP.fullmatch(parent_id) \
                or not isinstance(people, list) or not people \
                or not all(isinstance(x, str) and x for x in people):
            return error("invalid request", 400, "invalid_request")
        try:
            response = await change_administrator(s, parent_id, people, action)
        except Exception as e:
            log.exception("community participants")
            return error(e)
        return ok(status="success", response=promotion_result(people, response))

    async def promote_community_participant(req):
        return await participants_action(req, ParticipantChange.PROMOTE)

    async def demote_community_participant(req):
        return await participants_action(req, ParticipantChange.DEMOTE)

    r.add_post("/api/{tok}/create-community", create_community)
    r.add_post("/api/{tok}/add-community-subgroup", add_community_subgroup)
    r.add_post("/api/{tok}/remove-community-subgroup", remove_community_subgroup)
    r.add_get("/api/{tok}/communities", communities)
    r.add_get("/api/{tok}/community-subgroups/{communityId}", community_subgroups)
    r.add_get("/api/{tok}/community-participants/{id}", community_participants)
    r.add_post("/api/{tok}/community-admin/{communityId}/promote", community_admin_promote)
    r.add_post("/api/{tok}/promote-community-participant", promote_community_participant)
    r.add_post("/api/{tok}/demote-community-participant", demote_community_participant)
