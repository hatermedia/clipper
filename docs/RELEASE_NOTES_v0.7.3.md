# Clipper v0.7.3

This release is a UX, onboarding, and public-site cleanup pass.

## App

- Single-clicking a highlight only selects it and shows its peak frame. It does
  not open a preview window or start playback.
- The preview panel is now the actual inline player with Play/Pause, -5s/+5s,
  a timeline, time readout, and Open.
- Highlights are a flat list with a Video column. No per-video expandable
  groups.
- Window controls are uniform, icon-based, tooltip-free, and anchored to the
  top-right title bar.
- Combo/spin arrows use a clean custom chevron asset.
- Help tooltips now wait longer, ignore clicks, and linger briefly when the
  pointer leaves the `?` icon.
- Advanced settings explain Max clips, Sample FPS, Proxy width, CPU threads,
  Pre-roll, Post-roll, and Low-power mode.
- Export explains Output, Frame-accurate re-encode, encoder choice, and CRF.
  CRF now defaults to Auto (20) and remains editable.
- The drop zone is clickable and offers folder or video selection.
- First-run AI setup clearly says Lite mode is ready with no extra install.
  When Ollama is available it can pull the recommended model. 6 GB cards use
  gemma3:4b; 8 GB+ use qwen2.5vl:7b. The 3B recommendation is retired.
- Game Guard uses a 196-title built-in map plus Unreal shipping-process and
  major game-library path detection. Custom titles can be added in
  `%LOCALAPPDATA%\Clipper\games.json`.

## Public site and README

- Native-app-first website with the current app palette, screenshots, and
  install flow.
- Removed the CLI guide, web UI demo, paid clip service, and service pages.
- Replaced the odd “Is it really a native app?” FAQ with “Is it really all
  local?”.
- Updated the 6 GB guidance and documented what the installer includes.
- Added a clear explanation of smart padding/merging and low-power mode.

## Verification

- `pytest -q` passes.
- Single-click selection stays paused; inline playback and seeking verified.
- Flat-list selection/export verified.
- Frozen self-test reports Whisper, RapidOCR, and YAMNet loaded.
- Installer, uninstaller, update helper, and live updater verified.
