"""wx.App() start-up on macOS (launch_mac), without creating an App: the
notification centre and NSApp are stubs and wx.App's own constructor is
replaced by one that replays what wxWidgets does during it."""

import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "macos"), os.path.join(ROOT, "client"), os.path.join(ROOT, ".pydeps")]

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS layer")

import wx  # noqa: E402

from winzapp_mac import launch_mac  # noqa: E402

NS_EVENT_TYPE_APPLICATION_DEFINED = 15


class _FakeCenter:
    def __init__(self):
        self.observers = {}

    def addObserverForName_object_queue_usingBlock_(self, name, obj, queue, block):
        token = object()
        self.observers[token] = (name, block)
        return token

    def removeObserver_(self, token):
        self.observers.pop(token, None)

    def post(self, name):
        for observed, block in list(self.observers.values()):
            if observed == name:
                block(None)


class _FakeApp:
    def __init__(self):
        self.posted = []

    def postEvent_atStart_(self, event, at_start):
        self.posted.append((event, at_start))


@pytest.fixture
def appkit(monkeypatch):
    center, app = _FakeCenter(), _FakeApp()
    monkeypatch.setattr(launch_mac, "_center", lambda: center)
    monkeypatch.setattr(launch_mac, "_app", lambda: app)
    return center, app


def _wx_app_init(center, steps):
    """Stands in for wx.App's constructor: the order of wxApp's start-up on
    the Mac (wxEntryStart, OnPreInit, [NSApp run] until launch finishes,
    OnInit)."""
    def fake_init(self, *a, **k):
        steps.append("init")
        launch_mac.on_pre_init(self)
        center.post("NSApplicationDidFinishLaunchingNotification")
        steps.append(launch_mac.on_init(self))
    return fake_init


class _Stub:
    pass


def test_finishing_launch_posts_one_wake_up_event_at_the_end_of_the_queue(appkit, monkeypatch):
    center, app = appkit
    monkeypatch.setitem(launch_mac._orig, "app_init", _wx_app_init(center, []))
    monkeypatch.setitem(launch_mac._orig, "on_pre_init", lambda self: None)
    monkeypatch.setitem(launch_mac._orig, "on_init", lambda self: True)
    launch_mac.app_init(_Stub())
    assert len(app.posted) == 1
    event, at_start = app.posted[0]
    assert event.type() == NS_EVENT_TYPE_APPLICATION_DEFINED
    assert at_start is False


def test_the_observer_is_removed_after_launch(appkit, monkeypatch):
    center, app = appkit
    monkeypatch.setitem(launch_mac._orig, "app_init", _wx_app_init(center, []))
    monkeypatch.setitem(launch_mac._orig, "on_pre_init", lambda self: None)
    monkeypatch.setitem(launch_mac._orig, "on_init", lambda self: True)
    launch_mac.app_init(_Stub())
    assert center.observers == {}
    center.post("NSApplicationDidFinishLaunchingNotification")   # a second one changes nothing
    assert len(app.posted) == 1


def test_the_observer_is_removed_when_construction_fails(appkit, monkeypatch):
    center, app = appkit

    def failing_init(self, *a, **k):
        raise SystemExit("This program needs access to the screen.")

    monkeypatch.setitem(launch_mac._orig, "app_init", failing_init)
    with pytest.raises(SystemExit):
        launch_mac.app_init(_Stub())
    assert center.observers == {}
    assert app.posted == []


def test_a_failed_post_never_reaches_appkit(appkit, monkeypatch, caplog):
    center, app = appkit

    def broken_post(event, at_start):
        raise RuntimeError("no NSApp")

    monkeypatch.setattr(app, "postEvent_atStart_", broken_post)
    steps = []
    monkeypatch.setitem(launch_mac._orig, "app_init", _wx_app_init(center, steps))
    monkeypatch.setitem(launch_mac._orig, "on_pre_init", lambda self: None)
    monkeypatch.setitem(launch_mac._orig, "on_init", lambda self: True)
    with caplog.at_level(logging.INFO):
        launch_mac.app_init(_Stub())
    assert steps == ["init", True]                      # start-up carried on
    assert "could not post the launch wake-up event" in caplog.text


