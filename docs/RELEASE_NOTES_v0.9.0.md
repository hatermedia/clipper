# Clipper v0.9.0

Windows x64 release. Published 2026-11-28.

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

## Packaging and provenance

- Both packages include `BUILD_INFO.txt` with the application version, full
  Git commit, build date, platform, build type, and Python, PyInstaller, and
  PySide6 versions.
- `Clipper.exe` carries 0.9.0 file and product version resources, the Clipper
  product name, and hatermedia branding.
- The release is built from a clean working tree. Stale editable-install
  metadata is removed, a clean 0.9.0 package record is written, and the build
  fails if a personal filesystem path or stale Clipper metadata remains.
- Packaging regression tests cover editable `direct_url.json` metadata, local
  paths in text and binary files, `BUILD_INFO.txt`, and the Windows version
  resource.

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
- The corrected 0.9.0 installer and portable package were rebuilt from the
  remediation commit, audited for stale metadata and local paths, extracted,
  installed to an isolated path, smoke-tested, and uninstalled while preserving
  the 0.8.4 installation.
- The final checksums are published in `SHA256SUMS-0.9.0.txt`; the build commit
  is recorded inside `BUILD_INFO.txt` in both packages.
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
