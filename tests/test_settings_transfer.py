"""What travels when settings are exported, and what an import is allowed to
apply (core/settings_transfer.py).

settings.json holds the person's preferences and this install's own state in
one file: the WhatsApp login, what this account has synced, per-JID clear
cutoffs and sound overrides, the Node port this account was given. Copying the
whole file to another install is what the user would otherwise have to do, and
it either does nothing or breaks that install.
"""

import copy

import pytest

from core import settings_transfer as transfer
from core.utils import DEFAULT_SETTINGS


def _settings():
    """A plausible settings dict: shipped defaults plus the state an install
    accumulates around them."""
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings["privateinfo"] = {"WA_token_protected": "gAAAA-secret", "paired": True}
    settings["status"]["messages_set_completed"] = True
    settings["status_panel"]["liked_status_ids"] = ["A@broadcast"]
    settings["cleared_chats"] = {"5511@s.whatsapp.net": 1789000000}
    settings["cleared_starred_chats"] = {"5511@s.whatsapp.net": True}
    settings["conversation_sounds"] = {"5511@s.whatsapp.net": "ding.wav"}
    settings["connection"].update({"wpp_port": 6412, "wpp_api_key": "install-key"})
    settings["general"].update({
        "language": "pt-BR", "first_run": False, "autostart": True,
        "quick_tip_shown": True, "voice_message_mode_default_migrated": True,
    })
    settings["files"]["save_dialog_last_folder"] = r"D:\\Downloads"
    return settings


class TestWhatStaysBehind:
    @pytest.mark.parametrize("section", sorted(transfer.EXCLUDED_SECTIONS))
    def test_no_section_of_this_install_is_exported(self, section):
        assert section not in transfer.exportable_settings(_settings())

    def test_the_whatsapp_login_never_reaches_the_file(self):
        """A settings file the user may mail to themselves must not carry the
        token: it is the account, and it is not even plaintext in settings.json."""
        exported = transfer.build_export(_settings())
        assert "secret" not in repr(exported)

    @pytest.mark.parametrize("section, key", sorted(transfer.EXCLUDED_KEYS))
    def test_no_key_of_this_install_is_exported(self, section, key):
        exported = transfer.exportable_settings(_settings())
        assert key not in exported.get(section, {})

    def test_migration_flags_stay_behind(self):
        """Carrying one would stop the migration running on the other install."""
        exported = transfer.exportable_settings(_settings())
        assert "voice_message_mode_default_migrated" not in exported["general"]

    def test_the_preferences_do_travel(self):
        exported = transfer.exportable_settings(_settings())
        assert exported["general"]["language"] == "pt-BR"
        assert exported["user_interface"]["messages_page_size"] == 200
        # The bundled API's address is this install's own (CUSTOM_API_KEYS).
        assert "wpp_server" not in exported["connection"]
        assert exported["profile_backup"]["close_snapshot_min_hours"] == 24

    def test_a_section_this_build_never_declared_is_not_exported(self):
        """The export is the same whitelist as the import: a section written
        straight into self.settings at runtime — which is how privateinfo and
        cleared_chats arrived — must not reach the file just because nobody
        remembered to name it."""
        settings = _settings()
        settings["some_future_state"] = {"account_only": True}
        assert "some_future_state" not in transfer.exportable_settings(settings)

    def test_the_source_settings_are_not_touched(self):
        settings = _settings()
        before = copy.deepcopy(settings)
        transfer.exportable_settings(settings)
        assert settings == before


