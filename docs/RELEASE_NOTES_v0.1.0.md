# Clipper v0.1.0

First public build of Clipper - a local-first gaming highlight trimmer.

Clipper scans a folder of gameplay footage, scores audio spikes and visual
motion, merges overlapping moments, and cuts clips with FFmpeg. No uploads, no
accounts, no model downloads.

## What's included

- Batch `.mp4` / `.mkv` / `.mov` / `.avi` scanning, optionally recursive.
- Hybrid audio + motion detection with configurable weights and sensitivity.
- Smart pre/post padding (8s / 5s defaults) and overlap merging.
- Instant lossless stream copy; optional frame-accurate `libx264`, `h264_nvenc`,
  `hevc_nvenc`, or `libx265` re-encode.
- Dry-run mode with timestamps, preview thumbnails, and JSON reports.
- Local web UI: folder browser, sliders, clip previews, batch export progress,
  cancel.
- FastAPI API and a single-file Tailwind/Alpine frontend. No Node build step.
- MIT license.

## Install

Requires Python 3.10+ and FFmpeg on `PATH`.

```powershell
winget install Gyan.FFmpeg
```

Install the attached wheel:

```bash
python -m pip install https://github.com/hatermedia/clipper/releases/download/v0.1.0/clipper_gg-0.1.0-py3-none-any.whl
```

Or install from GitHub with pipx:

```bash
pipx install git+https://github.com/hatermedia/clipper.git
```

## Try it

```bash
clipper --input "D:\Captures" --dry-run
clipper --input "D:\Captures" --output "D:\Highlights"
clipper ui
```

## Known limitations

- Stream-copy clips start at the nearest keyframe, so they can include a little
  extra run-up. Use `--reencode` for exact edges.
- The detector is heuristic: loud + fast-moving, not semantic game understanding.
- PyPI publication of `clipper-gg` is pending. Use the attached wheel or the
  GitHub source until then.
- Primary testing is on Windows; CI runs the unit and API suite on Linux and the
  synthetic end-to-end pipeline on Ubuntu.

## Feedback

Please open an issue with your OS, FFmpeg version, command, footage details, and
the timestamps you expected. Detection misses in specific games are especially
useful.
