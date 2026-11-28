# Clipper v0.9.0

Local test build. Not published.

Clipper 0.9 moves from highlight detection to a complete local clipping
workflow: keep a scan library, export platform-ready clips, reframe vertically,
inspect the director's evidence, and scan new recordings in the background.

## Clip library

- Every scan is saved locally with source paths, clip ranges, scores, reasons,
  keep/reject decisions, notes, tags, evidence, and export history.
- The Library dialog reopens previous scans and deletes saved history.
- A rescan inherits decisions for clips whose boundaries still match.
- The library is atomic JSON under `%LOCALAPPDATA%\Clipper\library`, with a
  corrupt-file backup instead of a silent overwrite.

## Creator export presets

- Lossless stream copy remains the default.
- YouTube Shorts, TikTok, Instagram Reels, square, landscape, Shorts HEVC, and
  frame-accurate H.264 presets are available in the desktop app and CLI.
- Batch export uses the existing checked-clip selection.
- Filename templates support `{source}`, `{index}`, `{start}`, `{end}`,
  `{duration}`, `{score}`, `{peak}`, `{preset}`, `{game}`, and `{date}`.
- NVENC is used when the installed FFmpeg build can actually encode; software
  fallbacks remain available.

## Automatic vertical reframe

- Action tracking follows the strongest motion.
- Facecam mode follows the largest stable face and falls back to action.
- Center crop is available when predictable framing is preferred.
- The crop path is smoothed and sent to FFmpeg as tracked commands.
- Dynamic-render failure falls back to a static crop rather than losing the
  export.

## Why this clip?

- The preview area now has a second tab with the director's evidence.
- Shows the transcript, HUD proof, audio and motion signals, reviewed windows,
  final-edit proof, confidence, notes, tags, and previous exports.
- Notes and tags are saved to the local library.

## Watch folders and scan queue

- Add watch folders without queueing the existing archive.
- New or changed recordings are queued after a 15 second settle period.
- The queue waits for idle input and Game Guard clearance by default.
- Pause, retry, clear-finished, per-file progress, and ETA are available.
- Running jobs are recovered after a crash or quit.
- Export output inside a watched folder is ignored.

## CLI

```powershell
clipper --input .\footage --export-preset shorts --reframe auto
clipper --input .\footage --export-preset square --name-template "{game}_{index:02d}"
clipper --input .\clip.mp4 --format shorts_hevc --reframe facecam
```

## Verification

- Full test suite and compile checks pass.
- Lite and Standard live scans found real Rocket League highlights with HUD,
  transcript, and audio evidence.
- Standard serialized MiniCPM and LFM3 with one server resident and a
  7,612 MiB peak.
- Real exports verified lossless, 1080 x 1920, 1080 x 1080, 1920 x 1080,
  and two-clip batch output.
- The 60 Hz vertical crop path stayed within 8 px per update and matched the
  source crop at 0.987 to 0.995 correlation.
- The 0.9.0 installer and portable package were built, extracted, installed to
  an isolated path, smoke-tested, and uninstalled while preserving the 0.8.4
  installation.
- Detailed results and remaining gaps are in
  [`VALIDATION_0.9.md`](VALIDATION_0.9.md).

## Not in this release

- Audio cleanup and enhancement
- Feedback-based personalisation
- Model and VRAM dashboard
- Diagnostics bundle
- Burned-in captions and transcript search
- Keyboard-first workflow and undo/redo
- Code signing and secure update infrastructure
- WinGet and MSIX packaging
- SBOM and reproducible builds
