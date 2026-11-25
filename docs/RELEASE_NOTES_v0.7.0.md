# Clipper v0.7.0

This release is a hardening and packaging pass. The detection features from
0.6.0 remain, but the updater, installer, shutdown path, and frozen AI runtime
are now built to fail safely instead of leaving orphan processes or partial
installs.

## Updater

- Update URLs must be public HTTPS URLs; redirects are re-validated.
- Installer assets must use the `ClipperSetup-*.exe` name with no path
  separators, reserved names, control characters, or alternate streams.
- Downloads go to a unique per-run temp directory, are size-capped, reject
  HTML/empty/truncated files, and must match the release `SHA256SUMS.txt`.
- The detached helper now checks the installer exit code, times out a hung
  installer, cleans its temp files, and aborts before installing if Clipper
  cannot exit.
- Auto-install only runs when the executable is the exact path registered by
  the installer, not merely any path containing `Programs`.

## Shutdown and installer

- Closing the app closes preview dialogs, cancels workers, terminates active
  FFmpeg children, and saves settings.
- The installer closes the installed Clipper gracefully, waits, then falls back
  to terminating only that install's process.
- Install and uninstall remove only known Clipper files and directories. A
  user-selected install directory is never wiped recursively.
- Uninstall removes the `hatermedia/Clipper` QSettings registry key.

## Packaging

- The portable CLI/desktop builds now collect the same OCR/AI dependencies as
  the desktop installer (`rapidocr_onnxruntime`, `onnxruntime`, `faster_whisper`,
  `ctranslate2`, `tokenizers`, `pyclipper`, `shapely`, and `av`).
- The active PySide6 MSVC runtime and CTranslate2 Intel OpenMP runtime are
  bundled into the frozen app's `_internal` directory.
- The pinned faster-whisper `base.en` model is staged from the local Hugging
  Face cache and bundled for offline transcription.
- Third-party notices, the FFmpeg notice, the GPLv3 text, and full license
  texts for the bundled runtime are included with the app.

## Reliability

- Malformed Ollama JSON/response shapes no longer abort the remaining AI
  candidates.
- Lite mode keeps every bounded HUD block, including late-video round/goal
  banners, and samples both edges of each block.
- RapidOCR and YAMNet failures retry after a cooldown instead of latching for
  the process lifetime.
- Saved window geometry is clamped to the logical `availableGeometry()` without
  dividing by the device pixel ratio.
- Frameless title-bar hit testing uses the laid-out header and widget hit
  testing, so buttons remain clickable at high DPI.

## Verification

- `pytest -q` covers updater adversarial cases, helper syntax/exit codes,
  FFmpeg child cleanup, OCR/YAMNet cooldowns, Lite HUD retention, Ollama
  malformed responses, packaging contracts, and desktop shutdown/DPI contracts.
- A true clean Windows VM run is still recommended for DPI, multi-monitor, and
  update-from-0.6.0 coverage. A fresh standard-user profile on the build
  machine passed install, self-test, offline demo scan, and uninstall with no
  prior Clipper caches or external FFmpeg.
- FFmpeg is the gyan.dev 9.1 GPLv3 build. The release includes the exact FFmpeg,
  x264, and x265 source archives; remaining statically linked library versions
  are recorded in `FFMPEG_SOURCE_MANIFEST.txt`.
