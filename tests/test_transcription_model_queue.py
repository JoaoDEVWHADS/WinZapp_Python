"""Marking models and downloading the marked ones in sequence — the pure half.

The keys and the list are in tests/test_transcription_settings_tab.py; here is
only what needs no window: which marks still mean something, what the queue is
(and what it skips), the row text, and what the user is told before the queue
starts.
"""

import pytest

from core.transcription import device, model_catalog, model_queue, model_store

_PROBE = device.HardwareProbe(total_ram_mb=16_384, available_ram_mb=12_288)
_ABSENT = model_store.STATE_ABSENT
_INSTALLED = model_store.STATE_INSTALLED
_INCOMPLETE = model_store.STATE_INCOMPLETE


class TestMarks:
    def test_toggling_marks_then_unmarks(self):
        marks = set()
        assert model_queue.toggle(marks, "small") is True
        assert marks == {"small"}
        assert model_queue.toggle(marks, "small") is False
        assert marks == set()

    def test_the_mode_is_on_only_while_a_marked_model_is_listed(self):
        marks = {"small"}
        assert model_queue.visible_marked(marks, ["auto", "small"])
        # The other backend lists other models: a mark nobody can see must not
        # make Space keep marking.
        assert not model_queue.visible_marked(marks, ["auto", "tiny"])
        assert not model_queue.visible_marked(set(), ["small"])

    def test_marks_of_models_no_longer_offered_are_forgotten(self):
        marks = {"small", "gone"}
        model_queue.prune(marks, ["auto", "small"])
        assert marks == {"small"}

    def test_a_row_says_it_is_marked_where_the_user_asked(self):
        assert model_queue.row_label("Small", True, "selecionado", "end") == (
            "Small selecionado"
        )
        assert model_queue.row_label("Small", True, "selecionado", "start") == (
            "selecionado Small"
        )
        assert model_queue.row_label("Small", False, "selecionado", "end") == "Small"


class TestTheQueue:
    LISTED = ["auto", "tiny", "base", "small"]

    def test_it_follows_the_order_of_the_list_not_of_the_marking(self):
        marks = {"small", "tiny"}
        states = {"tiny": _ABSENT, "base": _ABSENT, "small": _ABSENT}
        assert model_queue.queue_for(marks, self.LISTED, states) == ["tiny", "small"]

    def test_a_complete_model_is_skipped_not_downloaded_again(self):
        marks = {"tiny", "base"}
        states = {"tiny": _INSTALLED, "base": _ABSENT}
        assert model_queue.queue_for(marks, self.LISTED, states) == ["base"]

    def test_an_interrupted_download_is_resumed(self):
        states = {"tiny": _INCOMPLETE}
        assert model_queue.queue_for({"tiny"}, self.LISTED, states) == ["tiny"]

    def test_a_model_never_measured_is_not_guessed_at(self):
        assert model_queue.queue_for({"tiny"}, self.LISTED, {}) == []

    def test_nothing_marked_is_no_queue(self):
        assert model_queue.queue_for(set(), self.LISTED, {"tiny": _ABSENT}) == []


class TestWhatTheUserAgreesTo:
    def _ids(self, count):
        return [model.id for model in model_catalog.list_models()][:count]

    def test_the_size_is_the_sum_and_the_slack_is_paid_once(self, tmp_path):
        ids = self._ids(3)
        summary = model_queue.queue_download_summary(
            ids, str(tmp_path), _PROBE, 10 ** 12, device.PREFERENCE_AUTO
        )
        singles = [
            model_queue.management.model_download_summary(
                model_id, str(tmp_path), _PROBE, 10 ** 12
            )
            for model_id in ids
        ]
        total = sum(single.download_bytes for single in singles)
        assert summary.model_ids == tuple(ids)
        assert summary.download_bytes == total
        assert summary.required_free_bytes == model_store.required_free_bytes(total)
        assert summary.destination == str(tmp_path)

    def test_too_little_disk_is_a_no(self, tmp_path):
        summary = model_queue.queue_download_summary(
            self._ids(2), str(tmp_path), _PROBE, 1, device.PREFERENCE_AUTO
        )
        assert summary.enough_space is False

    def test_a_disk_that_cannot_be_measured_is_unknown_not_enough(self, tmp_path):
        summary = model_queue.queue_download_summary(
            self._ids(2), str(tmp_path), _PROBE, None, device.PREFERENCE_AUTO
        )
        assert summary.enough_space is None

    def test_an_unknown_id_is_left_out_and_all_unknown_is_none(self, tmp_path):
        ids = self._ids(1) + ["nonexistent-model"]
        summary = model_queue.queue_download_summary(
            ids, str(tmp_path), _PROBE, 10 ** 12, device.PREFERENCE_AUTO
        )
        assert summary.model_ids == tuple(self._ids(1))
        assert model_queue.queue_download_summary(
            ["nonexistent-model"], str(tmp_path), _PROBE, 10 ** 12,
            device.PREFERENCE_AUTO,
        ) is None

    def test_a_model_too_big_for_the_memory_is_named(self, tmp_path):
        tiny_ram = device.HardwareProbe(total_ram_mb=512, available_ram_mb=256)
        summary = model_queue.queue_download_summary(
            ["large-v3"], str(tmp_path), tiny_ram, 10 ** 12, device.PREFERENCE_AUTO
        )
        assert summary.not_fitting == ("large-v3",)
