"""What Sparkle may offer and install, decided without Sparkle.

Pure standard library (plus provenance.py): no PyObjC, no wx, so the normal
`pytest` on any platform exercises every decision, and macos/build_app.py
(which runs before any dependency is installed) writes the same Info.plist
keys the app later reads. sparkle_mac.py is only the bridge to Cocoa.

What is checked, and why only this. Against the threat model of
macos/README.md, "Commit provenance" (whoever controls the releases
repository and its CI secrets: the Developer ID certificate, the notary key,
SHA256SUMS and provenance files, and Sparkle's EdDSA key), byte checks of the
zip prove nothing that attacker could not also produce. The one guarantee
they cannot fake is the official repository's: the release is an existing
tag of gabrielhhaber/WinZapp_Python, pointing at the commit its provenance
declares, newer than the running tag. So Sparkle may offer or download a
release only when that holds (decide(), asked before anything is shown or
downloaded, for the scheduled background download too), and, where Sparkle
still asks at "Ready to Install" (a check the user started), may install it
only when it still holds at that moment (install_choice()). An update
downloaded in the background installs when WinZapp quits, with no question
left for a second check: the offer-time one is its gate. Sparkle's own checks
(signed appcast, EdDSA signature of the zip, code signing) come on top, as
integrity of the download.
"""

import base64
import binascii

from . import provenance

ALPHA_CHANNEL = "alpha"                 # <sparkle:channel> of an alpha item
# The update_coord claim (its own file, like WPP_PROMPT_FILE) held by the one
# account process that runs scheduled checks.
CLAIM_FILE = "sparkle_updater.json"
SCHEDULED_CHECK_INTERVAL = 3 * 60 * 60  # WinZapp's own UpdateChecker._RETRY_INTERVAL
MINIMUM_SYSTEM_VERSION = "12.0"         # Sparkle 2.10 and the bundled Chrome both need it

PUBLIC_KEY = "SUPublicEDKey"
FEED_URL = "SUFeedURL"

# Sparkle 2.10.0's enums (SPUUpdateCheck.h, SPUUserUpdateState.h:29-60,
# SUErrors.h:41-68) and the enclosure's default installation type.
CHECK_USER = 0                          # SPUUpdateCheckUpdates
CHECK_BACKGROUND = 1                    # SPUUpdateCheckUpdatesInBackground
CHOICE_SKIP, CHOICE_INSTALL, CHOICE_DISMISS = 0, 1, 2
STAGE_NOT_DOWNLOADED, STAGE_DOWNLOADED, STAGE_INSTALLING = 0, 1, 2
INSTALLATION_APPLICATION = "application"
ERROR_DOMAIN = "SUSparkleErrorDomain"
# Sparkle's UI driver aborts on this code without showing anything, even for
# a check the user asked for (SPUUIBasedUpdateDriver.m:482-483); every other
# code is shown to the user as an error (:484-491).
SILENT_ABORT = 4007                     # SUInstallationCanceledError
REFUSED = 4009                          # SUNotValidUpdateError
NO_UPDATE = 1001                        # SUNoUpdateError

PROCEED, REFUSE, VERIFY = "proceed", "refuse", "verify"


def feed_name(arch):
    """One appcast per architecture: each release has a zip per Mac, and
    Sparkle has no "Intel only" requirement to tell them apart in one feed."""
    return f"appcast-{arch}.xml"


def bundle_localization(locale):
    """The localization name of a WinZapp locale, as Sparkle's own folders
    name them (pt-BR.lproj, es.lproj): the language alone, except where
    WinZapp has two variants of it (pt-BR, pt-PT)."""
    return locale if locale.startswith("pt-") else locale.split("-")[0]


def bundle_localizations(locales):
    """CFBundleLocalizations for WinZapp's locales (language_map.json),
    English first, each once."""
    names = []
    for name in ["en"] + [bundle_localization(c) for c in locales]:
        if name not in names:
            names.append(name)
    return names


