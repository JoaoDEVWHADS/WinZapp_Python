---
paths:
  - "client/changelog_*.txt"
---

# Changelogs

**Read `docs/reference/writing-changelogs.md` before changing these files.** Short form:

The unit is stable-to-stable: a bug that only existed in an alpha is not news, a fix to a feature arriving in the same release is not news. Verify with `git show <previous stable tag>:<file>`. Every locale in `language_map.json` has a file (`tests/test_changelogs_in_sync.py`); same items, same order.
