"""Turn one list of row identities into another with per-row deletes and
inserts — never by clearing the whole control.

Pure and wx-free, so it has a direct test. The conversation's message list
uses it (ui/conversation_panel/message_rows.py): a native ListView row is a
single MSAA object, so clearing the control and re-appending it hands the
screen reader a brand-new list and re-announces the row the user is sitting on,
even when nothing about that row changed. Deleting and inserting only the rows
that really differ leaves every other row — above all the focused one — alone.
"""

from difflib import SequenceMatcher


def plan_row_diff(old_keys: list, new_keys: list) -> "tuple[list[int], list[int]]":
    """Return ``(deletes, inserts)`` that turn *old_keys* into *new_keys*.

    *deletes* are indexes into the OLD list, highest first, so each one is
    still valid at the moment it is applied. *inserts* are indexes into the NEW
    list, ascending: once every delete has been applied the surviving rows are
    exactly the matched ones, in their final relative order, so inserting each
    missing row at its final index, lowest first, lands it in the right place
    and keeps every later index valid.

    Rows are matched by identity, in order (a longest-common-subsequence), so a
    row that merely moved is deleted and re-inserted — the one case where
    re-announcing is honest. Keys must be hashable; a key repeated inside one
    list is matched like any other, the first occurrence first.

    The common prefix and suffix are peeled off before the matcher runs: the
    refreshes this serves change a few rows at the tail, and diffing a few
    hundred identical rows against themselves is wasted work.
    """
    old_n, new_n = len(old_keys), len(new_keys)
    prefix = 0
    limit = min(old_n, new_n)
    while prefix < limit and old_keys[prefix] == new_keys[prefix]:
        prefix += 1
    suffix = 0
    while (suffix < limit - prefix
           and old_keys[old_n - 1 - suffix] == new_keys[new_n - 1 - suffix]):
        suffix += 1

    old_mid = old_keys[prefix:old_n - suffix]
    new_mid = new_keys[prefix:new_n - suffix]
    matched_old: set = set()
    matched_new: set = set()
    if old_mid and new_mid:
        matcher = SequenceMatcher(None, old_mid, new_mid, autojunk=False)
        for block in matcher.get_matching_blocks():
            for k in range(block.size):
                matched_old.add(prefix + block.a + k)
                matched_new.add(prefix + block.b + k)
    matched_old.update(range(prefix))
    matched_old.update(range(old_n - suffix, old_n))
    matched_new.update(range(prefix))
    matched_new.update(range(new_n - suffix, new_n))

    deletes = [i for i in range(old_n - 1, -1, -1) if i not in matched_old]
    inserts = [j for j in range(new_n) if j not in matched_new]
    return deletes, inserts
