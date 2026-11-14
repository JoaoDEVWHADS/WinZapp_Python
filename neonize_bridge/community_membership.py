"""Joining a group of a community, withdrawing a request to join one, and
deactivating a community: the stanzas WhatsApp Web sends, read over CDP on
2026-10-26 (WAWebGroupJoinSubgroupJob + WASmaxOutGroupsJoinLinkedGroupRequest,
WAWebGroupCancelMembershipRequestJob + WASmaxOutGroupsCancelGroupMembershipRequestsRequest,
WAWebGroupCommunityJob.sendDeactivateCommunity + WASmaxOutGroupsDeleteParentGroupRequest).
All three are `w:g2` set queries:

- join: to the community, <join_linked_group type="sub_group" jid=group/>. A
  plain result is "joined"; one carrying <membership_approval_request> is
  "requested" (an admin has to approve); error 304 is "request_pending";
- cancel: to the group, <cancel_membership_requests><participant jid=me/>,
  where "me" is the account's LID (lidGroupMigrationNonMemberIQEnabled() is
  true on WhatsApp Web), else its number; a participant answered with an
  `error` attribute was not withdrawn;
- deactivate: to the community, <delete_parent/>; 401 is "you did not create
  it", 404 "it no longer exists".

The answers follow WinZapp's WPPConnect routes (communityJoinController.ts):
`{"response": {"state"}}`, or `{"code", "retrySafe": false}`. Never retried: a
query that timed out may have reached the server. A neonize build without raw
queries answers 501 "unavailable", as before. Not run against a real account.
"""
import asyncio
import logging
import re

from aiohttp import web

import raw_queries as rq

log = logging.getLogger("bridge")

_GROUP = re.compile(r"[0-9]+(?:-[0-9]+)?@g\.us\Z")
REQUEST_EXISTS = 304
FAILURE_STATUS = {"invalid_request": 400, "not_community": 404, "group_unavailable": 409,
                  "unavailable": 501}


def group_jid(text) -> str:
    text = str(text or "").strip()
    return text if _GROUP.fullmatch(text) else ""


def bare_user(jid_text) -> str:
    """'123:4@lid' -> '123@lid' (the device does not belong in a participant)."""
    user, _, server = str(jid_text or "").partition("@")
    return f"{user.split(':')[0]}@{server}" if user and server else ""


def join_query(community, group) -> dict:
    return {"namespace": "w:g2", "type": "set", "to": community,
            "content": [rq.node("join_linked_group",
                                {"type": "sub_group", "jid": rq.jid(group)})]}


def cancel_query(group, me) -> dict:
    return {"namespace": "w:g2", "type": "set", "to": group,
            "content": [rq.node("cancel_membership_requests", None,
                                [rq.node("participant", {"jid": rq.jid(me)})])]}


def deactivate_query(community) -> dict:
    return {"namespace": "w:g2", "type": "set", "to": community,
            "content": [rq.node("delete_parent")]}


def join_state(response) -> str:
    """'joined' or 'requested' from the response node of a join."""
    return "requested" if rq.child(response, "membership_approval_request") else "joined"


def join_error_state(code) -> str:
    """The state a refused join still means ('' when it is a failure)."""
    return "request_pending" if code == REQUEST_EXISTS else ""


def join_failure(code) -> str:
    return "group_unavailable" if code == 404 else "join_failed"


def cancel_withdrawn(response) -> bool:
    """Was the request withdrawn? Every participant answered without `error`."""
    request = rq.child(response, "cancel_membership_requests")
    people = rq.children(request, "participant") if request else []
    return all("error" not in (p.get("attrs") or {}) for p in people)


def deactivate_failure(code) -> tuple:
    """(HTTP status, code) of a refused deactivation."""
    if code == 401:
        return 403, "not_community_owner"
    if code == 404:
        return 404, "not_community"
    return 502, "community_action_failed"


def register_routes(r, *, session):
    """Wire the routes to the aiohttp router `r`."""

    async def execute(func, *args):
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)

    def failure(code, status=None):
        return web.json_response({"status": "error", "code": code, "retrySafe": False},
                                 status=status or FAILURE_STATUS.get(code, 502))

    def state(value):
        return web.json_response({"status": "success", "response": {"state": value}})

    def ready(s):
        return s.client is not None and s.status == "CONNECTED" and rq.available(s.client)

    async def membership(req, operation):
        s = session(req)
        community = group_jid(req.match_info["communityId"])
        group = group_jid(req.match_info["subgroupId"])
        if not community or not group:
            return failure("invalid_request")
        if not ready(s):
            return failure("unavailable")
        if operation == "join":
            try:
                return state(join_state(await execute(rq.send_iq, s.client,
                                                      join_query(community, group))))
            except rq.QueryError as e:
                pending = join_error_state(e.code)
                if pending:
                    return state(pending)
                log.warning("join community group refused (%s)", e.code)
                return failure(join_failure(e.code))
        me = bare_user(s.lid) or bare_user(s.me)
        if not me:
            return failure("unavailable")
        try:
            response = await execute(rq.send_iq, s.client, cancel_query(group, me))
        except rq.QueryError as e:
            log.warning("cancel join request refused (%s)", e.code)
            return failure("cancel_failed")
        return state("cancelled") if cancel_withdrawn(response) else failure("cancel_failed")

    async def join(req):
        return await membership(req, "join")

    async def cancel(req):
        return await membership(req, "cancel")

    async def deactivate(req):
        s = session(req)
        try:
            body = await req.json()
        except ValueError:
            body = {}
        community = group_jid((body or {}).get("id") if isinstance(body, dict) else "")
        if not community:
            return failure("invalid_request")
        if not ready(s):
            return failure("unavailable")
        try:
            await execute(rq.send_iq, s.client, deactivate_query(community))
        except rq.QueryError as e:
            status, code = deactivate_failure(e.code)
            log.warning("deactivate community refused (%s)", e.code)
            return failure(code, status)
        return web.json_response({"status": "success", "response": {"id": community}})

    r.add_post("/api/{tok}/community-subgroups/{communityId}/{subgroupId}/join", join)
    r.add_post("/api/{tok}/community-subgroups/{communityId}/{subgroupId}/cancel-request",
               cancel)
    r.add_post("/api/{tok}/deactivate-community", deactivate)
