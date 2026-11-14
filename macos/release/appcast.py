#!/usr/bin/env python3
"""The Sparkle appcasts of the macOS releases (one per architecture).

Run by the releases repository's workflow (macos/release/README.md) on a Mac
runner, over the zips downloaded from the published release (and checked
against its SHA256SUMS.txt). The workflow runs its own pinned copy of this
file, never the one in the tag being added: the step that holds the private
key runs no code from that tag, which it reads as data only (--source: its
changelogs and language map).

    appcast.py sign-zip --zip pub/WinZapp-macOS-arm64.zip --out sparkle-arm64.json \\
        --tag v2.1.0.4258alpha --public-key "$SPARKLE_PUBLIC_ED_KEY" --sign-update tools/sign_update
    appcast.py add --site site --tag v2.1.0.4258alpha --arch arm64 \\
        --repo rocco-labs/WinZapp_Python --signature sparkle-arm64.json \\
        --source src --sign-update tools/sign_update

The private EdDSA key is read from SPARKLE_ED_PRIVATE_KEY and handed to
Sparkle's own sign_update (from the Sparkle release build_app.py pins) on its
standard input: never an argument, never a file. sign_update signs the zip
(sparkle:edSignature) and then the whole feed, so the apps, which require a
signed feed (SURequireSignedFeed), trust nothing in it that was changed after.

The items of each feed live in site/appcast-<arch>.json, and the XML is
rebuilt from them each time: adding a release never edits signed XML in
place. Only full zips are listed, never deltas: the app refuses an item with
deltas (sparkle_policy.decide), since the release its tag stands for is the
full zip.

The parsing and rendering are pure and tested on any platform
(tests/test_macos_appcast.py).
"""

import argparse
import datetime
import email.utils
import importlib.util
import json
import os
import plistlib
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
MACOS = os.path.dirname(HERE)
ROOT = os.path.dirname(MACOS)
if MACOS not in sys.path:
    sys.path.insert(0, MACOS)

from winzapp_mac import provenance, sparkle_policy  # noqa: E402  (pure standard library)

SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
KEEP_ALPHA = 5              # newest alphas kept in a feed
KEEP_STABLE = 3             # newest stables; never pushed out by alphas
KEY_ENV = "SPARKLE_ED_PRIVATE_KEY"

_SIGN_OUTPUT = re.compile(r'sparkle:edSignature="([A-Za-z0-9+/=]+)"\s+length="(\d+)"', re.ASCII)
# client/updater.py's _HDR_RE: a "V1.2.3.4" line starts a version's section.
_HEADER = re.compile(r"^V(\d+\.\d+\.\d+\.\d+(?:dev|alpha|beta)?)\s*$", re.IGNORECASE | re.ASCII)
# A pull request in a GitHub release body, as client/core/release_notes.py reads it.
_PULL = re.compile(r"^\s*[*-]\s+(?P<title>.+?)\s+by\s+@[\w.-]+(?:\[bot\])?\s+in\s+\S*/pull/(?P<number>\d+)\s*$")

ET.register_namespace("sparkle", SPARKLE_NS)


# -- pure ------------------------------------------------------------------------

def parse_sign_output(text):
    """{"edSignature", "length"} from what sign_update prints for an archive."""
    m = _SIGN_OUTPUT.search(text or "")
    if not m:
        raise ValueError("sign_update printed no signature")
    return {"edSignature": m.group(1), "length": int(m.group(2))}


def _section_key(version):
    """Order of a changelog header, as provenance orders tags (a "dev"
    header, which no release tag has, sorts before alpha)."""
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)\.(\d+)(dev|alpha|beta)?", version, re.IGNORECASE | re.ASCII)
    pre = {"dev": 0, "alpha": 1, "beta": 2, "": 3}[(m.group(5) or "").lower()]
    return tuple(int(m.group(i)) for i in range(1, 5)), pre


INFO_PLIST = "WinZapp.app/Contents/Info.plist"


def key_refusal(zip_path, tag, public_key):
    """"" when the app in *zip_path* is a Sparkle build of release *tag* that
    trusts *public_key*, otherwise why not. Once one Sparkle build exists,
    every release offered to it must carry the key (Sparkle refuses an update
    that drops it, SUUpdateValidator.m: "Sparkle only supports rotation, but
    not removal of (Ed)DSA keys"), and only after the user has downloaded the
    whole zip, so a release without it never goes into the appcast."""
    if not sparkle_policy.valid_public_key(public_key):
        return "no Sparkle public key given to check the build against"
    try:
        with zipfile.ZipFile(zip_path) as zf:
            info = plistlib.loads(zf.read(INFO_PLIST))
    except (OSError, KeyError, zipfile.BadZipFile, plistlib.InvalidFileException, ValueError) as exc:
        return f"cannot read {INFO_PLIST} in the zip: {type(exc).__name__}"
    if info.get(sparkle_policy.PUBLIC_KEY) != public_key:
        return "the build does not carry this repository's Sparkle public key"
    if info.get(provenance.RELEASE_TAG_KEY) != tag:
        return f"the build is not release {tag}"
    if not sparkle_policy.configured(info):
        return "the build's Sparkle configuration is incomplete"
    return ""