def valid_public_key(value):
    """True for a base64 Ed25519 public key (32 bytes), what generate_keys
    prints."""
    if not isinstance(value, str) or not value.isascii():
        return False
    try:
        return len(base64.b64decode(value, validate=True)) == 32
    except (binascii.Error, ValueError):
        return False


def valid_feed_base(value):
    """An https base the appcasts are served from, without a trailing slash
    (Sparkle refuses an http feed; so does this, earlier)."""
    return (isinstance(value, str) and value.isascii() and value.startswith("https://")
            and len(value) > len("https://") and not value.endswith("/")
            and not any(c.isspace() for c in value))


def plist_keys(public_key, feed_base, arch, locales=()):
    """Info.plist keys of a Sparkle build (build_app.py writes them before
    signing). Each value is a WinZapp decision, not a Sparkle default:

    * SUEnableAutomaticChecks: on, as WinZapp's updates_enabled is by default;
      it also keeps Sparkle from asking its own permission question on the
      second launch, since Settings > General already asks it. The setting
      itself is applied at run time (sparkle_mac), so it stays the one switch.
    * SUAllowsAutomaticUpdates and SUAutomaticallyUpdate on: updates are
      downloaded in the background and installed when WinZapp quits, as in
      other Mac apps. A scheduled check then runs Sparkle's automatic driver
      (SPUUpdater.m:622, while automaticallyDownloadsUpdates is on), which
      downloads silently (SPUAutomaticUpdateDriver.m:87-97) once
      updater:shouldProceedWithUpdate:... has let the release through, and
      leaves the prepared installer waiting for the app to end
      (:104-128, updater:willInstallUpdateOnQuit:...). A later check shows it
      in Sparkle's standard window with "Install and Relaunch"
      (SPUUpdater.m:903-906, SPUUIBasedUpdateDriver.m:236-237). The run-time
      switch is WinZapp's "check for updates automatically" setting, which
      sparkle_mac applies to automaticallyChecksForUpdates and
      automaticallyDownloadsUpdates alike; this key is only the default.
    * SURequireSignedFeed (with its prerequisite SUVerifyUpdateBeforeExtraction)
      and no expiry for a signing failure: an unsigned or re-signed appcast is
      never trusted, however long it stays that way.
    * CFBundleLocalizations: WinZapp's languages, so Sparkle's windows use its
      own translations of them; see sparkle_mac.py for which one it picks.
    """
    if not valid_public_key(public_key):
        raise ValueError("not a base64 Ed25519 public key")
    if not valid_feed_base(feed_base):
        raise ValueError("the appcast base must be an https URL without a trailing slash")
    keys = {
        FEED_URL: f"{feed_base}/{feed_name(arch)}",
        PUBLIC_KEY: public_key,
        "SUEnableAutomaticChecks": True,
        "SUAllowsAutomaticUpdates": True,
        "SUAutomaticallyUpdate": True,
        "SUScheduledCheckInterval": SCHEDULED_CHECK_INTERVAL,
        "SUVerifyUpdateBeforeExtraction": True,
        "SURequireSignedFeed": True,
        "SUSignedFeedFailureExpirationInterval": 0,
    }
    if locales:
        keys["CFBundleLocalizations"] = bundle_localizations(locales)
    return keys


def configured(info):
    """True when this build's Info.plist turns Sparkle on: a public key, an
    https feed, and a CFBundleVersion that is the bundle version of its release
    tag (without it Sparkle's "newer" and provenance's would not agree).
    Anything else leaves updates to updater_mac, as before Sparkle."""
    tag = provenance.running_release_tag(info)
    feed = info.get(FEED_URL)
    return bool(tag and valid_public_key(info.get(PUBLIC_KEY))
                and isinstance(feed, str) and feed.startswith("https://")
                and info.get("CFBundleVersion") == provenance.bundle_version(tag))