def test_each_phase_of_wx_app_is_timed_in_order(appkit, monkeypatch, caplog):
    center, app = appkit
    monkeypatch.setitem(launch_mac._orig, "app_init", _wx_app_init(center, []))
    monkeypatch.setitem(launch_mac._orig, "on_pre_init", lambda self: None)
    monkeypatch.setitem(launch_mac._orig, "on_init", lambda self: True)
    with caplog.at_level(logging.INFO):
        launch_mac.app_init(_Stub())
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[STARTUP_TIMING] wx.App:")]
    phases = ["construction started", "toolkit initialised", "macOS finished launching",
              "OnInit reached", "construction finished"]
    assert len(lines) == len(phases)
    for line, phase in zip(lines, phases):
        assert phase in line
    assert "after launch finished" in lines[3]


def test_oninit_still_returns_what_wx_returns(monkeypatch):
    monkeypatch.setitem(launch_mac._orig, "on_init", lambda self: False)
    assert launch_mac.on_init(_Stub()) is False
    monkeypatch.setitem(launch_mac._orig, "on_init", lambda self: True)
    assert launch_mac.on_init(_Stub()) is True


def _fresh_install(monkeypatch):
    monkeypatch.setattr(wx.App, "__init__", wx.App.__init__)
    monkeypatch.setattr(wx.App, "OnPreInit", wx.App.OnPreInit)
    monkeypatch.setattr(wx.App, "OnInit", wx.App.OnInit)
    monkeypatch.setattr(launch_mac, "_orig", {})
    monkeypatch.setattr(launch_mac, "_installed", False)
    monkeypatch.setattr(launch_mac, "_post_needed", True)


def test_install_wraps_wx_app_and_keeps_the_originals(monkeypatch):
    _fresh_install(monkeypatch)
    original_init = wx.App.__init__
    launch_mac.install()
    launch_mac.install()          # installing twice wraps once
    assert wx.App.__init__ is launch_mac.app_init
    assert wx.App.OnPreInit is launch_mac.on_pre_init
    assert wx.App.OnInit is launch_mac.on_init
    assert launch_mac._orig["app_init"] is original_init


def test_installing_after_another_onpreinit_wrapper_keeps_it(monkeypatch):
    # accessibility_mac wraps OnPreInit the same way; whichever of the two
    # installs first, both must still run.
    _fresh_install(monkeypatch)
    calls = []
    monkeypatch.setattr(wx.App, "OnPreInit", lambda self: calls.append("other"))
    launch_mac.install()
    wx.App.OnPreInit(_Stub())
    assert calls == ["other"]


def test_accessibility_installed_after_launch_mac_keeps_both(monkeypatch):
    # The order winzapp_mac.install() uses: launch_mac first, then
    # accessibility_mac wraps the OnPreInit launch_mac installed.
    from winzapp_mac import accessibility_mac
    _fresh_install(monkeypatch)
    monkeypatch.setattr(wx.App, "FilterEvent", getattr(wx.App, "FilterEvent", None), raising=False)
    calls = []
    launch_mac.install()
    monkeypatch.setitem(launch_mac._orig, "on_pre_init", lambda self: calls.append("wx"))
    accessibility_mac._install_filter()
    stub = _Stub()
    stub.SetCallFilterEvent = lambda on: calls.append(("filter", on))
    wx.App.OnPreInit(stub)
    assert calls == ["wx", ("filter", True)]


@pytest.mark.parametrize("text, wx_posts", [
    ("4.2.4 osx-cocoa (phoenix) wxWidgets 3.2.8", False),
    ("4.3.0 osx-cocoa (phoenix) wxWidgets 3.3.1", False),
    ("4.3.0 osx-cocoa (phoenix) wxWidgets 3.3.2", True),
    ("5.0.0 osx-cocoa (phoenix) wxWidgets 3.4.0", True),
    ("garbled", False),
])
def test_the_workaround_is_only_for_wxwidgets_before_3_3_2(text, wx_posts):
    assert launch_mac.wx_posts_its_own_wake_event(text) is wx_posts


def test_a_fixed_wxwidgets_is_timed_but_not_woken(appkit, monkeypatch, caplog):
    center, app = appkit
    _fresh_install(monkeypatch)
    monkeypatch.setattr(wx, "version", lambda: "4.3.0 osx-cocoa (phoenix) wxWidgets 3.3.2")
    launch_mac.install()
    monkeypatch.setitem(launch_mac._orig, "app_init", _wx_app_init(center, []))
    monkeypatch.setitem(launch_mac._orig, "on_pre_init", lambda self: None)
    monkeypatch.setitem(launch_mac._orig, "on_init", lambda self: True)
    with caplog.at_level(logging.INFO):
        launch_mac.app_init(_Stub())
    assert app.posted == []
    assert "macOS finished launching; wx posts its own wake-up event" in caplog.text
