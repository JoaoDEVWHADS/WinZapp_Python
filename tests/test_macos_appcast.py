"""The Sparkle appcasts the macOS releases publish (macos/release/appcast.py).

What goes wrong with an appcast is quiet: an item whose sparkle:version
disagrees with its tag is refused by every app (sparkle_policy.item_tag), an
alpha without its channel reaches people who never opted in, a stable pushed
out by a run of alphas leaves stable users "up to date" forever, and notes
picked from the wrong changelog section describe another release. Sparkle
2.10.0 itself parsed this rendering and ordered these versions as tested
here (checked by hand against the framework when this was written). Pure
standard library; nothing is signed or downloaded.
"""

import importlib.util
import pathlib
import xml.etree.ElementTree as ET

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PATH = _ROOT / "macos" / "release" / "appcast.py"

pytestmark = pytest.mark.skipif(not _PATH.is_file(), reason="no macOS layer in this checkout")

_spec = importlib.util.spec_from_file_location("winzapp_appcast_under_test", _PATH)
A = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(A)

REPO = "rocco-labs/WinZapp_Python"
SIG = {"edSignature": "b4Ugl80G216Ol9SYOY0mIjscLZbrjgzk7hJoVsZ0yWFfN9WuA2Hb6A2APToSPoHAysNvHFhPG5DgesaEJtlJAg==",
       "length": 312953368}
NS = {"sparkle": A.SPARKLE_NS}

CHANGELOG = """V2.1.0.0

What is new in 2.1.

V2.0.0.0

What was new in 2.0.
"""


def _item(tag, notes=None):
    return A.make_item(tag, "arm64", REPO, SIG, {"en": f"notes {tag}"} if notes is None else notes,
                       pub_date="Sat, 10 Oct 2026 04:44:02 +0000")


class TestSigning:
    def test_sign_updates_output_is_read(self):
        out = f'sparkle:edSignature="{SIG["edSignature"]}" length="312953368"\n'
        assert A.parse_sign_output(out) == SIG

    @pytest.mark.parametrize("out", ["", "Error: no key", 'sparkle:edSignature="" length="1"'])
    def test_no_signature_stops(self, out):
        with pytest.raises(ValueError):
            A.parse_sign_output(out)


class TestReleaseNotes:
    def test_an_alpha_gets_the_section_of_the_release_it_leads_to(self):
        assert A.release_notes(CHANGELOG, "v2.1.0.4258alpha") == "What is new in 2.1."

    def test_a_stable_gets_its_own_section_and_never_a_newer_one(self):
        assert A.release_notes(CHANGELOG, "v2.1.0.0") == "What is new in 2.1."
        assert A.release_notes(CHANGELOG, "v2.0.0.9") == "What was new in 2.0."
        assert A.release_notes(CHANGELOG, "v1.9.0.0") == ""

    def test_each_locale_of_the_tag_with_english_first(self):
        notes = A.localized_notes(str(_ROOT / "client"), "v2.1.0.4258alpha",
                                  ["pt-BR", "pt-PT", "en-US", "es-ES", "pl", "tr-TR", "ro"])
        assert list(notes)[0] == "en"
        assert set(notes) <= {"en", "pt-BR", "pt-PT", "es", "pl", "tr", "ro"}
        assert all(text.strip() for text in notes.values())



class TestAnAlphasOwnNotes:
    """Every alpha heading to 2.1.0.0 had the same section as its notes; the
    feed's fallback now starts with the pull requests of that alpha's GitHub
    release (the app shows its own notes when it can, sparkle_notes.py)."""

    BODY = ("## What's Changed\n"
            "* Calls ring on the Mac by @rocco in https://github.com/o/r/pull/484\n"
            "* Fix the updater by @dependabot[bot] in https://github.com/o/r/pull/485\n\n"
            "**Full Changelog**: https://github.com/o/r/compare/v1...v2")

    def test_pull_requests_read_as_titles_and_numbers(self):
        assert A.pull_requests(self.BODY) == "- Calls ring on the Mac (#484)\n- Fix the updater (#485)"
        assert A.pull_requests("") == "" and A.pull_requests("Plain notes.") == ""

    def test_an_alpha_starts_with_its_pull_requests_in_every_language(self):
        notes = A.alpha_notes({"en": "What is new in 2.1.", "pt-BR": "Novidades."},
                              "v2.1.0.4258alpha", self.BODY)
        assert notes == {"en": "- Calls ring on the Mac (#484)\n- Fix the updater (#485)\n\nWhat is new in 2.1.",
                         "pt-BR": "- Calls ring on the Mac (#484)\n- Fix the updater (#485)\n\nNovidades."}

    @pytest.mark.parametrize("tag, body", [("v2.1.0.4258", BODY), ("v2.1.0.4258alpha", "No list here.")])
    def test_a_stable_or_a_body_without_pull_requests_keeps_its_section(self, tag, body):
        assert A.alpha_notes({"en": "What is new in 2.1."}, tag, body) == {"en": "What is new in 2.1."}


