"""What the Transcription tab says and offers about models in other folders.

`external_view` is the part of the tab that can be decided without a window, so
these call it directly. What each pins is something a person using a screen
reader would otherwise find out the hard way:

* **A row is one sentence.** A list row is read whole and nothing else is: the
  folder, what it holds and whether it can be used are all inside it, and a
  folder is named by its last component, never a path read character by
  character (a Hugging Face snapshot by its repository — its own folder name is
  a 40-digit commit).
* **"Use this model" is for a model that can be used now.** Choosing one whose
  disk is unplugged only moves the failure to the first transcription.
* **Counting an external folder as installed needs its state.** A reference
  not measured yet does not make a model "available": the picker would promise
  what the run may not find. And a custom model is never among what the
  automatic choice picks from.
* **The question about a folder the catalogue does not vouch for says which
  of two true things it is** — unknown, or the sizes of a known model with
  other weights — so that nobody is let to believe the second is the first.
"""

import json
import pathlib
import re

from tests.locales import load_strings, registered_locale_codes
import pytest

from coord_locks import canonical_dir
from core.transcription import backend as backend_module
from core.transcription import external_models, external_view, model_catalog, model_store
from tests.test_transcription_external_models import (  # noqa: F401  (fixtures)
    _hf_snapshot,
    _same_length_other_bytes,
    _write,
    catalogue,
)

LOCALES = registered_locale_codes()


class _I18n:
    """The key and what it was formatted with, so assertions need no locale."""

    def t(self, key):
        return _Template(key)


class _Template(str):
    def format(self, **values):
        return f"{self}|" + ",".join(f"{k}={v}" for k, v in sorted(values.items()))


def _parent(path):
    return str(pathlib.Path(path).parent)


def _join(path, name):
    return str(pathlib.Path(path) / name)


def _reference(reference_id="r1", path="/disk/models/my-model", model_id=None,
               verified=True):
    return external_models.ExternalReference(
        reference_id, path, model_id, verified, weights_mark=(1, 2),
        key=path.casefold(),
    )


class TestTheRows:
    def test_a_custom_row_says_which_folder_and_what_state(self):
        text = external_view.row_label(
            _I18n(), _reference(), external_models.REF_FOLDER_MISSING)
        assert text == (
            f"{external_view.ROW_CUSTOM_I18N_KEY}|model=,name=my-model,"
            f"state={external_view.STATE_I18N_KEYS[external_models.REF_FOLDER_MISSING]}")

    def test_a_catalogue_row_names_the_model(self):
        text = external_view.row_label(
            _I18n(), _reference(model_id="large-v3"), external_models.REF_READY)
        assert text.startswith(external_view.ROW_CATALOGUE_I18N_KEY)
        assert "model=large-v3" in text

    def test_not_measured_yet_is_said_as_such_and_not_guessed(self):
        text = external_view.row_label(_I18n(), _reference(), None)
        assert external_view.STATE_I18N_KEYS[None] in text
        assert external_view.STATE_I18N_KEYS[external_models.REF_READY] not in text

    def test_a_folder_is_named_by_its_last_component_never_the_whole_path(self):
        text = external_view.row_label(
            _I18n(), _reference(path="/home/someone/projects/models/my-model"), None)
        assert "name=my-model" in text
        assert "someone" not in text

    def test_a_cache_snapshot_is_named_by_its_repository(self):
        snapshot = "/cache/hub/models--Org--faster-whisper-small/snapshots/" + "a" * 40
        text = external_view.row_label(_I18n(), _reference(path=snapshot), None)
        assert "name=faster-whisper-small" in text

    def test_every_state_an_answer_can_be_has_a_word(self):
        for state in (external_models.REF_READY, external_models.REF_FOLDER_MISSING,
                      external_models.REF_CHANGED, external_models.REF_UNVERIFIED, None):
            assert state in external_view.STATE_I18N_KEYS