def allowed_channels(settings):
    """Sparkle channels for WinZapp's "check for alpha updates" setting, read
    fresh on every check like UpdateChecker._alpha_enabled(). The default
    channel (stable) is always allowed; alpha only when explicitly on."""
    try:
        alpha = settings.get("general", {}).get("alpha_updates_enabled", False) is True
    except Exception:
        alpha = False
    return [ALPHA_CHANNEL] if alpha else []


def updates_enabled(settings):
    try:
        return settings.get("general", {}).get("updates_enabled", True) is not False
    except Exception:
        return True


def zip_url(repo, tag, arch):
    """The one URL an appcast item may point at: this Mac's zip in the
    release of *tag* of the releases repository, where updater_mac has always
    downloaded it from."""
    return f"https://github.com/{repo}/releases/download/{tag}/WinZapp-macOS-{arch}.zip"


def item_tag(version, display_version):
    """The release tag an appcast item stands for, or "". The item's
    shortVersionString is the tag's version and its sparkle:version must be
    that tag's bundle_version(), so Sparkle's choice and provenance's tag are
    the same release."""
    if not isinstance(display_version, str):
        return ""
    tag = "v" + display_version
    if not provenance.is_release_tag(tag) or version != provenance.bundle_version(tag):
        return ""
    return tag


def decide(item, repo, arch, running_tag, verdict):
    """(action, tag, detail) for the update Sparkle wants to show.

    *item* is {"version", "display_version", "url", "deltas",
    "installation_type"} read from Sparkle's SUAppcastItem; *verdict* is None
    (provenance not asked yet) or (ok, detail) from
    updater_mac.release_provenance() for that tag.

    PROCEED: Sparkle may show it. VERIFY: ask the official repository first
    (Sparkle aborts silently meanwhile). REFUSE: never shown, never
    downloaded (*detail* says why)."""
    tag = item_tag(item.get("version"), item.get("display_version"))
    if not tag:
        return REFUSE, "", "the appcast item does not name a release tag"
    if item.get("url") != zip_url(repo, tag, arch):
        return REFUSE, tag, "the appcast item does not point at this release's zip"
    if item.get("deltas"):
        return REFUSE, tag, "the appcast item offers delta updates"
    if item.get("installation_type") != INSTALLATION_APPLICATION:
        return REFUSE, tag, "the appcast item is not an application update"
    if not provenance.tag_is_newer(tag, running_tag):
        return REFUSE, tag, "release is not newer than the running version"
    if verdict is None:
        return VERIFY, tag, ""
    ok, detail = verdict
    return (PROCEED, tag, "ok") if ok else (REFUSE, tag, detail)


def install_choice(choice, verdict):
    """The answer Sparkle gets at "Ready to Install", its last question
    before it installs, in a check the user started (a background download
    never asks it: it installs on quit). *choice* is the user's; *verdict* the result of asking
    the official repository (and checking the appcast item) again just now,
    None when it was not asked because the user did not choose to install.

    Only an install whose release still holds goes ahead. Anything else is
    SPUUserUpdateChoiceSkip, which at that point cancels the prepared
    installer (SPUCoreBasedUpdateDriver.m:313-314 -> SPUInstallerDriver.m:
    563-572 -> AppInstaller.m:681-684, the installer exits) without marking
    the release as skipped: from "Ready to Install" the choice goes straight
    to finishInstallationWithResponse: (SPUUIBasedUpdateDriver.m:420-425),
    not through the update window's handler that records skips (:282-283).
    The release is offered again at the next check. Unreachable GitHub counts
    as a refusal (fail closed): nothing is lost but the download. Left
    unanswered, the window lets the update install when WinZapp quits, like
    one downloaded in the background."""
    if choice == CHOICE_INSTALL and verdict is not None and verdict[0]:
        return CHOICE_INSTALL
    return CHOICE_SKIP