class TestItems:
    def test_an_item_names_its_release_tag_the_way_the_app_checks_it(self):
        i = _item("v2.1.0.4258alpha")
        assert (i["version"], i["short_version"], i["channel"]) == ("2.1.0.42581", "2.1.0.4258alpha", "alpha")
        assert i["url"] == ("https://github.com/rocco-labs/WinZapp_Python/releases/download/"
                            "v2.1.0.4258alpha/WinZapp-macOS-arm64.zip")
        assert _item("v2.1.0.0")["channel"] == ""
        assert _item("v2.1.0.5beta")["channel"] == ""          # betas are offered to everyone

    @pytest.mark.parametrize("tag,repo", [("2.1.0.0", REPO), ("v2.1.0", REPO), ("v2.1.0.0", "not a repo")])
    def test_a_bad_tag_or_repository_stops(self, tag, repo):
        with pytest.raises(ValueError):
            A.make_item(tag, "arm64", repo, SIG, {})

    def test_the_same_tag_twice_replaces_the_item(self):
        items = A.merge([_item("v2.1.0.4258alpha")], _item("v2.1.0.4258alpha", {"en": "rebuilt"}))
        assert [i["notes"] for i in items] == [{"en": "rebuilt"}]

    def test_alphas_never_push_the_stables_out(self):
        items = []
        for n in range(4):
            items = A.merge(items, _item(f"v2.0.0.{n}"))
        for n in range(4200, 4220):
            items = A.merge(items, _item(f"v2.1.0.{n}alpha"))
        tags = [i["tag"] for i in items]
        assert tags[:A.KEEP_ALPHA] == [f"v2.1.0.{n}alpha" for n in range(4219, 4219 - A.KEEP_ALPHA, -1)]
        assert tags[A.KEEP_ALPHA:] == ["v2.0.0.3", "v2.0.0.2", "v2.0.0.1"][:A.KEEP_STABLE]

    def test_only_the_newest_of_each_channel_keeps_its_notes(self):
        items = []
        for tag in ("v2.0.0.0", "v2.0.0.1", "v2.1.0.4200alpha", "v2.1.0.4201alpha"):
            items = A.merge(items, _item(tag))
        noted = {i["tag"] for i in items if i["notes"]}
        assert noted == {"v2.0.0.1", "v2.1.0.4201alpha"}