class TestTheButtons:
    ALL_OFF = {"add": False, "find": False, "use": False, "check": False, "forget": False}

    def test_nothing_selected_offers_only_the_two_ways_to_add(self):
        assert external_view.button_states(None, None, False) == {
            "add": True, "find": True, "use": False, "check": False, "forget": False}

    def test_a_ready_model_can_be_used_checked_and_forgotten(self):
        assert external_view.button_states(
            _reference(), external_models.REF_READY, False) == {
                "add": True, "find": True, "use": True, "check": True, "forget": True}

    @pytest.mark.parametrize("state", [
        external_models.REF_FOLDER_MISSING, external_models.REF_CHANGED,
        external_models.REF_UNVERIFIED, None])
    def test_a_model_that_cannot_be_used_now_can_still_be_checked_or_forgotten(
        self, state
    ):
        allowed = external_view.button_states(_reference(), state, False)
        assert allowed["use"] is False
        assert allowed["check"] and allowed["forget"]

    def test_everything_is_off_while_something_runs(self):
        assert external_view.button_states(
            _reference(), external_models.REF_READY, True) == self.ALL_OFF
        assert external_view.button_states(None, None, True) == self.ALL_OFF


class TestWhatCountsAsAvailable:
    def test_a_verified_external_copy_makes_the_model_available(self):
        references = (_reference(model_id="small"),)
        ready = external_view.ready_model_ids(
            references, {"r1": external_models.REF_READY})
        assert ready == {"small"}

    def test_a_reference_not_measured_yet_does_not(self):
        assert external_view.ready_model_ids((_reference(model_id="small"),), {}) == frozenset()

    @pytest.mark.parametrize("state", [
        external_models.REF_FOLDER_MISSING, external_models.REF_CHANGED,
        external_models.REF_UNVERIFIED])
    def test_nor_does_one_that_is_not_ready(self, state):
        assert external_view.ready_model_ids(
            (_reference(model_id="small"),), {"r1": state}) == frozenset()

    def test_a_custom_model_is_never_a_catalogue_model(self):
        assert external_view.ready_model_ids(
            (_reference(),), {"r1": external_models.REF_READY}) == frozenset()

    def test_the_usable_ids_are_the_roots_and_the_external_ones_in_catalogue_order(self):
        first, second = model_catalog.list_models()[:2]
        references = (_reference(model_id=first.id),)
        usable = external_view.usable_ids(
            (second.id,), references, {"r1": external_models.REF_READY})
        assert usable == (first.id, second.id)

    def test_the_automatic_choice_never_sees_a_custom_model(self):
        usable = external_view.usable_ids(
            (), (_reference(),), {"r1": external_models.REF_READY})
        assert usable == ()

    def test_a_models_picker_line_says_another_folder_only_when_the_root_has_none(self):
        model = model_catalog.list_models()[0]
        ready = frozenset({model.id})
        assert external_view.choice_is_external(model, model_store.STATE_ABSENT, ready)
        assert external_view.choice_is_external(model, model_store.STATE_INCOMPLETE, ready)
        assert not external_view.choice_is_external(
            model, model_store.STATE_INSTALLED, ready)
        assert not external_view.choice_is_external(
            model, model_store.STATE_ABSENT, frozenset())

    def test_custom_models_are_listed_whatever_their_folder_is_doing(self):
        references = (_reference("a"), _reference("b", model_id="small"),
                      _reference("c", path="/disk/other"))
        assert external_view.custom_choices(_I18n(), references) == [
            ("external:a", f"{external_view.CHOICE_CUSTOM_I18N_KEY}|name=my-model"),
            ("external:c", f"{external_view.CHOICE_CUSTOM_I18N_KEY}|name=other"),
        ]


