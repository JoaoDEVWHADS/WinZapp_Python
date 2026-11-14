"""wx.App() on the Mac: time its phases, and end its launch wait promptly.

wxWidgets 3.2 (src/osx/cocoa/utils.mm) starts the app by running
[NSApp run] inside wxApp::CallOnInit() until applicationDidFinishLaunching:
calls [NSApp stop:]; only then is OnInit() called and wx.App() returns.
stop: takes effect only once the run loop has handled one more event. wx
posts a dummy event before [NSApp run], but AppKit dequeues it while launch
is still in progress, so when the did-finish notification arrives the queue
is empty and wx.App() sits idle until some unrelated event comes in. A
launch measured 4.1 s inside wx.App(), 3.6 s of it with the main thread
doing nothing; how long depends on what event happens to wake it.

wxWidgets 3.3.2 fixed this by posting a second dummy event in
applicationDidFinishLaunching: (before stop:). wxPython 4.2.x ships
wxWidgets 3.2, so the same event is posted here, from an observer of the
same notification. Posted to the end of the queue, like wx's own wake-up
events (wxGUIEventLoop::WakeUp), it is harmless if the loop has already
stopped: the main loop later dispatches it and nothing handles it. With
wxWidgets 3.3.2 or later wx posts it itself, and only the timing remains.

The [STARTUP_TIMING] lines bracket each phase, so log.log shows whether the
wait is gone: "OnInit reached" should follow "macOS finished launching"
within milliseconds.
"""

import logging
import re
import time

import wx

# wx.App's methods as install() found them. Read there, not at import:
# another module (accessibility_mac) wraps OnPreInit too, and a copy taken
# at import would drop its wrapper if that module installs first.
_orig = {}
_installed = False

# The first wxWidgets with the second dummy event in applicationDidFinishLaunching:.
FIXED_IN = (3, 3, 2)
_post_needed = True

# Times of the wx.App() being constructed; one App per process.
_timing = {"started": None, "launched": None}


def _center():
    from Foundation import NSNotificationCenter
    return NSNotificationCenter.defaultCenter()


def _app():
    from AppKit import NSApp
    return NSApp()


def _since_start():
    return time.perf_counter() - (_timing["started"] or time.perf_counter())


def wxwidgets_version(version_text):
    """(major, minor, release) of the wxWidgets in wx.version()'s text
    ("4.2.4 osx-cocoa (phoenix) wxWidgets 3.2.8"), or None. wx.VERSION is
    wxPython's own version, not wxWidgets'."""
    match = re.search(r"wxWidgets (\d+)\.(\d+)\.(\d+)", version_text or "")
    return tuple(int(part) for part in match.groups()) if match else None


def wx_posts_its_own_wake_event(version_text):
    version = wxwidgets_version(version_text)
    return version is not None and version >= FIXED_IN


def post_wake_event():
    """Queue an empty application-defined event at the end of the queue, so
    a run loop told to stop: notices it and returns."""
    from AppKit import NSEvent, NSEventTypeApplicationDefined
    event = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
        NSEventTypeApplicationDefined, (0.0, 0.0), 0, 0, 0, None, 0, 0, 0)
    _app().postEvent_atStart_(event, False)


def _watch_launch():
    """Observe NSApplicationDidFinishLaunchingNotification once; returns
    the observer token, or None when it could not be registered."""
    holder = {}

    def did_finish_launching(notification):
        # An exception escaping into AppKit's notification dispatch would
        # take the launch down with it, so nothing leaves this block.
        try:
            _unwatch(holder.pop("token", None))
            _timing["launched"] = time.perf_counter()
            if _post_needed:
                post_wake_event()
            logging.info("[STARTUP_TIMING] wx.App: +%.3fs macOS finished launching%s", _since_start(),
                         "; wake-up event posted" if _post_needed else "; wx posts its own wake-up event")
        except Exception:
            logging.exception("[launch_mac] could not post the launch wake-up event")

    try:
        from AppKit import NSApplicationDidFinishLaunchingNotification
        holder["token"] = _center().addObserverForName_object_queue_usingBlock_(
            NSApplicationDidFinishLaunchingNotification, None, None, did_finish_launching)
    except Exception:
        logging.exception("[launch_mac] could not observe the end of launch")
        return None
    return holder["token"]


def _unwatch(token):
    if token is None:
        return
    try:
        _center().removeObserver_(token)
    except Exception:
        logging.debug("[launch_mac] could not remove the launch observer", exc_info=True)


def app_init(self, *args, **kwargs):
    _timing["started"] = time.perf_counter()
    _timing["launched"] = None
    logging.info("[STARTUP_TIMING] wx.App: construction started")
    token = _watch_launch()
    try:
        _orig["app_init"](self, *args, **kwargs)
    finally:
        # Normally already gone (the observer removes itself); this covers a
        # constructor that failed before macOS finished launching.
        _unwatch(token)
    logging.info("[STARTUP_TIMING] wx.App: +%.3fs construction finished", _since_start())


def on_pre_init(self):
    # Called after wxEntryStart(), right before CallOnInit() enters [NSApp run].
    logging.info("[STARTUP_TIMING] wx.App: +%.3fs toolkit initialised, waiting for macOS to finish launching",
                 _since_start())
    return _orig["on_pre_init"](self)


def on_init(self):
    launched = _timing["launched"]
    if launched is None:
        logging.info("[STARTUP_TIMING] wx.App: +%.3fs OnInit reached (launch notification not seen)",
                     _since_start())
    else:
        logging.info("[STARTUP_TIMING] wx.App: +%.3fs OnInit reached, %.3fs after launch finished",
                     _since_start(), time.perf_counter() - launched)
    return _orig["on_init"](self)


def install():
    global _installed, _post_needed
    if _installed:
        return
    _installed = True
    # Not logged here: install() runs before WinZapp's setup_logging(), so
    # the launch-finished line in did_finish_launching says which case ran.
    if wx_posts_its_own_wake_event(wx.version()):
        _post_needed = False
    _orig["app_init"] = wx.App.__init__
    _orig["on_pre_init"] = wx.App.OnPreInit
    _orig["on_init"] = wx.App.OnInit
    wx.App.__init__ = app_init
    wx.App.OnPreInit = on_pre_init
    wx.App.OnInit = on_init
