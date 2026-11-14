"""Installation timings without logging commands, tokens or HTTP payloads."""

from functools import wraps
import logging
import time


def timed_call(step, function, *args, **kwargs):
    started = time.monotonic()
    logging.info("[api-timing] step=%s event=start", step)
    outcome = "exception"
    try:
        result = function(*args, **kwargs)
        verdict = result[0] if isinstance(result, tuple) and result else result
        outcome = "false" if verdict is False else "returned"
        return result
    finally:
        logging.info("[api-timing] step=%s event=end elapsed_s=%.3f outcome=%s",
                     step, time.monotonic() - started, outcome)


def timed_step(step):
    def decorate(function):
        @wraps(function)
        def measured(*args, **kwargs):
            return timed_call(step, function, *args, **kwargs)
        return measured
    return decorate


def npm_step(command):
    if "exec" in command and "puppeteer" in command:
        return "browser_cli"
    if "install" in command:
        return "npm_install"
    if "run" in command:
        script = command[command.index("run") + 1:][:1]
        if script == ["build"]:
            return "npm_build"
        if script == ["db:generate"]:
            return "db_generate"
    return "subprocess"


def timed_subprocess(function):
    @wraps(function)
    def measured(self, cmd, *args, **kwargs):
        return timed_call(npm_step(cmd), function, self, cmd, *args, **kwargs)
    return measured