class TestTheApiThisAccountTalksTo:
    """WinZapp’s own bundled API is per install: the port is allocated per
    account and re-resolved at every launch, and the key is the local REST
    credential. A custom API is the opposite — a server the person runs, which
    is the whole reason they would want it on the other computer too."""

    def _custom(self):
        settings = _settings()
        settings["connection"].update({
            "wpp_custom_api": True, "wpp_server": "https://api.exemplo.com",
            "wpp_ws_server": "wss://api.exemplo.com", "wpp_port": 8443,
            "wpp_api_key": "minha-chave",
        })
        return settings

    def test_the_bundled_api_keeps_its_port_and_key_here(self):
        exported = transfer.exportable_settings(_settings())
        assert "wpp_port" not in exported["connection"]
        assert "wpp_api_key" not in exported["connection"]

    def test_a_custom_api_travels_whole(self):
        exported = transfer.exportable_settings(self._custom())
        assert exported["connection"] == {
            "wpp_custom_api": True, "wpp_server": "https://api.exemplo.com",
            "wpp_ws_server": "wss://api.exemplo.com", "wpp_port": 8443,
            "wpp_api_key": "minha-chave",
        }

    def test_importing_one_points_this_install_at_the_same_server(self):
        incoming, error = transfer.read_export(transfer.build_export(self._custom()))
        assert error == ""
        merged, applied, ignored = transfer.merge_settings(_settings(), incoming)
        assert merged["connection"]["wpp_custom_api"] is True
        assert merged["connection"]["wpp_server"] == "https://api.exemplo.com"
        assert merged["connection"]["wpp_port"] == 8443
        assert merged["connection"]["wpp_api_key"] == "minha-chave"
        assert applied and ignored == []

    def test_a_file_on_the_bundled_api_never_moves_this_port(self):
        """Another machine’s local port is at best overwritten at the next
        launch and at worst claimed by a second account here."""
        incoming = {"connection": {"wpp_custom_api": False, "wpp_port": 6399,
                                   "wpp_api_key": "theirs"}}
        current = _settings()
        merged, applied, ignored = transfer.merge_settings(current, incoming)
        assert merged["connection"]["wpp_port"] == current["connection"]["wpp_port"]
        assert merged["connection"]["wpp_api_key"] == current["connection"]["wpp_api_key"]
        assert applied == 1        # only wpp_custom_api itself
        assert sorted(ignored) == ["connection.wpp_api_key", "connection.wpp_port"]

    def test_a_file_on_the_bundled_api_cannot_set_the_server_either(self):
        """Every request carries the session token to wpp_server. A file that
        says "bundled API" while naming a server used to move it anyway, with
        nothing on screen to say so."""
        incoming = {"connection": {"wpp_custom_api": False,
                                   "wpp_server": "http://atacante.exemplo",
                                   "wpp_ws_server": "ws://atacante.exemplo"}}
        current = _settings()
        merged, _applied, ignored = transfer.merge_settings(current, incoming)
        assert merged["connection"]["wpp_server"] == current["connection"]["wpp_server"]
        assert merged["connection"]["wpp_ws_server"] == current["connection"]["wpp_ws_server"]
        assert "connection.wpp_server" in ignored
        assert transfer.api_change(current, incoming) is None

    def test_the_bundled_api_exports_no_address(self):
        exported = transfer.exportable_settings(_settings())
        assert "wpp_server" not in exported["connection"]
        assert "wpp_ws_server" not in exported["connection"]

    def test_api_change_names_the_server_a_custom_file_moves_to(self):
        incoming, _ = transfer.read_export(transfer.build_export(self._custom()))
        assert transfer.api_change(_settings(), incoming) == "https://api.exemplo.com"

    def test_api_change_is_none_when_nothing_about_the_api_changes(self):
        custom = self._custom()
        incoming, _ = transfer.read_export(transfer.build_export(custom))
        assert transfer.api_change(custom, incoming) is None

    def test_declining_keeps_the_connection_and_still_merges_the_rest(self):
        incoming, _ = transfer.read_export(transfer.build_export(self._custom()))
        current = _settings()
        merged, applied, ignored = transfer.merge_settings(
            current, incoming, include_connection=False)
        assert merged["connection"] == current["connection"]
        assert "connection" in ignored
        assert applied

    def test_uses_custom_api_reads_the_flag_it_is_given(self):
        assert transfer.uses_custom_api(self._custom()) is True
        assert transfer.uses_custom_api(_settings()) is False
        assert transfer.uses_custom_api({}) is False
        assert transfer.uses_custom_api(None) is False
        assert transfer.uses_custom_api({"connection": "x"}) is False


class TestTheFileItself:
    def test_it_says_what_it_is(self):
        payload = transfer.build_export(_settings(), app_version="1.1.2.0")
        assert payload["format"] == transfer.EXPORT_FORMAT
        assert payload["version"] == transfer.EXPORT_VERSION
        assert payload["app_version"] == "1.1.2.0"
        assert payload["settings"]["general"]["language"] == "pt-BR"

    def test_an_export_reads_back(self):
        settings, error = transfer.read_export(transfer.build_export(_settings()))
        assert error == "" and settings["general"]["language"] == "pt-BR"

    @pytest.mark.parametrize("payload", [
        {}, {"format": "something-else", "settings": {}}, [], "x", None,
        {"format": transfer.EXPORT_FORMAT, "version": 1, "settings": "nope"},
        {"format": transfer.EXPORT_FORMAT, "version": "abc", "settings": {}},
    ])
    def test_anything_that_is_not_an_export_is_refused(self, payload):
        settings, error = transfer.read_export(payload)
        assert settings is None and error == "settings_import_not_an_export"

    def test_a_newer_format_says_so_instead_of_guessing(self):
        payload = transfer.build_export(_settings())
        payload["version"] = transfer.EXPORT_VERSION + 1
        settings, error = transfer.read_export(payload)
        assert settings is None and error == "settings_import_newer_version"


