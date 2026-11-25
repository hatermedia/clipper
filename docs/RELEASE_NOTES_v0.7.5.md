# Clipper v0.7.5

Simpler controls, native Windows pickers, and an Edge-style titlebar.

## Input and AI controls

- **Browse…** now opens the Windows folder picker directly. Clicking the
  “Drop a folder or video here” zone opens the Windows video-file picker
  directly. Dragging still accepts either a folder or a file.
- Removed the **Game** dropdown. The game preset is inferred automatically from
  each file's folder or file name, including one parent NVIDIA folder with
  several games.
- Removed the legacy **Fast review** mode. The only AI modes are **Director**
  (whole-clip vision + audio) and **Lite** (HUD OCR + Whisper + audio/motion).

## Export and Game Guard

- Removed the **Frame-accurate re-encode** toggle, encoder selector, and CRF
  control. Desktop exports are now always lossless stream copy: the original
  video and audio streams are kept, and exports finish almost instantly.
- Removed the Discord-presence sentence from the Game Guard help. Game Guard
  still uses local processes and paths, pauses analysis, and unloads the vision
  model while a known game is running.

## Titlebar

- Minimize, maximize/restore, and close now use thin Edge-style line icons with
  no gaps between the caption buttons and a matching hover treatment.

## Install

Download `ClipperSetup-0.7.5.exe`, run it, and launch Clipper. The installer is
per-user and preserves footage, caches, and settings during upgrades. The
portable zip is available for users who do not want an installer.

SHA-256 checksums are in `SHA256SUMS.txt` on the release page.
