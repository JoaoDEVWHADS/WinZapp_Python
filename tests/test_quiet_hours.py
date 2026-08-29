"""Tests for core/quiet_hours.py — Windows Focus Assist, Do Not Disturb ("Não incomodar"),
and notification suppression detection.

Reported live: WinZapp's background-notification sound is played directly
through BASS, bypassing the WinRT toast pipeline Windows itself gates on
Focus Assist / DND / disabled notifications — so it kept playing with Focus Assist,
Do Not Disturb, or Windows notifications disabled. is_quiet_hours_active()
fixes that by consulting registry, WNF, WinRT, and SHQueryUserNotificationState,
isolated behind stubs so these tests never touch real Win32 APIs.
"""

from core import quiet_hours


class TestShouldSuppressNotificationSound:
    def test_quiet_time_is_suppressed(self):
        """QUNS_QUIET_TIME (6) is what Focus Assist (Priority only / Alarms
        only) surfaces as — the exact state this feature exists for."""
        assert quiet_hours.should_suppress_notification_sound(6) is True

    def test_busy_is_suppressed(self):
        assert quiet_hours.should_suppress_notification_sound(2) is True

    def test_fullscreen_d3d_is_suppressed(self):
        assert quiet_hours.should_suppress_notification_sound(3) is True

    def test_presentation_mode_is_suppressed(self):
        assert quiet_hours.should_suppress_notification_sound(4) is True

    def test_accepts_notifications_is_not_suppressed(self):
        assert quiet_hours.should_suppress_notification_sound(5) is False

    def test_not_present_is_not_suppressed(self):
        assert quiet_hours.should_suppress_notification_sound(1) is False

    def test_unknown_value_is_not_suppressed(self):
        """An unrecognized value must fail open, not be treated as quiet."""
        assert quiet_hours.should_suppress_notification_sound(999) is False


class TestIsQuietHoursActive:
    def test_true_when_registry_reports_disabled(self, monkeypatch):
        monkeypatch.setattr(quiet_hours, "_query_registry_notifications_disabled", lambda: True)
        monkeypatch.setattr(quiet_hours, "_query_wnf_quiet_hours", lambda: None)
        monkeypatch.setattr(quiet_hours, "_query_winrt_notification_policy", lambda: None)
        monkeypatch.setattr(quiet_hours, "_query_notification_state", lambda: 5)
        assert quiet_hours.is_quiet_hours_active() is True

    def test_true_when_wnf_reports_active(self, monkeypatch):
        monkeypatch.setattr(quiet_hours, "_query_registry_notifications_disabled", lambda: False)
        monkeypatch.setattr(quiet_hours, "_query_wnf_quiet_hours", lambda: True)
        monkeypatch.setattr(quiet_hours, "_query_winrt_notification_policy", lambda: None)
        monkeypatch.setattr(quiet_hours, "_query_notification_state", lambda: 5)
        assert quiet_hours.is_quiet_hours_active() is True

    def test_true_when_winrt_policy_reports_active(self, monkeypatch):
        monkeypatch.setattr(quiet_hours, "_query_registry_notifications_disabled", lambda: False)
        monkeypatch.setattr(quiet_hours, "_query_wnf_quiet_hours", lambda: False)
        monkeypatch.setattr(quiet_hours, "_query_winrt_notification_policy", lambda: True)
        monkeypatch.setattr(quiet_hours, "_query_notification_state", lambda: 5)
        assert quiet_hours.is_quiet_hours_active() is True

    def test_true_when_the_query_reports_quiet_time(self, monkeypatch):
        monkeypatch.setattr(quiet_hours, "_query_registry_notifications_disabled", lambda: False)
        monkeypatch.setattr(quiet_hours, "_query_wnf_quiet_hours", lambda: None)
        monkeypatch.setattr(quiet_hours, "_query_winrt_notification_policy", lambda: None)
        monkeypatch.setattr(quiet_hours, "_query_notification_state", lambda: 6)
        assert quiet_hours.is_quiet_hours_active() is True

    def test_false_when_all_report_accepts_notifications(self, monkeypatch):
        monkeypatch.setattr(quiet_hours, "_query_registry_notifications_disabled", lambda: False)
        monkeypatch.setattr(quiet_hours, "_query_wnf_quiet_hours", lambda: False)
        monkeypatch.setattr(quiet_hours, "_query_winrt_notification_policy", lambda: False)
        monkeypatch.setattr(quiet_hours, "_query_notification_state", lambda: 5)
        assert quiet_hours.is_quiet_hours_active() is False

    def test_fails_open_when_queries_fail(self, monkeypatch):
        """When all API calls fail (off-Windows, missing DLL, error)
        — must fall back to "not quiet" (sound still plays)."""
        monkeypatch.setattr(quiet_hours, "_query_registry_notifications_disabled", lambda: False)
        monkeypatch.setattr(quiet_hours, "_query_wnf_quiet_hours", lambda: None)
        monkeypatch.setattr(quiet_hours, "_query_winrt_notification_policy", lambda: None)
        monkeypatch.setattr(quiet_hours, "_query_notification_state", lambda: None)
        assert quiet_hours.is_quiet_hours_active() is False