class TestAWhisperCppFile:
    """A whisper.cpp model is one file: its sentences say "file", and the
    picker of one backend never offers the other's custom models."""

    @staticmethod
    def _file_reference(reference_id, model_id=None):
        return external_models.ExternalReference(
            reference_id, "/disk/models/fine-tune.bin", model_id, True,
            weights_mark=(1, 2), backend=backend_module.BACKEND_WHISPER_CPP,
        )

    def test_a_folders_sentence_has_a_files_sentence_beside_it(self):
        for key in external_view.FILE_I18N_KEYS:
            assert external_view.for_reference(key, True) == key + "_file"
            assert external_view.for_reference(key, False) == key

    def test_a_sentence_that_names_neither_is_the_same_for_both(self):
        key = external_view.USE_DONE_I18N_KEY
        assert external_view.for_reference(key, True) == key

    def test_custom_models_are_listed_under_their_own_backend_only(self):
        references = (_reference("folder"), self._file_reference("file"))
        choices = {
            backend: [value for value, _line in
                      external_view.custom_choices(_I18n(), references, backend)]
            for backend in (backend_module.BACKEND_FASTER_WHISPER,
                            backend_module.BACKEND_WHISPER_CPP, None)
        }
        assert choices[backend_module.BACKEND_FASTER_WHISPER] == ["external:folder"]
        assert choices[backend_module.BACKEND_WHISPER_CPP] == ["external:file"]
        assert choices[None] == ["external:folder", "external:file"]

    def test_a_ready_ggml_file_is_usable_in_the_catalogues_order(self):
        references = (self._file_reference("r1", model_id="ggml-small-q5_1"),)
        usable = external_view.usable_ids(
            ("small",), references, {"r1": external_models.REF_READY})
        assert usable == ("small", "ggml-small-q5_1")

    @pytest.mark.parametrize("state", [external_models.REF_FOLDER_MISSING,
                                       external_models.REF_CHANGED])
    def test_a_file_row_says_file_not_found_or_changed(self, state):
        row = external_view.row_label(_I18n(), self._file_reference("r1"), state)
        assert f"state={external_view.STATE_I18N_KEYS[state]}_file" in row
        folder_row = external_view.row_label(_I18n(), _reference("r1"), state)
        assert f"state={external_view.STATE_I18N_KEYS[state]}" in folder_row
        assert "_file" not in folder_row

    def test_the_question_about_an_unknown_file_says_file(self):
        text = external_view.custom_question(
            _I18n(), "/disk/fine-tune.bin", external_models.ACCEPT_NOT_IDENTIFIED,
            None, is_file=True)
        assert text.startswith(external_view.NOT_IDENTIFIED_QUESTION_I18N_KEY + "_file")
        assert "name=fine-tune.bin" in text


class TestTheQuestionAboutAFolderTheCatalogueDoesNotVouchFor:
    def test_unknown_says_so(self):
        text = external_view.custom_question(
            _I18n(), "/disk/mine", external_models.ACCEPT_NOT_IDENTIFIED, None)
        assert text.startswith(external_view.NOT_IDENTIFIED_QUESTION_I18N_KEY)
        assert "name=mine" in text

    def test_the_sizes_of_a_known_model_with_other_weights_is_not_that_model(self):
        text = external_view.custom_question(
            _I18n(), "/disk/mine", external_models.ACCEPT_DIGEST_MISMATCH, "large-v3")
        assert text.startswith(external_view.DIGEST_MISMATCH_QUESTION_I18N_KEY)
        assert "model=large-v3" in text


class TestWhatAPickedFolderStandsFor:
    def test_a_model_folder_stands_for_itself(self, catalogue, tmp_path):
        _model, contents = catalogue["alpha"]
        folder = _write(tmp_path / "mine", contents)
        [candidate] = external_view.folder_candidates(folder)
        assert candidate.path == folder
        assert candidate.model_id == "alpha"

    def test_a_folder_that_is_not_a_model_is_still_checked_so_it_can_say_why(
        self, tmp_path
    ):
        (tmp_path / "empty").mkdir()
        assert external_view.folder_candidates(tmp_path / "empty") == (
            external_view.Candidate(str(tmp_path / "empty")),)

    def test_a_cache_repository_folder_stands_for_each_of_its_revisions(
        self, catalogue, tmp_path
    ):
        model, contents = catalogue["alpha"]
        hub = tmp_path / "hub"
        first = _hf_snapshot(hub, model, contents)
        repository = _parent(_parent(first))
        candidates = external_view.folder_candidates(repository)
        assert [c.path for c in candidates] == [first]
        assert candidates[0].revision == model.revision
        assert candidates[0].model_id == "alpha"

    def test_only_folders_shaped_like_a_model_are_offered(self, catalogue, tmp_path):
        model, contents = catalogue["alpha"]
        hub = tmp_path / "hub"
        good = _hf_snapshot(hub, model, contents)
        repository = _parent(_parent(good))
        # An interrupted download: a revision with no weights.
        interrupted = _join(_parent(good), "b" * 40)
        _write(interrupted, {"config.json": b"{}"})
        assert [c.path for c in external_view.folder_candidates(repository)] == [good]

    def test_what_is_not_added_yet_is_all_discovery_lists(self, catalogue, tmp_path):
        model, contents = catalogue["alpha"]
        hub = tmp_path / "hub"
        snapshot = _hf_snapshot(hub, model, contents)
        snapshots = external_models.discover_hf_cache(str(hub))
        assert [s.path for s in snapshots] == [snapshot]
        assert external_view.new_snapshots(snapshots, ()) == snapshots
        reference = external_models.ExternalReference(
            "r", snapshot, "alpha", True, (1, 2), canonical_dir(snapshot))
        assert external_view.new_snapshots(snapshots, (reference,)) == ()

    def test_a_listed_snapshot_says_what_it_looks_like_without_claiming_it_is(
        self, catalogue, tmp_path
    ):
        model, contents = catalogue["alpha"]
        snapshot = _hf_snapshot(tmp_path / "hub", model, contents)
        [found] = external_models.discover_hf_cache(str(tmp_path / "hub"))
        text = external_view.snapshot_label(_I18n(), found)
        assert text.startswith(external_view.SNAPSHOT_RECOGNISED_I18N_KEY)
        assert f"model={model.id}" in text
        assert f"revision={model.revision[:8]}" in text
        assert snapshot  # silence "unused"

    def test_an_unrecognised_one_is_just_its_name_and_a_slice_of_the_commit(self):
        candidate = external_view.Candidate("/c/models--A--whisper-x/snapshots/abc", "abcdef0123")
        assert external_view.snapshot_label(_I18n(), candidate) == "whisper-x (abcdef01)"


