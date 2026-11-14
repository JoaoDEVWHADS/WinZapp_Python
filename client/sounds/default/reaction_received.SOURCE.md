# Reaction notification sound

- Bundled file: `reaction_received.ogg`.
- User-supplied original: `notification_message-notify-4-310754.mp3`.
- Source: Pixabay, "notify 4" (item 310754) by Notification_Message,
  uploaded 2025-03-10:
  <https://pixabay.com/sound-effects/notification-message-notify-4-310754/>.
  The page states "Free for use under the Pixabay Content License". The
  maintainer compared the download with the bundled sound on 2026-10-06 and
  confirmed it is the same recording.
- Original SHA-256: `dd16a078341265bde60e7a13b993f93ae37c174eb14214408c7d065792baa539`.
- OGG SHA-256: `133feafc6d613965f76a49fa2377c23669022426769a7b955de981b25cfa9b81`.
- Converted with FFmpeg to OGG Vorbis (`-map_metadata -1 -vn -c:a libvorbis
  -q:a 5`), preserving the full approximately 2.87-second stereo recording.

This third-party sound is used as part of WinZapp's notification interface.
It is not relicensed under the repository's software license. See the
[Pixabay Content License](https://pixabay.com/service/license-summary/) and
[Pixabay FAQ](https://pixabay.com/service/faq/). The license forbids
distributing the sound on its own ("on a Standalone basis"); shipping it as
part of WinZapp's notification interface is not that.