class TestImporting:
    def _merge(self, incoming, current=None):
        return transfer.merge_settings(current or _settings(), incoming)

    def test_a_value_is_applied(self):
        merged, applied, ignored = self._merge(
            {"user_interface": {"messages_page_size": 50}})
        assert merged["user_interface"]["messages_page_size"] == 50
        assert applied == 1 and ignored == []

    def test_everything_the_file_does_not_mention_is_kept(self):
        current = _settings()
        merged, _applied, _ignored = self._merge(
            {"user_interface": {"messages_page_size": 50}}, current)
        assert merged["general"]["language"] == "pt-BR"
        assert merged["privateinfo"] == current["privateinfo"]
        assert merged["cleared_chats"] == current["cleared_chats"]

    def test_the_current_settings_are_not_modified_in_place(self):
        current = _settings()
        before = copy.deepcopy(current)
        self._merge({"user_interface": {"messages_page_size": 50}}, current)
        assert current == before

    @pytest.mark.parametrize("incoming, ignored_name", [
        ({"privateinfo": {"paired": False}}, "privateinfo"),
        ({"cleared_chats": {"x@s.whatsapp.net": 1}}, "cleared_chats"),
        ({"general": {"autostart": True}}, "general.autostart"),
        ({"general": {"first_run": True}}, "general.first_run"),
        ({"general": {"spell_check_mode_migrated": True}}, "general.spell_check_mode_migrated"),
        ({"files": {"save_dialog_last_folder": "D:\\\\x"}}, "files.save_dialog_last_folder"),
    ], ids=lambda v: v if isinstance(v, str) else "incoming")
    def test_what_belongs_to_an_install_is_never_read_back(self, incoming, ignored_name):
        """Even a hand-made file naming these cannot reach settings.json."""
        current = _settings()
        merged, applied, ignored = self._merge(incoming, current)
        assert applied == 0 and ignored == [ignored_name]
        assert merged == current

    def test_a_setting_this_build_does_not_have_is_ignored(self):
        merged, applied, ignored = self._merge(
            {"user_interface": {"from_the_future": 1}, "future_section": {"a": 1}})
        assert applied == 0
        assert sorted(ignored) == ["future_section", "user_interface.from_the_future"]
        assert "from_the_future" not in merged["user_interface"]

    @pytest.mark.parametrize("value", ["200", 1.5, None, [], {}])
    def test_a_value_of_the_wrong_kind_is_ignored(self, value):
        merged, applied, ignored = self._merge(
            {"user_interface": {"messages_page_size": value}})
        assert applied == 0 and ignored == ["user_interface.messages_page_size"]
        assert merged["user_interface"]["messages_page_size"] == 200

    def test_a_number_where_a_speed_belongs_is_accepted(self):
        """1 and 1.0 are the same speed; refusing the first would drop it."""
        merged, applied, _ignored = self._merge({"audio_playback": {"audio_default_speed": 2}})
        assert merged["audio_playback"]["audio_default_speed"] == 2 and applied == 1

    def test_true_is_not_a_number(self):
        merged, applied, ignored = self._merge({"storage": {"media_max_days": True}})
        assert applied == 0 and ignored == ["storage.media_max_days"]

    def test_a_list_setting_travels_whole(self):
        merged, applied, _ignored = self._merge(
            {"storage": {"auto_download_media_types": ["images"]}})
        assert merged["storage"]["auto_download_media_types"] == ["images"]
        assert applied == 1

    def test_a_free_form_section_travels_whole(self):
        """sound_events is keyed by event name, not by a fixed set."""
        events = {"message_received": {"enabled": False, "path": ""}}
        merged, applied, ignored = self._merge({"sound_events": events})
        assert merged["sound_events"] == events and applied == 1 and ignored == []

    def test_a_free_form_entry_of_the_wrong_shape_is_dropped(self):
        """Free-form in its keys, never in its values: load_sounds() calls
        .get() on each one, and it runs in __init__ — so a number here would
        stop the app opening at all on the next launch, with hand-editing
        settings.json the only way back."""
        merged, applied, ignored = self._merge(
            {"sound_events": {"default": 5, "classic": {"enabled": True}}})
        assert merged["sound_events"] == {"classic": {"enabled": True}}
        assert ignored == ["sound_events.default"] and applied == 1

    @pytest.mark.parametrize("language, kept", [
        ("pl", True), ("en-US", True), ("xx-YY", False), ("", False),
    ])
    def test_only_a_language_this_build_ships_is_applied(self, language, kept):
        """Locales are data: an export from an install carrying a sixth one
        would otherwise leave every label and every spoken line reading its own
        key name — including the box announcing the import."""
        current = _settings()
        merged, _applied, ignored = self._merge({"general": {"language": language}}, current)
        if kept:
            assert merged["general"]["language"] == language
        else:
            assert merged["general"]["language"] == current["general"]["language"]
            assert "general.language" in ignored

    @pytest.mark.parametrize("value, kept", [
        ({"vk": 75, "mod": 3}, True), (None, True), ("Ctrl+K", False), (75, False),
    ])
    def test_the_hotkey_is_a_pair_or_nothing(self, value, kept):
        merged, _applied, ignored = self._merge({"general": {"global_hotkey": value}})
        if kept:
            assert merged["general"]["global_hotkey"] == value
        else:
            assert "general.global_hotkey" in ignored

    def test_a_top_level_scalar_travels(self):
        merged, applied, _ignored = self._merge({"active_sound_pack": "classic"})
        assert merged["active_sound_pack"] == "classic" and applied == 1

    def test_a_section_sent_as_something_else_is_ignored(self):
        merged, applied, ignored = self._merge({"user_interface": "oops"})
        assert applied == 0 and ignored == ["user_interface"]

    def test_a_whole_export_round_trips(self):
        """The end-to-end promise: export here, import there, same preferences."""
        theirs = _settings()
        theirs["general"]["language"] = "pl"
        theirs["user_interface"]["messages_page_size"] = 75
        theirs["speech_content"]["announce_typing"] = False

        incoming, error = transfer.read_export(transfer.build_export(theirs))
        assert error == ""
        mine = _settings()
        mine["privateinfo"] = {"WA_token_protected": "mine", "paired": True}
        merged, applied, ignored = transfer.merge_settings(mine, incoming)

        assert merged["general"]["language"] == "pl"
        assert merged["user_interface"]["messages_page_size"] == 75
        assert merged["speech_content"]["announce_typing"] is False
        assert merged["privateinfo"] == {"WA_token_protected": "mine", "paired": True}
        assert merged["connection"]["wpp_port"] == mine["connection"]["wpp_port"]
        assert applied and ignored == []


