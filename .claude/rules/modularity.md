---
paths:
  - "client/main.py"
  - "client/main_window/*.py"
  - "client/ui/conversations.py"
  - "client/ui/conversation_panel/*.py"
  - "client/status_panel.py"
  - "client/status_tab/*.py"
---

# Modularity

**Read the map in `client/main_window/__init__.py` / `client/ui/conversation_panel/__init__.py` / `client/status_tab/__init__.py` before adding code here.** Short form:

`MainWindow`, `ConversationsPanel` and `StatusPanel` are assembled from one mixin per responsibility. New code goes into the module that owns the responsibility, or a new module in that package — never back into `main.py`/`conversations.py`/`status_panel.py`, and never into whichever module happens to be open. Pure logic (no `self`, no wx) goes into a plain function with a direct test. A mixin never imports `main`. A module global is looked up where the method is *defined*: tests patch it with `tests/god_modules.py`'s `patch_main_global()`/`patch_conversations_global()`/`patch_status_panel_global()`, and read source with `main_window_source()`/`main_window_method_source()`. Size budgets live in `tests/test_god_file_split_structure.py`; split, don't raise them.
