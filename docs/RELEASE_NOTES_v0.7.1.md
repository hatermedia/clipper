# Clipper v0.7.1

This is a small update-path fix for 0.7.0.

## Fixed

- The update-ready button now reads **Restart and install** instead of using an
  ampersand that Qt rendered as a mnemonic underscore.
- The one-time upgrade from 0.6.0 no longer depends on the old 0.6.0 update
  helper. Installing 0.7.1 replaces that helper with the hardened 0.7.0+
  installer/relaunch flow.

## Included from 0.7.0

- Secure updater downloads, checksum verification, helper timeout/exit checks.
- Safe installer cleanup, graceful process close, and QSettings removal.
- Offline Whisper/RapidOCR/YAMNet runtime and bundled models.
- Safe shutdown with FFmpeg child cleanup.
- DPI-safe window clamping and widget-based titlebar hit testing.
- Notices, full license texts, and the FFmpeg/x264/x265 source package.

## Verification

- `pytest -q` passes.
- Frozen self-test reports Whisper, RapidOCR, and YAMNet loaded from the bundled
  install payload.
- Silent install, self-test, uninstall, and fresh-user profile install pass.
- The live GitHub updater downloads and verifies the published installer.