def release_notes(changelog_text, tag):
    """The newest section of a changelog_<locale>.txt at or below *tag*:
    for an alpha, the "what's new" of the release it is heading to."""
    want = _section_key(provenance.tag_version(tag))
    best, best_key, current, lines = None, None, None, []
    for line in (changelog_text or "").splitlines() + ["V0.0.0.0"]:
        m = _HEADER.match(line.strip())
        if not m:
            if current is not None:
                lines.append(line)
            continue
        if current is not None:
            key = _section_key(current)
            body = "\n".join(lines).strip()
            if body and key <= want and (best_key is None or key > best_key):
                best, best_key = body, key
        current, lines = m.group(1), []
    return best or ""


def pull_requests(markdown):
    """The pull requests a GitHub release body lists, one "- title (#N)" line
    each, without the author's @handle or the link; "" when it lists none."""
    lines = []
    for line in (markdown or "").splitlines():
        m = _PULL.match(line)
        if m:
            lines.append(f"- {m.group('title').strip()} (#{m.group('number')})")
    return "\n".join(lines)


def alpha_notes(notes, tag, markdown):
    """For an alpha, *notes* with the pull requests of its GitHub release
    first: the changelog section is the same for every alpha heading to one
    release, so on its own it cannot say what this alpha changed. The app
    shows its own notes when it can fetch them (winzapp_mac/sparkle_notes.py);
    these are what it falls back to."""
    pulls = pull_requests(markdown) if tag.endswith("alpha") else ""
    if not pulls:
        return dict(notes)
    return {lang: f"{pulls}\n\n{text}" for lang, text in notes.items()}


def localized_notes(changelog_dir, tag, locales):
    """{xml:lang: text} from each locale's changelog in *changelog_dir*,
    English first (Sparkle's choice when none matches the user's languages)."""
    notes = {}
    for locale in sorted(locales, key=lambda c: c != "en-US"):
        path = os.path.join(changelog_dir, f"changelog_{locale}.txt")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                text = release_notes(fh.read(), tag)
            if text:
                notes[sparkle_policy.bundle_localization(locale)] = text
    return notes


def make_item(tag, arch, repo, signature, notes, markdown="", pub_date=None):
    """One appcast item, as the JSON state keeps it."""
    if not provenance.is_release_tag(tag):
        raise ValueError(f"{tag!r} is not a release tag")
    if not provenance.valid_repo(repo):
        raise ValueError(f"{repo!r} is not a repository")
    return {
        "tag": tag,
        "version": provenance.bundle_version(tag),
        "short_version": provenance.tag_version(tag),
        "channel": sparkle_policy.ALPHA_CHANNEL if tag.endswith("alpha") else "",
        "url": sparkle_policy.zip_url(repo, tag, arch),
        "length": int(signature["length"]),
        "ed_signature": signature["edSignature"],
        "notes": dict(notes),
        "markdown": markdown if not notes else "",
        "pub_date": pub_date or email.utils.format_datetime(datetime.datetime.now(datetime.timezone.utc)),
    }


def merge(items, new):
    """*new* added (replacing an item of the same tag), newest first, with the
    newest KEEP_ALPHA alphas and KEEP_STABLE stables (betas count as stable:
    they are offered to everyone).

    Only the newest item of each channel keeps its release notes: it is the
    one Sparkle offers, and every app downloads the whole feed on each check
    (seven locales of notes are over 100 KB an item). The older items stay
    so a withdrawn release can be dropped by hand without leaving the feed
    empty."""
    items = [dict(i) for i in items if i["tag"] != new["tag"]] + [dict(new)]
    items.sort(key=lambda i: tuple(int(p) for p in i["version"].split(".")), reverse=True)
    alphas = [i for i in items if i["channel"]][:KEEP_ALPHA]
    stables = [i for i in items if not i["channel"]][:KEEP_STABLE]
    for older in alphas[1:] + stables[1:]:
        older["notes"], older["markdown"] = {}, ""
    return [i for i in items if any(i is k for k in alphas + stables)]