@pytest.mark.parametrize("locale", LOCALES)
def test_every_string_exists_in_every_locale_and_formats(locale):
    """A missing key is read out as its own name; a dropped placeholder loses
    the folder the sentence is about, and an invented one is a KeyError."""
    table = load_strings(locale)
    values = {"name": "mine", "model": "small", "state": "ok", "revision": "abc",
              "folders": "x", "size_class": "s", "size": "1 GB"}
    for key in external_view.VIEW_I18N_KEYS + (
            "transcription_external_root_contains",):
        assert table.get(key, "").strip(), f"{locale}: {key} is missing or blank"
        assert "{" not in table[key].format(**values), f"{locale}: {key}"
    for key in (external_view.ROW_CATALOGUE_I18N_KEY, external_view.ROW_CUSTOM_I18N_KEY):
        assert "{name}" in table[key] and "{state}" in table[key], f"{locale}: {key}"
    assert "{model}" in table[external_view.ROW_CATALOGUE_I18N_KEY]
    for key in (external_view.NOT_IDENTIFIED_QUESTION_I18N_KEY,
                external_view.DIGEST_MISMATCH_QUESTION_I18N_KEY,
                external_view.FORGET_QUESTION_I18N_KEY,
                external_view.FORGOTTEN_I18N_KEY, external_view.USE_DONE_I18N_KEY):
        assert "{name}" in table[key], f"{locale}: {key} lost {{name}}"
    assert "{model}" in table[external_view.DIGEST_MISMATCH_QUESTION_I18N_KEY]
    assert "{folders}" in table["transcription_external_root_contains"]
    # A file's sentence is its folder sentence with the noun changed: the same
    # placeholders, or the file's name is lost from the one about a file.
    for key, file_key in external_view.FILE_I18N_KEYS.items():
        assert (set(re.findall(r"\{(\w+)\}", table[file_key]))
                == set(re.findall(r"\{(\w+)\}", table[key]))), f"{locale}: {file_key}"


@pytest.mark.parametrize("locale", LOCALES)
def test_the_group_name_spends_no_letter_and_every_button_has_one(locale):
    """The group is not a tab stop, so it takes no Alt key. The five buttons
    each have one, like every action button on the tab: the letters are shared
    by word across the rows and never take OK's, Cancel's or Apply's (see
    tests/test_transcription_settings_tab.py::TestTheMnemonicsOnThisTab)."""
    table = load_strings(locale)
    assert "&" not in table["transcription_external_actions_group"], locale
    for key in ("transcription_external_add_btn", "transcription_external_find_btn",
                "transcription_external_use_btn", "transcription_external_check_btn",
                "transcription_external_forget_btn"):
        assert table[key].count("&") == 1, f"{locale}: {key}"