class TestRendering:
    def _parse(self, items):
        return ET.fromstring(A.render(items, "arm64"))

    def test_the_xml_has_what_sparkle_reads(self):
        rss = self._parse([_item("v2.1.0.4258alpha", {"en": "hello", "pt-BR": "olá"}), _item("v2.1.0.0")])
        alpha, stable = rss.findall("channel/item")
        assert alpha.find("sparkle:version", NS).text == "2.1.0.42581"
        assert alpha.find("sparkle:shortVersionString", NS).text == "2.1.0.4258alpha"
        assert alpha.find("sparkle:channel", NS).text == "alpha"
        assert stable.find("sparkle:channel", NS) is None
        assert alpha.find("sparkle:minimumSystemVersion", NS).text == "12.0"
        enc = alpha.find("enclosure")
        assert enc.get("url").endswith("/v2.1.0.4258alpha/WinZapp-macOS-arm64.zip")
        assert enc.get("length") == "312953368"
        assert enc.get(f"{{{A.SPARKLE_NS}}}edSignature") == SIG["edSignature"]
        descs = {d.get(A.XML_LANG): d.text for d in alpha.findall("description")}
        assert descs == {"en": "hello", "pt-BR": "olá"}
        assert all(d.get(f"{{{A.SPARKLE_NS}}}format") == "plain-text" for d in alpha.findall("description"))

    def test_markdown_release_notes_only_without_a_changelog_section(self):
        item = A.make_item("v2.1.0.0", "arm64", REPO, SIG, {}, markdown="**hi**", pub_date="x")
        desc = self._parse([item]).find("channel/item/description")
        assert desc.text == "**hi**" and desc.get(f"{{{A.SPARKLE_NS}}}format") == "markdown"
        assert A.make_item("v2.1.0.0", "arm64", REPO, SIG, {"en": "x"}, markdown="**hi**")["markdown"] == ""

    def test_no_delta_is_ever_listed(self):
        xml = A.render([_item("v2.1.0.4258alpha")], "arm64").decode()
        assert "deltas" not in xml and "sparkle:deltaFrom" not in xml


class TestTheWorkflowsPinnedCopy:
    """The releases workflow signs with its own copy of these files
    (.github/mac-release-tools, added by macos/release/mac-release-sparkle.patch),
    so the step holding the private key runs no code from the tag it
    publishes. The copy in the patch must be exactly this tree's."""

    PATCH = _ROOT / "macos" / "release" / "mac-release-sparkle.patch"
    COPIES = {
        ".github/mac-release-tools/release/appcast.py": _ROOT / "macos" / "release" / "appcast.py",
        ".github/mac-release-tools/winzapp_mac/provenance.py": _ROOT / "macos" / "winzapp_mac" / "provenance.py",
        ".github/mac-release-tools/winzapp_mac/sparkle_policy.py":
            _ROOT / "macos" / "winzapp_mac" / "sparkle_policy.py",
    }

    def _added_files(self):
        files, current = {}, None
        for line in self.PATCH.read_text(encoding="utf-8").splitlines():
            if line.startswith("+++ b/"):
                current = line[len("+++ b/"):]
                files[current] = []
            elif line.startswith("diff --git"):
                current = None
            elif current and line.startswith("+"):
                files[current].append(line[1:])
        return {name: "\n".join(lines) + "\n" for name, lines in files.items()}

    def test_the_pinned_copies_are_this_trees_files(self):
        added = self._added_files()
        for name, source in self.COPIES.items():
            assert added.get(name) == source.read_text(encoding="utf-8"), name

    def test_the_signing_step_runs_only_the_pinned_copy(self):
        text = self.PATCH.read_text(encoding="utf-8")
        step = text[text.index("+      - name: Sign them and add them"):text.index("+      - name: Keep the appcast")]
        assert "SPARKLE_ED_PRIVATE_KEY" in step
        assert "src/macos" not in step and "build_app" not in step
        assert "mac-release-tools/release/appcast.py" in step and "--sign-update" in step
        assert "--public-key" in step and "vars.SPARKLE_PUBLIC_ED_KEY" in step
        assert "SPARKLE_SHA256: c2bf58aa8387266ac179357b1415d6f2635f044da8be41042af32425dae6da0c" in text


def test_add_reads_the_tags_changelogs_from_source(tmp_path, monkeypatch):
    """--source: the tag's files are read as data, from wherever they are."""
    src = tmp_path / "src" / "client"
    (src / "languages").mkdir(parents=True)
    (src / "languages" / "language_map.json").write_text('{"en-US": "English"}', encoding="utf-8")
    (src / "changelog_en-US.txt").write_text("V2.1.0.0\n\nFrom the tag.\n", encoding="utf-8")
    sig = tmp_path / "sig.json"
    sig.write_text('{"edSignature": "%s", "length": 1}' % SIG["edSignature"], encoding="utf-8")
    signed = []
    monkeypatch.setattr(A, "_sign", lambda path, tool=None: signed.append((path, tool)) or "")
    A.main(["add", "--site", str(tmp_path / "site"), "--tag", "v2.1.0.4258alpha", "--arch", "arm64",
            "--repo", REPO, "--signature", str(sig), "--source", str(tmp_path / "src"),
            "--sign-update", "/pinned/sign_update"])
    xml = (tmp_path / "site" / "appcast-arm64.xml").read_text(encoding="utf-8")
    assert "From the tag." in xml and signed[0][1] == "/pinned/sign_update"


