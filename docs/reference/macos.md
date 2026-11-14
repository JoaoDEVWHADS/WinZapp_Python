# macOS build (`macos/`)

A separate, Mac-only layer (`macos/winzapp_mac`) replaces Windows-only
pieces at startup; the Windows build never runs it. In `client/` the Mac
has only `<key>_macos` strings and `start.js`'s user agent. Its maintainer is
listed in `macos/README.md`; build and updater details are there too.

What it asks of a Windows change:

- A rename or removal of something the layer patches or reads fails
  `tests/test_macos_layer_contract.py` (fix the name in `macos/winzapp_mac`
  or tell its maintainer).
- A string that names Windows may get a `<key>_macos` variant beside it,
  kept in every locale like any key.
- Nothing else is constrained, and a Windows change never needs a Mac.

## Commit provenance

A Mac release must declare an official tag and commit, and the Mac updater
checks that the tag exists in `gabrielhhaber/WinZapp_Python` and points at the
declared commit, on top of the Apple Team ID, `codesign` and `spctl` checks.
That is a declaration checked against our repository; it does not prove the
zip was built from that commit (that needs an attestation from an official
workflow, or a maintainer signature over the zip hash as on Windows). The
running version is the tag in Info.plist (`WinZappReleaseTag`), never
`client/version.py`; a build without it never updates. Tag protection is only
as strong as the repository's tag rules: the ruleset "Allow tag creation only
for admins" (id 20587521) excludes `refs/tags/v*alpha`, a known limit.
The pure verifier is `macos/winzapp_mac/provenance.py`; its tests run in the
normal `pytest` (`tests/test_macos_provenance.py`). The threat model, the
verification sequence and the release steps are in `macos/README.md`, "Commit
provenance". For a Windows change: nothing, except that the official
repository name is pinned in `provenance.py`.

Release builds with a Sparkle key update through Sparkle 2's standard
windows (`macos/winzapp_mac/sparkle_mac.py`), downloaded in the background
and installed when WinZapp quits. There the official tag is checked before
Sparkle offers or downloads a release, and again at "Ready to Install" when
the user started the download; the zip's bytes are left to Sparkle's own
signature checks. What that covers
and what remains: `macos/README.md`, "Updates through Sparkle".
