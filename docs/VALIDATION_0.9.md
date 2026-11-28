# Clipper 0.9.0 validation

This record covers the local Clipper 0.9.0 test build. It is not a public
release validation record. The current public release remains 0.8.4.

## Test environment

- Windows 11 Pro, build 26200, 64-bit
- AMD Ryzen 5 3600
- NVIDIA GeForce RTX 3080, 10,240 MiB, driver 610.88
- Isolated test profile under `%TEMP%\clipper-090-localappdata`
- Bundled llama.cpp `b12776`, CUDA 12.4 runtime
- Models: LFM3-Omni-2B and MiniCPM-o 4.5

The normal `%LOCALAPPDATA%\Clipper` library and settings were not used for the
scan tests. The existing 0.8.4 install and release artifacts were preserved.

## Automated checks

```text
pytest -q
257 passed, 1 skipped
```

The skipped test is `tests/test_e2e.py`, which requires `CLIPPER_E2E=1`.
`compileall` passed, the source desktop smoke test passed, the frozen desktop
smoke test passed, and the static website check found no missing local assets.

## Clean AI runtime and model restore

The isolated profile was empty. Clipper's own installer functions were used to
download, verify, and install the runtime and both models.

| Component | Result |
| --- | --- |
| llama.cpp runtime | 749,426,307 bytes downloaded, ready |
| LFM3-Omni-2B | 2,049,471,328 bytes, both files SHA-256 matched |
| MiniCPM-o 4.5 | 6,121,827,584 bytes, both files SHA-256 matched |

The runtime server and both model folders reported ready. No download or
checksum failures occurred.

## Live AI scans

Both scans used real NVIDIA DVR gameplay recordings, the bundled llama.cpp
runtime, GPU analysis proxies, Whisper transcription, HUD OCR, and LFM3 ears.

| Run | Source | Model | Time | Clip | Score | Peak VRAM |
| --- | --- | --- | ---: | --- | ---: | ---: |
| Lite | Rocket League 2025.08.01, 73.9 s | LFM3-Omni-2B | 82.6 s | 44.22-73.42 s | 85 | 4,087 MiB |
| Standard | Desktop 2025.11.29, 90.3 s | MiniCPM-o 4.5 + LFM3 | 106.8 s | 14.8-45.59 s | 99 | 7,612 MiB |

Lite returned one clip with a HUD goal, 23 transcript lines, 2 HUD lines, a
trusted sarcastic LFM3 reading, 6 reviewed windows, and one llama-server at a
time. Peak used memory was 4,087 MiB; free memory returned to 8,977 MiB after
shutdown.

Standard returned one clip with `B997SCORED!`, 24 transcript lines, a HUD goal,
trusted laughter and the line "We gotta win!", and 9 reviewed windows. The log
showed the vision model being released before the ears pass and the audio model
being released before the final edit. Peak used memory was 7,612 MiB, minimum
free memory was 2,440 MiB, and only one llama-server was resident at a time.
Free memory returned to 8,970 MiB after shutdown.

### Bugs found during live testing

- The final-refine model returned the prompt placeholders "one short sentence"
  and "the concrete proof or the contradiction" into the evidence record. The
  placeholder values are now discarded, and a fresh Lite scan verified the
  corrected record.
- The first Shorts export used a 2 fps crop path, which FFmpeg applied as
  stepwise jumps. The command stream is now interpolated at 60 Hz. The largest
  crop move dropped from 115 px per update to 8 px per update.

### Ranking limit

Each selected source produced one surviving story beat, so the two-config
scans verified scoring and timestamp selection but did not provide a multi-clip
ranking sample. Multi-clip sorting remains covered by unit tests, not by these
two live recordings.

## Creator export verification

The live Lite clip was exported through every preset. The batch run included
the Lite clip and the Standard clip. All outputs had audio and no export errors
or warnings.

| Preset | Output | Video | Audio | A/V duration delta |
| --- | --- | --- | --- | ---: |
| Lossless | 1920 x 1080 | H.264 | AAC | 0.002 s |
| YouTube Shorts | 1080 x 1920 | H.264 | AAC | 0.017 s |
| TikTok | 1080 x 1920 | H.264 | AAC | 0.017 s |
| Instagram Reels | 1080 x 1920 | H.264 | AAC | 0.017 s |
| Landscape 1080p | 1920 x 1080 | H.264 | AAC | 0.017 s |
| Square | 1080 x 1080 | H.264 | AAC | 0.017 s |
| Batch | 2 files, 1080 x 1920 | H.264 | AAC | n/a |

The batch run exported two different real clips from two different source
recordings. The filename templates produced the expected source, index, and
preset tokens.

### Vertical reframe inspection

The Shorts path was inspected at the beginning, middle, and end, plus a 17-frame
strip across the goal sequence.

- Source crop path: 118 tracked samples, x from 212 to 743 in a 0 to 1,312 range.
- 60 Hz command stream: 1,757 crop updates, maximum 8 px between updates.
- Output frames matched the corresponding source crop at 0.987 to 0.995
  correlation across the motion strip.
- The middle output frame matched the planned crop within 6 px at half scale.
- Edge means were 53.7 to 88.6, so there were no black borders.
- The car, ball, goal explosion, and score remained visible.
- The full 16:9 goal banner cannot fit inside a 9:16 crop; its outer text is
  clipped. This is inherent to the target aspect ratio, not a stretch or black
  border.

Lossless output duration was 29.214 s. Re-encoded outputs were 29.183 s video
with 29.200 s audio. The largest audio/video duration difference was 0.017 s.

## Library and queue persistence

The persistence test used the real 0.9 library and workflow code with an
isolated data directory.

- A Standard scan was saved to the library.
- One clip was rejected and marked with the note `0.9 persistence check` and
  tags `verified`, `to-post`.
- A real Shorts export was recorded in the clip's export history.
- A new process reopened the library and restored the scan, keep state, note,
  tags, evidence, and export history.
- The desktop loaded the scan, showed the rejected checkbox state, restored the
  note and tags, and populated the evidence panel.
- A watch folder detected one newly added real video file.
- The queue job was saved as running, the process was restarted, and recovery
  returned it to the queue with one attempt and the message
  `Resuming after restart`.

## Installer and frozen app

Pending final package build.

## Remaining limitations

- No multi-clip live ranking sample was produced by the two selected sources.
- Facecam reframe was not tested on real facecam footage.
- HEVC hardware encoding was not exercised on this machine.
- Live gaming coexistence and non-NVIDIA hardware tests remain out of scope for
  this milestone.
- New-file detection used a real trimmed video with a settled timestamp, not a
  full ShadowPlay or Steam write cycle.
- The installer is unsigned, so SmartScreen warnings remain.
- The public website and public download links remain on the 0.8.4 stable
  release until publishing is authorized.
