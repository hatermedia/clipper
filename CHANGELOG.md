# Changelog

All notable changes to Clipper are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/hatermedia/clipper/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/hatermedia/clipper/releases/tag/v0.1.1
[0.1.0]: https://github.com/hatermedia/clipper/releases/tag/v0.1.0
