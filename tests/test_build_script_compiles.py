"""build.py is only ever run for real by a release build, so a syntax slip in it
(a step added without ever being run) would surface there. Compile it here."""

import os


def test_build_py_compiles():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build.py")
    with open(path, encoding="utf-8") as stream:
        compile(stream.read(), path, "exec")