def render(items, arch):
    """The appcast XML (unsigned) for *items*."""
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = f"WinZapp for macOS ({arch})"
    ET.SubElement(channel, "language").text = "en"
    for i in items:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = f"WinZapp {i['short_version']}"
        ET.SubElement(item, "pubDate").text = i["pub_date"]
        ET.SubElement(item, f"{{{SPARKLE_NS}}}version").text = i["version"]
        ET.SubElement(item, f"{{{SPARKLE_NS}}}shortVersionString").text = i["short_version"]
        if i["channel"]:
            ET.SubElement(item, f"{{{SPARKLE_NS}}}channel").text = i["channel"]
        ET.SubElement(item, f"{{{SPARKLE_NS}}}minimumSystemVersion").text = \
            sparkle_policy.MINIMUM_SYSTEM_VERSION
        for lang, text in i["notes"].items():
            desc = ET.SubElement(item, "description",
                                 {XML_LANG: lang, f"{{{SPARKLE_NS}}}format": "plain-text"})
            desc.text = text
        if not i["notes"] and i.get("markdown"):
            ET.SubElement(item, "description", {f"{{{SPARKLE_NS}}}format": "markdown"}).text = i["markdown"]
        ET.SubElement(item, "enclosure", {
            "url": i["url"], "length": str(i["length"]), "type": "application/octet-stream",
            f"{{{SPARKLE_NS}}}edSignature": i["ed_signature"]})
    ET.indent(rss)
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(rss, encoding="utf-8") + b"\n"


# -- Sparkle's tools ---------------------------------------------------------------

def sign_update_tool():
    """bin/sign_update of the Sparkle release build_app.py pins (downloaded
    and SHA-256 checked there)."""
    spec = importlib.util.spec_from_file_location("winzapp_build_app", os.path.join(MACOS, "build_app.py"))
    build_app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_app)
    return os.path.join(build_app.fetch_sparkle(), "bin", "sign_update")


def _sign(path, tool=None):
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        sys.exit(f"{KEY_ENV} is not set")
    r = subprocess.run([tool or sign_update_tool(), "--ed-key-file", "-", path],
                       input=key + "\n", capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"sign_update failed for {os.path.basename(path)}: {r.stderr.strip()[-300:]}")
    return r.stdout


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sign-zip", help="EdDSA-sign a release zip")
    s.add_argument("--zip", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--sign-update", default="",
                   help="Sparkle's sign_update (default: the one build_app.py pins)")
    s.add_argument("--tag", required=True, help="the release the zip must be a build of")
    s.add_argument("--public-key", required=True,
                   help="the Sparkle public key the build must carry (SPARKLE_PUBLIC_ED_KEY)")
    a = sub.add_parser("add", help="add a release to site/appcast-<arch>.xml and sign the feed")
    a.add_argument("--site", required=True)
    a.add_argument("--tag", required=True)
    a.add_argument("--arch", required=True, choices=("arm64", "x86_64"))
    a.add_argument("--repo", required=True)
    a.add_argument("--signature", required=True, help="the JSON sign-zip wrote")
    a.add_argument("--notes-markdown", default="",
                   help="release notes used only when the tag has no changelog section")
    a.add_argument("--source", default=ROOT,
                   help="checkout of the tag, read as data (client/changelog_*, language_map.json)")
    a.add_argument("--sign-update", default="",
                   help="Sparkle's sign_update (default: the one build_app.py pins)")
    args = ap.parse_args(argv)

    if args.cmd == "sign-zip":
        why = key_refusal(args.zip, args.tag, args.public_key)
        if why:
            sys.exit(f"{os.path.basename(args.zip)} of {args.tag} is not added to the appcast: {why}")
        sig = parse_sign_output(_sign(args.zip, args.sign_update or None))
        if sig["length"] != os.path.getsize(args.zip):
            sys.exit("sign_update's length is not the zip's size")
        with open(args.out, "w") as fh:
            json.dump(sig, fh)
        return

    with open(args.signature) as fh:
        signature = json.load(fh)
    with open(os.path.join(args.source, "client", "languages", "language_map.json"), encoding="utf-8") as fh:
        locales = list(json.load(fh))
    markdown = ""
    if args.notes_markdown and os.path.isfile(args.notes_markdown):
        with open(args.notes_markdown, encoding="utf-8") as fh:
            markdown = fh.read().strip()
    notes = alpha_notes(localized_notes(os.path.join(args.source, "client"), args.tag, locales),
                        args.tag, markdown)
    item = make_item(args.tag, args.arch, args.repo, signature, notes, markdown)
    os.makedirs(args.site, exist_ok=True)
    state = os.path.join(args.site, sparkle_policy.feed_name(args.arch).replace(".xml", ".json"))
    items = []
    if os.path.isfile(state):
        with open(state, encoding="utf-8") as fh:
            items = json.load(fh)
    items = merge(items, item)
    with open(state, "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    feed = os.path.join(args.site, sparkle_policy.feed_name(args.arch))
    with open(feed, "wb") as fh:
        fh.write(render(items, args.arch))
    _sign(feed, args.sign_update or None)
    print(f"{feed}: {len(items)} items, newest {items[0]['tag']}")


if __name__ == "__main__":
    main()
