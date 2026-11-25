# Clipper v0.7.2

This release focuses on browsing and previewing highlights.

## Changed

- Highlights are now a flat clip list. Videos no longer create expandable
  groups; every detected clip is one row with its source video in the Video
  column.
- Single-clicking a clip only selects it and shows its first/peak frame. It no
  longer starts playback or opens a separate preview dialog.
- The preview area below the list is now a real inline player with Play/Pause,
  -5s/+5s, a timeline slider, time readout, and Open.
- Double-clicking a clip starts inline playback. The Play button, poster, and
  timeline remain available for normal use.

## Verification

- `pytest -q` passes.
- Inline player test: playback starts, position advances, seeking works, and
  the video page is shown.
- Single-click test: selecting a row stays paused on the poster; double-click
  starts playback.
- Frozen self-test still reports Whisper, RapidOCR, and YAMNet loaded.
- Installer/uninstaller and the published update path remain verified.