def test_add_puts_an_alphas_pull_requests_before_its_section(tmp_path, monkeypatch):
    """--notes-markdown is the tag's GitHub release body (the workflow's gh api)."""
    src = tmp_path / "src" / "client"
    (src / "languages").mkdir(parents=True)
    (src / "languages" / "language_map.json").write_text('{"en-US": "English"}', encoding="utf-8")
    (src / "changelog_en-US.txt").write_text("V2.1.0.0\n\nFrom the tag.\n", encoding="utf-8")
    body = tmp_path / "notes.md"
    body.write_text("* Calls ring by @rocco in https://github.com/o/r/pull/484\n", encoding="utf-8")
    sig = tmp_path / "sig.json"
    sig.write_text('{"edSignature": "%s", "length": 1}' % SIG["edSignature"], encoding="utf-8")
    monkeypatch.setattr(A, "_sign", lambda path, tool=None: "")
    A.main(["add", "--site", str(tmp_path / "site"), "--tag", "v2.1.0.4258alpha", "--arch", "arm64",
            "--repo", REPO, "--signature", str(sig), "--source", str(tmp_path / "src"),
            "--notes-markdown", str(body), "--sign-update", "/pinned/sign_update"])
    root = ET.parse(tmp_path / "site" / "appcast-arm64.xml").getroot()
    (desc,) = root.findall("channel/item/description")
    assert desc.text == "- Calls ring (#484)\n\nFrom the tag."


class TestOnlyBuildsCarryingTheKey:
    """Sparkle refuses an update that drops its key, after the user has
    downloaded the whole zip (about 380 MB); appcast.py never adds one."""

    KEY = "Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4Zm9vYmFyYmE="
    TAG = "v2.1.0.4258alpha"

    def _zip(self, tmp_path, **info):
        import plistlib
        import zipfile
        P = A.provenance
        plist = {"WinZappReleaseTag": self.TAG, "CFBundleVersion": P.bundle_version(self.TAG),
                 "SUPublicEDKey": self.KEY,
                 "SUFeedURL": "https://rocco-labs.github.io/WinZapp_Python/appcast-arm64.xml"}
        plist.update(info)
        plist = {k: v for k, v in plist.items() if v is not None}
        path = tmp_path / "WinZapp-macOS-arm64.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("WinZapp.app/Contents/Info.plist", plistlib.dumps(plist))
        return str(path)

    def test_a_sparkle_build_of_the_tag_with_the_key_is_accepted(self, tmp_path):
        assert A.key_refusal(self._zip(tmp_path), self.TAG, self.KEY) == ""

    @pytest.mark.parametrize("info,why", [
        ({"SUPublicEDKey": None}, "public key"),                       # built without the key
        ({"SUPublicEDKey": "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE="}, "public key"),
        ({"WinZappReleaseTag": "v2.1.0.4257alpha"}, "not release"),
        ({"SUFeedURL": None}, "incomplete"),
        ({"CFBundleVersion": "2.1.0.4258"}, "incomplete"),
    ])
    def test_anything_else_is_refused(self, tmp_path, info, why):
        assert why in A.key_refusal(self._zip(tmp_path, **info), self.TAG, self.KEY)

    def test_a_zip_without_the_app_or_no_key_to_check_against_is_refused(self, tmp_path):
        bad = tmp_path / "bad.zip"
        bad.write_bytes(b"not a zip")
        assert A.key_refusal(str(bad), self.TAG, self.KEY)
        assert A.key_refusal(self._zip(tmp_path), self.TAG, "")

    def test_sign_zip_refuses_before_signing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(A, "_sign", lambda *a: pytest.fail("signed a build without the key"))
        with pytest.raises(SystemExit, match="not added to the appcast"):
            A.main(["sign-zip", "--zip", self._zip(tmp_path, SUPublicEDKey=None), "--out",
                    str(tmp_path / "s.json"), "--tag", self.TAG, "--public-key", self.KEY])
