"""Community routes: the pure functions that build what the client reads."""
from types import SimpleNamespace as N

import communities


def jid(user, server="s.whatsapp.net"):
    return N(User=user, Server=server)


def person(user, admin=False, super_admin=False, lid="", phone="", error=0):
    return N(JID=jid(user), LID=jid(lid, "lid"), PhoneNumber=jid(phone),
             IsAdmin=admin, IsSuperAdmin=super_admin, Error=error,
             AddRequest=N(Code="", Expiration=0))


def group(user, name="", parent="", parents=False, default=False, topic="", people=()):
    return N(JID=jid(user, "g.us"), GroupName=N(Name=name), GroupTopic=N(Topic=topic),
             GroupParent=N(IsParent=parents), GroupIsDefaultSub=N(IsDefaultSubGroup=default),
             GroupLinkedParent=N(LinkedParentJID=jid(parent, "g.us")),
             Participants=list(people))


def target(user, name, default=False):
    return N(JID=jid(user, "g.us"), GroupName=N(Name=name),
             GroupIsDefaultSub=N(IsDefaultSubGroup=default))


def test_only_the_parent_group_is_a_community():
    assert communities.is_community(group("1", parents=True))
    assert not communities.is_community(group("2", parent="1"))


def test_administrators_are_only_the_marked_ones_and_the_number_comes_first():
    g = group("1", parents=True, people=[
        person("lid1", admin=True, lid="lid1", phone="5511"), person("222", super_admin=True),
        person("333")])
    assert communities.administrators_of(g) == [
        {"id": "5511@s.whatsapp.net", "superAdmin": False},
        {"id": "222@s.whatsapp.net", "superAdmin": True}]


def test_am_administrator_by_number_or_by_lid():
    g = group("1", parents=True, people=[person("lid1", admin=True, lid="lid1"), person("333")])
    assert communities.am_administrator(g, {"lid1"})
    assert not communities.am_administrator(g, {"333"})   # member, not admin
    assert not communities.am_administrator(g, {""})
    assert not communities.am_administrator(g, set())


def test_joined_and_not_joined_subgroups():
    parent = group("1", "Community", parents=True)
    announcements = group("2", "Announcements", parent="1", default=True)
    general = group("3", "General", parent="1")
    from_another = group("4", "Other", parent="9")
    rows = communities.community_subgroups_of(
        parent, [parent, announcements, general, from_another],
        [target("2", "Announcements", True), target("5", "Not joined"), target("1", "the parent itself")])
    assert [(r["id"], r["subject"], r["joined"], r["announcement"]) for r in rows] == [
        ("2@g.us", "Announcements", True, True), ("3@g.us", "General", True, False),
        ("5@g.us", "Not joined", False, False)]
    assert rows[2]["approval"] is False and rows[2]["requested"] is False


def test_subgroups_query_variables_carry_a_joined_group_as_hint():
    assert communities.subgroups_query_variables("1@g.us", ["2@g.us", "3@g.us"]) == {
        "group_id": "1@g.us", "query_context": "INTERACTIVE", "sub_group_hint_id": "2@g.us"}
    assert communities.subgroups_query_variables("1@g.us", []) == {
        "group_id": "1@g.us", "query_context": "INTERACTIVE"}


def mex_node(user, name, general=False, approval=False, requests=0):
    return {"id": user + "@g.us", "subject": {"value": name, "creation_time": "1700000000"},
            "properties": {"general_chat": general, "hidden_group": False,
                           "membership_approval_mode_enabled": approval},
            "membership_approval_requests": {"total_count": requests}}


MEX_ANSWER = {
    "__typename": "XWA2CommunityGroup", "id": "1@g.us",
    "default_sub_group": {"id": "2@g.us", "subject": {"value": "Announcements",
                                                      "creation_time": "1"}},
    "sub_groups": {"edges": [{"node": mex_node("3", "General", general=True)},
                             {"node": mex_node("5", "Needs approval", approval=True, requests=1)},
                             {"node": None}, {"node": {"subject": {"value": "no id"}}}]}}


def test_subgroups_from_the_query_whatsapp_web_runs():
    rows = communities.subgroups_from_mex(MEX_ANSWER)
    assert [(r["id"], r["subject"], r["announcement"], r["general"], r["approval"],
             r["requested"], r["joined"]) for r in rows] == [
        ("2@g.us", "Announcements", True, False, False, False, False),
        ("3@g.us", "General", False, True, False, False, False),
        ("5@g.us", "Needs approval", False, False, True, True, False)]
    assert communities.subgroups_from_mex(None) == []
    assert communities.subgroups_from_mex({"sub_groups": None}) == []
    # a bare number gets the group server
    assert communities.subgroups_from_mex({"default_sub_group": {"id": "9"}})[0]["id"] == "9@g.us"


def test_the_query_s_list_wins_over_get_sub_groups_and_marks_the_joined():
    parent = group("1", "Community", parents=True)
    announcements = group("2", "Announcements", parent="1", default=True)
    general = group("3", "General", parent="1")
    rows = communities.community_subgroups_of(
        parent, [parent, announcements, general], [target("8", "from get_sub_groups")],
        communities.subgroups_from_mex(MEX_ANSWER))
    assert [(r["id"], r["joined"], r["general"]) for r in rows] == [
        ("2@g.us", True, False), ("3@g.us", True, True), ("5@g.us", False, False)]
    assert rows[2]["approval"] is True and rows[2]["requested"] is True


