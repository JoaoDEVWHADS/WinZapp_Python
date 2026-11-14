"""How much log.log records: Settings > Advanced > Log level.

setup_logging() starts every run at INFO, before the settings exist; once
they are loaded MainWindow calls apply_log_level(), and the Settings dialog
calls it again on OK/Apply, so a change takes effect at once, with no restart.

Per account: each account is its own process with its own log.log, so the
account being diagnosed can log in detail while the others stay quiet.

Only the root logger moves. The noisy libraries setup_logging() pins at ERROR
(urllib3, socketio...) keep their own level, so DEBUG shows WinZapp's own
detail without drowning it in HTTP chatter.
"""

import logging

SECTION = "advanced"
KEY = "log_level"

#: The levels offered, in the order the Settings choice lists them.
LEVELS = ("debug", "info", "warning", "error")

#: What WinZapp always logged at, and what an unknown value falls back to.
DEFAULT = "info"

_NUMERIC = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


def level_name(settings) -> str:
    """The configured level's name, DEFAULT for a missing or unknown one
    (a hand-edited settings.json must not silence the log)."""
    section = (settings or {}).get(SECTION) if isinstance(settings, dict) else None
    value = section.get(KEY) if isinstance(section, dict) else None
    if isinstance(value, str) and value.strip().lower() in _NUMERIC:
        return value.strip().lower()
    return DEFAULT


def numeric_level(name: str) -> int:
    """logging's number for a level name; INFO for an unknown one."""
    return _NUMERIC.get((name or "").strip().lower(), _NUMERIC[DEFAULT])


def apply_log_level(settings, logger=None) -> str:
    """Set the root logger (or *logger*) to the configured level and answer
    its name. Logged at WARNING so the change is in log.log at any level."""
    name = level_name(settings)
    target = logger if logger is not None else logging.getLogger()
    if target.level != numeric_level(name):
        target.setLevel(numeric_level(name))
        logging.warning("Log level set to %s", name.upper())
    return name
