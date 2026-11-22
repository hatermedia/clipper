# Reddit launch kit

## Title options

1. **I built a local, open-source gameplay clipper that finds highlights by audio spikes + motion — no uploads, no ML models**
2. **Clipper: batch-trim 40GB of gameplay footage down to the good 30 seconds (MIT, local, FFmpeg)**
3. **I got tired of scrubbing ShadowPlay clips, so I made an offline highlight trimmer**

## Body

```markdown
I record a lot of gameplay and almost never edit it. Every "auto clipper" I tried was built around one game, one streaming platform, or a cloud pipeline that wanted my footage uploaded.

So I built **Clipper** — a small, local-first highlight trimmer.

**What it does**
- Scan a folder of `.mp4` / `.mkv` / `.mov` / `.avi` files.
- Score audio spikes (RMS vs. a rolling baseline) + visual motion (OpenCV frame deltas).
- Fuse the two, merge overlapping moments, and pad 8s before / 5s after by default.
- Export with FFmpeg stream copy (instant, lossless) or re-encode with libx264 / NVENC for frame-accurate cuts.
- Dry-run mode shows timestamps + preview frames before rendering anything.
- Local web UI: folder browser, sensitivity sliders, clip previews, batch progress.

**What it is not**
- Not a semantic AI editor. It does not know what a "boss fight" is. It knows loud + fast-moving.
- Not a vertical-caption generator (yet).
- Not a cloud service. No accounts, no telemetry, no uploads.

**Install**
```bash
pipx install git+https://github.com/hatermedia/clipper.git
# or
git clone https://github.com/hatermedia/clipper.git
cd clipper && python -m venv .venv && pip install -e .
```

You need FFmpeg on PATH. Windows: `winget install Gyan.FFmpeg`.

**Try it**
```bash
clipper --input "D:\Captures" --dry-run
clipper --input "D:\Captures" --output "D:\Highlights"
clipper ui
```

MIT licensed. GitHub: https://github.com/hatermedia/clipper

I'd especially love feedback on:
- Detection misses in specific games (quiet tactical vs. constant action).
- Whether stream-copy keyframe drift bothers you or if re-encode should be the default.
- Which game presets would actually be useful.
```

## Where to post

| Subreddit | Angle | Notes |
|---|---|---|
| r/pcgaming | "40GB of clips → highlights" | Check self-promo rules; use a screenshot/GIF, not just a link |
| r/VideoEditing | Batch trimming / FFmpeg workflow | Focus on the technical pipeline, not gaming |
| r/Twitch | Stream VOD cleanup | Frame it around VODs, not self-promo |
| r/opensource | MIT local-first tool | Show architecture + roadmap |
| r/Python | FastAPI + OpenCV + argparse | Technical write-up angle |
| r/gaming | General | Strict self-promo rules; consider skipping |

## Posting checklist

- [ ] Record a 15–30s screen capture of the UI (scan → detect → export).
- [ ] Include the screenshot from `docs/screenshot.png`.
- [ ] Mention the synthetic demo footage if you use it (don't imply it's real gameplay).
- [ ] Post one subreddit at a time and reply to comments.
- [ ] Don't cross-post the identical text to six subs in ten minutes.
- [ ] Add a clear "feedback wanted" question.
- [ ] Link the GitHub repo, not a landing page.
- [ ] Do not ask for stars; ask for detection edge cases.

## Short reply for comments

> It's heuristic on purpose: 16kHz RMS vs. a 4s rolling median for audio, 4fps 320px proxy + frame diff for motion, then a weighted fusion with adaptive percentile peak picking. No model download, no GPU required, and it runs on any game. The trade-off is it can't understand context — a loud menu sound can score. Sensitivity + audio/motion weights are the knobs.