class TestTheConnectionRuntime:
    """MainWindow keeps these five as attributes and builds every WPPConnect
    URL from server and port together, authenticating with the key — so an
    import has to move all five or none."""

    def test_it_reads_them_from_the_settings(self):
        settings = _settings()
        settings["connection"].update({
            "wpp_custom_api": True, "wpp_server": "https://api.exemplo.com",
            "wpp_ws_server": "wss://api.exemplo.com", "wpp_port": 8443,
            "wpp_api_key": "minha-chave"})
        assert transfer.connection_runtime(settings) == {
            "wpp_custom_api": True, "wpp_server": "https://api.exemplo.com",
            "wpp_ws_server": "wss://api.exemplo.com", "wpp_port": 8443,
            "wpp_api_key": "minha-chave"}

    def test_what_the_settings_do_not_say_keeps_the_running_value(self):
        runtime = transfer.connection_runtime(
            {"connection": {"wpp_server": "http://10.0.0.5"}},
            {"wpp_port": 6300, "wpp_api_key": "local", "wpp_custom_api": False,
             "wpp_ws_server": "ws://127.0.0.1"})
        assert runtime["wpp_server"] == "http://10.0.0.5"
        assert runtime["wpp_port"] == 6300 and runtime["wpp_api_key"] == "local"

    @pytest.mark.parametrize("settings", [None, {}, {"connection": "x"}, "x"])
    def test_unusable_settings_keep_everything_running(self, settings):
        fallback = {"wpp_custom_api": False, "wpp_server": "http://127.0.0.1",
                    "wpp_ws_server": "ws://127.0.0.1", "wpp_port": 6300,
                    "wpp_api_key": "local"}
        assert transfer.connection_runtime(settings, fallback) == fallback
