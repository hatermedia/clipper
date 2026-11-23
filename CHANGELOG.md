# Changelog

All notable changes to Clipper are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.1] - 2026-11-24

### Added

- `clipper --version` / `clipper -V`.
- Live auto-update path verified end to end: an installed 0.3.0 build detects
  0.3.1, downloads the installer, verifies its SHA-256, installs silently, and
  reopens as 0.3.1.

### Fixed

- The portable README bundled in the native zip and installer now documents the
  installer/auto-update flow, GPU-on-by-default behavior, and optional local AI.
- Launching the installer from a source/pip CLI no longer tries to reopen
  `python.exe`; it leaves the installed app on the Start Menu.

## [0.3.0] - 2026-11-24

### Added

- **Windows installer** (`ClipperSetup-0.3.0.exe`): per-user install to
  `%LOCALAPPDATA%\Programs\Clipper`, no admin prompt, Desktop and Start Menu
  shortcuts, Add/Remove Programs entry, and a standard uninstaller. Silent
  install (`/S`) supports in-place upgrades.
- **Built-in auto-updater**: checks GitHub Releases on launch and from the
  `Updates` button, downloads the installer, verifies its SHA-256 against the
  release's `SHA256SUMS.txt`, then installs silently and relaunches. No update
  is installed without a matching checksum.
- `clipper update` and `clipper update --install` for checking and installing
  releases from the terminal.
- **Optional local AI review** using Ollama vision models (default
  `qwen2.5vl:7b`, 100% GPU). It center-crops the game viewport, adds a zoomed
  top-HUD frame for the score and kill feed, rejects black/desktop/menu frames,
  and reviews candidate windows with structured JSON. Results are cached.
- CLI flags: `--ai`, `--ai-model`, `--ai-game`, `--ai-min-confidence`, and
  `--ai-max-candidates`.
- Native AI controls: model selector, game preset, and a GPU status label.
- `clipper gpu` now reports Ollama availability and installed vision models.

### Changed

- The primary download is now the installer instead of a zip. The portable zip
  remains available for users who prefer it.
- The left control panel keeps Detect/Cancel pinned while settings scroll.
- Checkbox indicators and the AI/update bars match the dark native theme.
- AI scores blend model confidence with the audio/motion score so the results
  table reflects both signals.

### Known limitations

- The local vision pass is a review layer, not a trained kill detector. It
  reliably skips menus, loading screens, and black frames, but can still
  misjudge a quiet gameplay moment; keep clips in the results table under
  review before exporting.
- `qwen2.5vl:7b` needs roughly 6 GB of VRAM at an 8k context. Smaller GPUs can
  use `qwen2.5vl:3b` at lower accuracy.
- OpenCV motion scoring and audio RMS remain CPU work. NVENC accelerates only
  decode, the analysis proxy encode, re-encode, and the AI runtime.
- The installer is unsigned, so SmartScreen may warn on first run.

## [0.2.1] - 2026-11-24

### Fixed

- GPU is now **enabled by default in the native app and CLI when a real
  one-frame NVENC test passes**, instead of being off by default or trusting
  the encoder list.
- The NVENC capability probe used a 128×128 test frame, which NVIDIA rejects as
  below its minimum supported dimension. It now uses 256×144 and correctly
  reports `NVENC H.264 test encode: PASS` on an RTX 3080.
- Analysis progress now reports the actual proxy backend (`NVENC`,
  `NVENC + hardware decode`, or CPU fallback), and a requested GPU that falls
  back to CPU produces a visible warning.
- Added `clipper gpu` diagnostics with the NVENC test result, `nvidia-smi`
  summary, and a clear note that OpenCV motion scoring/audio RMS remain CPU
  work.

## [0.2.0] - 2026-11-24

### Added

- Native Qt desktop app (`clipper-desktop` / `Clipper.exe`) with:
  - native folder picker and drag-and-drop,
  - sensitivity/padding controls and advanced tuning,
  - GPU/NVENC toggle for proxy encode and optional re-encode,
  - CPU thread cap, proxy size/FPS controls, and a low-power mode,
  - in-app progress, previews, results table, cancel, and export.
- Native Windows portable build now ships `Clipper.exe` (windowed, no console)
  with Python, PySide6, FFmpeg, and FFprobe bundled.
- CLI hardware controls: `--threads`, `--proxy-width`, `--gpu`, `--low-power`,
  and `--encoder auto`.
- Analysis defaults to a balanced half-core thread cap instead of using every
  core; low-power mode lowers process priority and caps threads/FPS/proxy size.

### Changed

- `clipper` with no arguments now opens the native desktop app when PySide6 is
  installed. `clipper ui` remains available as the optional local web UI.
- Re-encode defaults to `auto` (NVENC when available, libx264 fallback).

## [0.1.1] - 2026-11-23

### Added

- Windows x64 portable build with Python 3.13, FFmpeg, FFprobe, the web UI,
  and launcher scripts bundled. Unzip and double-click `Clipper UI.cmd`; no
  Python or FFmpeg install required.
- Frozen-build FFmpeg discovery: the executable now looks in its own folder,
  `bin/`, and `ffmpeg/bin/` before falling back to `PATH`.
- Public landing page, demo video/GIF, social preview, three guides, and a
  done-for-you clip request flow.

## [0.1.0] - 2026-11-22

### Added

- Folder and single-file batching for `.mp4`, `.mkv`, `.mov`, and `.avi`.
- Audio spike detector: 16 kHz mono PCM, 50 ms RMS windows, 4-second rolling
  median baseline, robust z-score, absolute-loudness blend, and p99
  normalization.
- Visual activity detector: FFmpeg 320px / 4fps proxy, OpenCV frame differencing,
  90th-percentile change, and brightness-flash scoring.
- Hybrid fusion with configurable audio/motion weights, agreement bonus,
  adaptive percentile peak picking, minimum peak spacing, smart padding, and
  overlapping-window merging.
- CLI with `--input`, `--output`, `--dry-run`, `--pre`, `--post`,
  `--sensitivity`, `--reencode`, hardware encoders, JSON output, and recursive
  scanning.
- Lossless stream-copy export with automatic H.264/AAC fallback when the source
  container or codec is incompatible.
- Local FastAPI + Tailwind/Alpine web UI with folder browser, sliders, preview
  thumbnails, background jobs, progress, cancellation, and export controls.
- Dry-run preview thumbnails and timestamped JSON reports.
- Synthetic footage generator and a gated end-to-end test.
- Dockerfile, GitHub Actions CI, MIT license, README, and Reddit launch kit.

### Known limitations

- Stream-copy clips can start on the previous keyframe; use `--reencode` for
  frame-accurate edges.
- Detection is heuristic. It understands loud and fast-moving, not game context.
- PyPI publication of `clipper-gg` is pending; install the release wheel or the
  GitHub source until then.

[Unreleased]: https://github.com/hatermedia/clipper/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/hatermedia/clipper/releases/tag/v0.3.1
[0.3.0]: https://github.com/hatermedia/clipper/releases/tag/v0.3.0
[0.2.1]: https://github.com/hatermedia/clipper/releases/tag/v0.2.1
[0.2.0]: https://github.com/hatermedia/clipper/releases/tag/v0.2.0
[0.1.1]: https://github.com/hatermedia/clipper/releases/tag/v0.1.1
[0.1.0]: https://github.com/hatermedia/clipper/releases/tag/v0.1.0
