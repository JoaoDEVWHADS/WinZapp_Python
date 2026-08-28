"""Windows Focus Assist, Do Not Disturb ("Não incomodar"), and Notifications detection.

Detects when Windows suppresses toast notifications and sounds:
1. Windows 11 "Não Incomodar" (Do Not Disturb) and Focus Assist via:
   - WNF (Windows Notification Facility) real-time state: WNF_SHEL_QUIETHOURS_ACTIVE
   - WinRT ToastNotificationManagerPolicy
   - Windows Registry (FocusAssistMode / QuietHours)
2. Windows Notifications Disabled globally ("Obter notificações de apps e outros remetentes" desativado) via:
   - HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PushNotifications (ToastEnabled == 0)
   - HKCU/HKLM Group Policy (NoToastApplicationNotification == 1)
   - Notification Settings (NOC_GLOBAL_SETTING_TOASTS_ENABLED == 0)
   - WinRT ToastNotificationManagerPolicy (status == Disabled)
3. Fullscreen DirectX games, presentation mode, or busy state via:
   - Win32 SHQueryUserNotificationState (shell32)

Deliberately NOT applied to message_current_sound (a message arriving in the
conversation the user already has open and focused) or to incoming-call
alerts — Focus Assist / DND is about notifications competing for attention while
the user is doing something else.
"""

import sys
from typing import Optional

# QUERY_USER_NOTIFICATION_STATE values (shellapi.h)
_QUNS_NOT_PRESENT = 1
_QUNS_BUSY = 2
_QUNS_RUNNING_D3D_FULL_SCREEN = 3
_QUNS_PRESENTATION_MODE = 4
_QUNS_ACCEPTS_NOTIFICATIONS = 5
_QUNS_QUIET_TIME = 6
_QUNS_APP = 7

# States in which Windows would itself suppress a toast's sound/banner: a
# fullscreen app/game, a presentation, or Focus Assist (both "Priority only"
# and "Alarms only" surface here as QUNS_QUIET_TIME — Windows doesn't expose
# a finer-grained value through this API).
_SUPPRESSED_STATES = {
    _QUNS_BUSY, _QUNS_RUNNING_D3D_FULL_SCREEN,
    _QUNS_PRESENTATION_MODE, _QUNS_QUIET_TIME,
}


def should_suppress_notification_sound(state: int) -> bool:
    """Pure mapping from a QUERY_USER_NOTIFICATION_STATE value to whether the
    background-notification sound should be skipped. Split out from
    is_quiet_hours_active() so the decision table is testable without
    touching the real Win32 API."""
    return state in _SUPPRESSED_STATES


def _query_notification_state():
    """Raw SHQueryUserNotificationState call, isolated in its own function so
    tests can stub it without reaching into ctypes.windll. Returns None on
    any failure (off-Windows, API error, missing DLL, ...)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        state = ctypes.c_int()
        result = ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
        if result != 0:  # S_OK == 0
            return None
        return state.value
    except Exception:
        return None


def _query_wnf_quiet_hours() -> Optional[bool]:
    """Query Windows Notification Facility (WNF) for real-time Focus Assist /
    Do Not Disturb state in Windows 10 (1803+) and Windows 11.

    WNF_SHEL_QUIETHOURS_ACTIVE (0x0D83063EA3B64835) is the internal state name
    used by the Windows Shell / Action Center to toggle 'Não Incomodar'.
    Buffer contains a DWORD:
      0 = Inactive / Off (notifications permitted)
      1 = Priority Only (suppressed)
      2 = Alarms Only / Do Not Disturb (suppressed)
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        ntdll = getattr(ctypes.windll, "ntdll", None)
        if not ntdll or not hasattr(ntdll, "RtlQueryWnfStateData"):
            return None

        state_name = ctypes.c_uint64(0x0D83063EA3B64835)
        change_stamp = wintypes.DWORD(0)
        buffer = wintypes.DWORD(0)
        buffer_size = wintypes.ULONG(ctypes.sizeof(buffer))

        status = ntdll.RtlQueryWnfStateData(
            ctypes.byref(state_name),
            None,
            None,
            ctypes.byref(change_stamp),
            ctypes.byref(buffer),
            ctypes.byref(buffer_size),
        )
        if status == 0:  # STATUS_SUCCESS
            return buffer.value > 0
    except Exception:
        pass
    return None


