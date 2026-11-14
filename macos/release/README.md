# Publishing macOS releases with Sparkle

The macOS releases are built and published by the releases repository
(`rocco-labs/WinZapp_Python`, `.github/workflows/mac-release.yml` on its
`mac-releases` branch). This folder holds what that workflow runs for Sparkle,
and the change it needs: `mac-release-sparkle.patch` (against
`mac-releases` at 011b923; `git apply` it there). How the app uses Sparkle,
and what it checks, is in `../README.md`, "Updates through Sparkle".

## What the workflow change does

- **Build** (each architecture): passes `WINZAPP_SPARKLE_PUBLIC_KEY` and
  `WINZAPP_SPARKLE_FEED_BASE` (repository variables) to `build_app.py`, which
  writes the Sparkle keys into the app. A tag built before Sparkle ignores
  them. Nothing else changes in the build.
- **Publish**: unchanged. Every release still has both zips, both provenance
  files and `SHA256SUMS.txt`: builds from before Sparkle update through them,
  and Sparkle builds check the provenance's tag against the official
  repository.
- **appcast-plan** (new, Linux, every run that was not cancelled): lists the
  published releases the appcast still lacks, from the releases themselves
  and the appcast's own state, not from the run's plan. A release whose
  appcast job failed, or that an earlier run published, is picked up by the
  next run. Only releases with both zips and `SHA256SUMS.txt`, from tags whose
  macOS layer has Sparkle (`macos/release/appcast.py` in the tag), are listed,
  and never one older than the newest item of its channel already in that
  feed: a feed keeps only its newest items, so an older tag would be pruned
  and queued again on every run.
- **appcast** (new, macOS, only when there is something to add): for each
  such tag, downloads the **published** zips and checks them against the
  release's `SHA256SUMS.txt`, and fetches only the tag's changelogs and
  `language_map.json` (data, never run). Sparkle's `sign_update` comes from
  the official Sparkle 2.10.0 archive, pinned by SHA-256 in the workflow.
  Then, in the one step that sees the private key, the branch's **own pinned
  copy** of `appcast.py` (`.github/mac-release-tools`, added by the patch)
  signs those very bytes (the key reaches `sign_update` on standard input
  only) and adds them to `appcast-arm64.xml` / `appcast-x86_64.xml`, signing
  each feed. That step runs no code from the tag it publishes. A re-run over a
  tag already in the appcast does nothing, and a signature is never made over
  anything but the downloadable asset. Then it commits the feed's state to
  the `appcast` branch and deploys the feeds with `actions/deploy-pages`.
  The pinned copy is updated by hand, after review, when `appcast.py` changes
  here; `tests/test_macos_appcast.py` checks the patch carries exactly this
  tree's files.

Nothing runs for Sparkle until the variables are set: with
`SPARKLE_PUBLIC_ED_KEY` empty, builds carry no Sparkle keys and both appcast
jobs are skipped.

## The key rule: every release in the appcast carries the Sparkle key

Once a Sparkle build is installed anywhere, every release offered to it must
carry the same `SUPublicEDKey`. Sparkle refuses an update that drops the key
("Sparkle only supports rotation, but not removal of (Ed)DSA keys",
SUUpdateValidator.m), and it finds out only after the user has downloaded the
whole zip (about 380 MB). So:

- the plan only lists tags whose macOS layer has Sparkle;
- before signing, `appcast.py sign-zip` opens the **published** zip and reads
  `WinZapp.app/Contents/Info.plist`: it must carry this repository's
  `SPARKLE_PUBLIC_ED_KEY`, be a build of that very tag (`WinZappReleaseTag`),
  and have a complete Sparkle configuration (feed, CFBundleVersion of the
  tag). Otherwise that release is not added (neither architecture), the run
  still publishes the other releases, and then fails with an error naming it.
- A release refused this way is asked about again on every run until a newer
  release of its channel is in the appcast. Fix it by building that tag again
  with `SPARKLE_PUBLIC_ED_KEY` / `SPARKLE_FEED_BASE` set.

