# Clipper v0.8.3

Reliable updates that remember a downloaded installer and finish the job on the
next launch.

## Updates

- **Downloaded installers are cached** under
  `%LOCALAPPDATA%\Clipper\updates\<version>\`. Retrying, reopening the app, or
  clicking Download again reuses the verified installer instead of downloading
  the whole app again.
- **Later now actually means next launch.** A downloaded, SHA-256 verified
  installer is recorded as pending. On the next Clipper launch it installs
  silently and reopens the new version.
- **Restart and install is direct.** Removed the confirmation dialog that could
  hide or lose the click. The button starts the installer helper immediately.
- **The helper must confirm it started** before Clipper closes. If it does not,
  the app stays open and shows an error instead of silently doing nothing.
- Pending installers are cleared after the new version launches. Invalid or
  incomplete pending files are discarded.

The update payload is still the signed full installer. Clipper's frozen bundle
contains the runtime and offline Whisper model, so a true binary delta would
need a separate signed patch format. Caching prevents repeated full downloads;
a patch pipeline can be added later if you want smaller first downloads.

## Install

Download `ClipperSetup-0.8.3.exe`, run it over the existing install, and launch
Clipper. SHA-256 checksums are in `SHA256SUMS.txt` on the release page.