def _query_registry_notifications_disabled() -> bool:
    """Check Windows registry for whether notifications are disabled globally
    or in 'Não incomodar' / Focus Assist mode:
    1. 'Obter notificações de apps e outros remetentes' disabled:
       HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PushNotifications -> ToastEnabled == 0
    2. Group Policy:
       HKCU/HKLM\\Software\\Policies\\Microsoft\\Windows\\CurrentVersion\\PushNotifications -> NoToastApplicationNotification == 1
    3. Action Center global toasts disabled:
       HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Notifications\\Settings -> NOC_GLOBAL_SETTING_TOASTS_ENABLED == 0
    4. Focus Assist / DND registry values:
       HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\FocusAssist -> FocusAssistMode > 0
       HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Notifications\\QuietHours -> Profile > 0 or Enabled == 1
    """
    if sys.platform != "win32":
        return False
    try:
        import winreg

        # 1. Global toggle: "Obter notificações de apps e outros remetentes"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\PushNotifications") as k:
                val, _ = winreg.QueryValueEx(k, "ToastEnabled")
                if val == 0:
                    return True
        except OSError:
            pass

        # 2. Group Policy
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, r"Software\Policies\Microsoft\Windows\CurrentVersion\PushNotifications") as k:
                    val, _ = winreg.QueryValueEx(k, "NoToastApplicationNotification")
                    if val == 1:
                        return True
            except OSError:
                pass

        # 3. Action Center global setting
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings") as k:
                val, _ = winreg.QueryValueEx(k, "NOC_GLOBAL_SETTING_TOASTS_ENABLED")
                if val == 0:
                    return True
        except OSError:
            pass

        # 4. App-specific toggle for WinZapp in Windows Settings
        for app_key in (r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings\WinZapp",):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, app_key) as k:
                    val, _ = winreg.QueryValueEx(k, "Enabled")
                    if val == 0:
                        return True
            except OSError:
                pass

        # 5. Focus Assist Mode in registry
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\FocusAssist") as k:
                val, _ = winreg.QueryValueEx(k, "FocusAssistMode")
                if val in (1, 2):
                    return True
        except OSError:
            pass

        # 6. QuietHours profile/enabled in registry
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Notifications\QuietHours") as k:
                try:
                    profile, _ = winreg.QueryValueEx(k, "Profile")
                    if profile > 0:
                        return True
                except OSError:
                    pass
                try:
                    enabled, _ = winreg.QueryValueEx(k, "Enabled")
                    if enabled == 1:
                        return True
                except OSError:
                    pass
        except OSError:
            pass

    except Exception:
        pass
    return False


def _query_winrt_notification_policy() -> Optional[bool]:
    """Query WinRT ToastNotificationManagerPolicy if available on Windows 10/11.
    Values of ToastNotificationMode:
      0 = Unrestricted (allowed)
      1 = PriorityOnly (suppressed)
      2 = AlarmsOnly (suppressed)
      3 = DoNotDisturb (suppressed)
      4 = Disabled (suppressed)
    """
    if sys.platform != "win32":
        return None
    try:
        try:
            from winsdk.windows.ui.notifications import ToastNotificationManagerPolicy
            policy = ToastNotificationManagerPolicy.get_default()
            if policy is not None:
                return int(policy.notification_status) != 0
        except ImportError:
            from winrt.windows.ui.notifications import ToastNotificationManagerPolicy
            policy = ToastNotificationManagerPolicy.get_default()
            if policy is not None:
                return int(policy.notification_status) != 0
    except Exception:
        pass
    return None


def is_quiet_hours_active() -> bool:
    """True if Windows is currently in a state where toast notifications / sounds
    should be suppressed (Do Not Disturb / "Não Incomodar", Focus Assist,
    notifications toggled off in Windows Settings, fullscreen games, presentation mode).

    Fails open (False) off-Windows or on any API failure — an API failure is
    a reason to fall back to the pre-existing behavior (always play), not to
    go silent for a reason nobody can see.
    """
    # 1. Check if notifications are disabled in Windows Settings (Registry)
    if _query_registry_notifications_disabled():
        return True

    # 2. Check WNF state for real-time Windows 10/11 Do Not Disturb / Focus Assist
    wnf_state = _query_wnf_quiet_hours()
    if wnf_state is not None:
        if wnf_state is True:
            return True

    # 3. Check WinRT notification policy (if accessible)
    winrt_policy = _query_winrt_notification_policy()
    if winrt_policy is not None:
        if winrt_policy is True:
            return True

    # 4. Check legacy Win32 SHQueryUserNotificationState (fullscreen games, presentation mode)
    state = _query_notification_state()
    if state is not None and should_suppress_notification_sound(state):
        return True

    return False