Never remove `SPARKLE_PUBLIC_ED_KEY` from the repository variables, and never
change it without a key rotation plan: builds without it, or with another key,
can no longer reach the users of earlier Sparkle builds.

## Where the appcast lives, and why

GitHub Pages: `https://rocco-labs.github.io/WinZapp_Python/appcast-<arch>.xml`.

- A fixed address, independent of any release. `releases/latest/download/...`
  resolves only the newest non-prerelease, and alphas are prereleases, so the
  alpha items could not live there. A dedicated release (a tag named
  `appcast` whose asset is replaced) would be a delete-then-upload, briefly
  missing on every update, and it would appear in the `/releases` list that
  older builds' updater reads.
- **Deployed by the workflow, not by a branch push.** GitHub's documentation
  ("Configuring a publishing source for your GitHub Pages site"): "Commits
  pushed by a GitHub Actions workflow that uses the GITHUB_TOKEN do not
  trigger a GitHub Pages build." A branch-published site would never update.
  `actions/upload-pages-artifact` and `actions/deploy-pages` (pinned by
  commit) publish the feeds in the same job, and a failed deployment fails
  the run where it can be seen.
- The `appcast` branch keeps `appcast-<arch>.json` (the items) and the signed
  XML: the state the next run builds on, and the history of what was offered
  when. The XML is rebuilt from the JSON and signed again on every change,
  never edited in place.

## Channels

One feed per architecture (each release has a zip per Mac, and Sparkle has no
"Intel only" requirement). Alpha items carry `<sparkle:channel>alpha</sparkle:channel>`;
stable (and beta) items carry none, so they are in Sparkle's default channel,
which every app sees. The app allows the `alpha` channel only while "Check for
alpha updates" is on, which is exactly how WinZapp chooses releases today. A
feed keeps the newest 5 alphas and 3 stables (alphas never push the stables
out), and only the newest item of each channel carries its release notes,
taken per language from the tag's `client/changelog_<locale>.txt` (the
upstream release notes when the changelog has no section for it). An alpha's
notes start with the pull requests its upstream release lists, since the
changelog section is the same for every alpha heading to one release. These
are the fallback: the app shows its own notes, what changed between the
version it runs and the one offered, whenever it can fetch them
(`winzapp_mac/sparkle_notes.py`).

## Delta updates: no

The app refuses any item that offers deltas: what the official tag stands for
is the release's full zip, and that is the one file the app lets Sparkle
download. Deltas would also need the previous releases' archives in every run
(about 330 MB each).

## One-time setup (the maintainer of the releases repository)

1. **Make the key pair once, on your Mac**, with the Sparkle build
   `build_app.py` pins (it is unpacked in `macos/cache/sparkle-2.10.0` after
   any build). `bin/generate_keys --account winzapp-macos` stores the private
   key in your login keychain and prints the public key. Then
   `bin/generate_keys --account winzapp-macos -x <file>` exports the private
   key to a file, for the secret below.
2. **Back up the private key** (the exported file's contents) in your
   password manager. If it is lost, no Sparkle build can be updated through
   Sparkle again (`SURequireSignedFeed` trusts that key and nothing else)
   until a new build with a new key reaches every user some other way.
3. **In the releases repository**, Settings > Secrets and variables > Actions:
   - secret `SPARKLE_ED_PRIVATE_KEY`: the exported file's contents;
   - variable `SPARKLE_PUBLIC_ED_KEY`: the public key generate_keys printed;
   - variable `SPARKLE_FEED_BASE`: `https://rocco-labs.github.io/WinZapp_Python`.
   Then delete the exported file.
4. **Settings > Pages**, "Build and deployment", Source: **GitHub Actions**.
   GitHub then creates the `github-pages` environment; under Settings >
   Environments > github-pages, its deployment branches must allow the
   branch this workflow runs from (the default branch, for the schedule).
5. **Apply `mac-release-sparkle.patch`** to `mac-releases`.

Until a Sparkle tag has been published and deployed, a Sparkle build's check
finds no feed and offers nothing.