def test_community_in_the_format_the_client_reads():
    parent = group("1", "Community", parents=True, topic="About",
                   people=[person("lid1", admin=True, lid="lid1")])
    announcements = group("2", "Announcements", parent="1", default=True)
    out = communities.communities_to_wpp([parent, announcements, group("7", "Ordinary group")], {"lid1"})
    assert out == [{
        "id": "1@g.us", "subject": "Community", "description": "About", "iAmAdmin": True,
        "admins": [{"id": "lid1@s.whatsapp.net", "superAdmin": False}],
        "subgroups": [{"id": "2@g.us", "subject": "Announcements", "announcement": True,
                       "general": False, "joined": True, "approval": False}]}]


def test_group_ids_refuses_what_is_not_a_group():
    assert communities.group_ids(["1@g.us", "12-34@g.us"]) == ["1@g.us", "12-34@g.us"]
    assert communities.group_ids([]) == []
    assert communities.group_ids(["5511@c.us"]) is None
    assert communities.group_ids("1@g.us") is None
    assert communities.group_ids([1]) is None


def test_link_result():
    assert communities.link_result("linkedGroupJids", ["1@g.us"], [("2@g.us", "x")]) == {
        "linkedGroupJids": ["1@g.us"],
        "failedGroups": [{"groupJid": "2@g.us", "errorText": "x"}]}
    assert communities.link_result("unlinkedGroupJids", [], []) == {
        "unlinkedGroupJids": [], "failedGroups": []}


def test_promotion_accepted_and_refused():
    assert communities.promotion_accepted("111@c.us", [person("111")])
    assert not communities.promotion_accepted("111@c.us", [])
    assert not communities.promotion_accepted("111@c.us", [person("111", error=403)])


def test_promotion_result_has_success_false_if_someone_was_refused():
    good = communities.promotion_result(["111@c.us"], [person("111")])
    assert good == {"participants": [{"id": "111@c.us", "code": 200}], "success": True}
    bad = communities.promotion_result(["111@c.us", "222@c.us"], [person("111")])
    assert bad["success"] is False and bad["participants"][1] == {"id": "222@c.us", "code": 403}


def test_the_community_and_its_announcement_group_count_the_whole_community():
    assert communities.community_counted(group("1", parents=True)) == "1@g.us"
    assert communities.community_counted(group("2", parent="1", default=True)) == "1@g.us"
    assert communities.community_counted(group("3", parent="1")) == ""
    assert communities.community_counted(group("4")) == ""


def test_member_total_counts_each_person_once():
    assert communities.member_total([jid("5511"), jid("5511"), jid("77", "lid"), jid("")]) == 2
    assert communities.member_total([]) == 0


def test_community_people_mark_who_is_admin():
    admins = [person("lid1", admin=True, lid="lid1", phone="5511"), person("9", super_admin=True)]
    rows = communities.community_people(
        [jid("5511"), jid("9"), jid("333"), jid("")], admins)
    assert rows == [
        {"id": "5511@s.whatsapp.net", "isAdmin": True, "isSuperAdmin": False},
        {"id": "9@s.whatsapp.net", "isAdmin": True, "isSuperAdmin": True},
        {"id": "333@s.whatsapp.net", "isAdmin": False, "isSuperAdmin": False}]


class Client:
    """Answers get_joined_groups, send_mex and get_sub_groups like neonize."""

    def __init__(self, groups, mex=None, targets=()):
        self.groups, self.mex, self.targets = groups, mex, list(targets)
        self.queries = []

    def get_joined_groups(self):
        return self.groups

    def send_iq(self, query):
        raise AssertionError("no IQ expected")

    def send_mex(self, query_id, variables):
        self.queries.append((query_id, variables))
        return self.mex

    def get_sub_groups(self, parent):
        return self.targets


def subgroups_route(client, monkeypatch):
    import asyncio

    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    import raw_queries
    monkeypatch.setattr(raw_queries, "available", lambda c: hasattr(c, "send_mex"))
    s = N(client=client, status="CONNECTED", me="5511@s.whatsapp.net", lid="")

    async def main():
        app = web.Application()
        communities.register_routes(
            app.router, session=lambda req: s, ok=lambda **kw: web.json_response(kw),
            jid_from_text=lambda t: jid(*t.split("@")))
        async with TestClient(TestServer(app)) as http:
            resp = await http.get("/api/tok/community-subgroups/1@g.us")
            return await resp.json()
    return asyncio.run(main())["response"][0]["subgroups"]


def test_the_route_lists_the_groups_not_joined_from_the_query(monkeypatch):
    parent = group("1", "Community", parents=True)
    joined = [parent, group("2", "Announcements", parent="1", default=True),
              group("3", "General", parent="1")]
    client = Client(joined, {"data": {"xwa2_group_query_by_id": MEX_ANSWER}},
                    [target("8", "from get_sub_groups")])
    rows = subgroups_route(client, monkeypatch)
    assert [(r["id"], r["joined"]) for r in rows] == [
        ("2@g.us", True), ("3@g.us", True), ("5@g.us", False)]
    assert client.queries == [(communities.SUBGROUPS_QUERY, {
        "group_id": "1@g.us", "query_context": "INTERACTIVE", "sub_group_hint_id": "2@g.us"})]


def test_a_refused_query_falls_back_to_get_sub_groups(monkeypatch):
    parent = group("1", "Community", parents=True)
    client = Client([parent, group("2", "Announcements", parent="1", default=True)],
                    {"error": "bad request"}, [target("8", "Not joined")])
    rows = subgroups_route(client, monkeypatch)
    assert [(r["id"], r["joined"]) for r in rows] == [("2@g.us", True), ("8@g.us", False)]
