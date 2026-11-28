# Clipper 0.9 development validation

This record covers the 0.9 workflow work in the working tree. It is not a release
validation record. The current public release remains 0.8.4.

## Automated checks

```text
pytest -q
255 passed, 1 skipped
```

The skipped test is `tests/test_e2e.py`, which requires `CLIPPER_E2E=1`. The new
export preset test runs FFmpeg directly and covers lossless copy, a tracked
vertical render, and a center-crop render.

New coverage includes:

- Library save/load, rescan decision inheritance, corrupt-file backup, export
  history, delete, and pruning
- Preset registry, filename templates, path sanitization, and output suffixes
- Crop geometry, smoothing, clamping, command generation, and a generated-video
  reframe path
- Watch baseline, settle time, exclusions, active-folder dedupe, queue lifecycle,
  pause, retry, ETA, and crash recovery
- Director evidence collection, evidence merging, and JSON round-trips

## Desktop checks

The desktop app was created on the local Windows machine, the library and queue
dialogs were rendered, a stored scan was reopened, notes and tags were edited,
and a queue job was completed into the library. The 1280 x 840 layout was
checked by screenshot. A window smoke test also passed.

## Real-media export check

Source: an Arc Raiders DVR recording at 1920 x 1080, 90.2 seconds, with audio.

- A 3 second clip was exported with the **YouTube Shorts** preset and automatic
  reframe.
- Output: 1080 x 1920 H.264, 180 frames, AAC stereo, about 7.1 MB.
- FFmpeg reported no errors or warnings.
- A 10 second clip was exported at 540 x 960 with automatic action tracking.
  The crop path moved from x=337 to x=760 in a 0 to 1,312 range. No errors or
  warnings were reported.

These checks prove the export and crop pipeline works on real 1080p gameplay
footage. They do not prove highlight quality, because the local AI runtime and
models were removed before this work.

## Not yet validated

- Live AI direction on new footage with the bundled models
- New-recording detection during an actual ShadowPlay write cycle
- Facecam tracking on real facecam footage
- HEVC hardware encoding on this machine
- Multiple GPUs or non-NVIDIA systems
- Library performance with hundreds of large scans
- Upload behavior on YouTube, TikTok, or Instagram

Review vertical exports before posting. Reframe tracking is best-effort on fast
cuts, dark scenes, menus, and unusual HUD layouts.