class TestQueryFunctionsOffWindows:
    def test_returns_none_off_windows(self, monkeypatch):
        monkeypatch.setattr(quiet_hours.sys, "platform", "linux")
        assert quiet_hours._query_notification_state() is None
        assert quiet_hours._query_wnf_quiet_hours() is None
        assert quiet_hours._query_registry_notifications_disabled() is False
        assert quiet_hours._query_winrt_notification_policy() is None


class TestWnfQuietHours:
    def test_queries_the_active_quiet_hours_profile(self, monkeypatch):
        seen = []
        monkeypatch.setattr(quiet_hours.sys, "platform", "win32")
        monkeypatch.setattr(
            quiet_hours,
            "_query_wnf_state",
            lambda low, high: seen.append((low, high)) or 1,
        )

        assert quiet_hours._query_wnf_quiet_hours() is True
        assert seen == [(0xA3BF1C75, 0x0D83063E)]

    def test_zero_profile_means_dnd_is_off(self, monkeypatch):
        monkeypatch.setattr(quiet_hours.sys, "platform", "win32")
        monkeypatch.setattr(quiet_hours, "_query_wnf_state", lambda *_: 0)
        assert quiet_hours._query_wnf_quiet_hours() is False

    def test_nt_query_wnf_state_data_uses_six_argument_abi(self, monkeypatch):
        import ctypes

        calls = []

        class FakeQuery:
            argtypes = None
            restype = None

            def __call__(self, state, type_id, scope, stamp, buffer, size):
                calls.append((type_id, scope))
                ctypes.cast(buffer, ctypes.POINTER(ctypes.c_uint32)).contents.value = 2
                ctypes.cast(size, ctypes.POINTER(ctypes.c_uint32)).contents.value = 4
                return 0

        class FakeNtdll:
            NtQueryWnfStateData = FakeQuery()

        monkeypatch.setattr(quiet_hours.sys, "platform", "win32")
        monkeypatch.setattr(ctypes, "WinDLL", lambda *_: FakeNtdll(), raising=False)

        assert quiet_hours._query_wnf_state(0xA3BF1C75, 0x0D83063E) == 2
        assert calls == [(None, None)]


class TestWinRtNotificationSetting:
    @staticmethod
    def _module_with_setting(value):
        class Setting:
            def __init__(self, setting_value):
                self.value = setting_value

        class Notifier:
            setting = Setting(value)

        class Manager:
            @staticmethod
            def create_toast_notifier(app_id):
                assert app_id == "WinZapp"
                return Notifier()

        class Module:
            ToastNotificationManager = Manager

        return Module()

    def test_global_or_user_block_suppresses_sound(self, monkeypatch):
        monkeypatch.setattr(quiet_hours.sys, "platform", "win32")
        module = self._module_with_setting(2)
        monkeypatch.setattr(quiet_hours.importlib, "import_module", lambda *_: module)
        assert quiet_hours._query_winrt_notification_policy() is True

    def test_enabled_notifications_do_not_suppress_sound(self, monkeypatch):
        monkeypatch.setattr(quiet_hours.sys, "platform", "win32")
        module = self._module_with_setting(0)
        monkeypatch.setattr(quiet_hours.importlib, "import_module", lambda *_: module)
        assert quiet_hours._query_winrt_notification_policy() is False

    def test_falls_back_to_winsdk_module(self, monkeypatch):
        monkeypatch.setattr(quiet_hours.sys, "platform", "win32")
        module = self._module_with_setting(1)
        imported = []

        def fake_import(name):
            imported.append(name)
            if name.startswith("winrt."):
                raise ImportError(name)
            return module

        monkeypatch.setattr(quiet_hours.importlib, "import_module", fake_import)
        assert quiet_hours._query_winrt_notification_policy() is True
        assert imported == [
            "winrt.windows.ui.notifications",
            "winsdk.windows.ui.notifications",
        ]


class TestCloudStoreQuietHours:
    def test_priority_only_is_suppressed(self):
        data = b"prefix" + "Microsoft.QuietHoursProfile.PriorityOnly".encode("utf-16-le")
        assert quiet_hours._parse_cloudstore_quiet_hours(data) is True

    def test_unrestricted_is_not_suppressed(self):
        data = "Microsoft.QuietHoursProfile.Unrestricted".encode("utf-16-le")
        assert quiet_hours._parse_cloudstore_quiet_hours(data) is False

    def test_unknown_blob_is_inconclusive(self):
        assert quiet_hours._parse_cloudstore_quiet_hours(b"\x02\x00unknown") is None
