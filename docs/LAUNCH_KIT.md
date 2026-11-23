# Launch kit — Clipper v0.1.1

Everything is built. This file is the 20-minute execution path once you are
logged in to the relevant accounts.

## Assets

- 16:9 demo (19.5s, 630 KB): `docs/media/demo.mp4`
- 9:16 demo (7.5s, 1080×1920): `docs/media/demo-vertical.mp4`
- GIF (3.7 MB): `docs/media/demo.gif`
- Social preview: `docs/og.png`
- Fiverr/Gumroad images: `docs/service/assets/`

## Links

- Site: https://hatermedia.github.io/clipper/
- Repo: https://github.com/hatermedia/clipper
- Release: https://github.com/hatermedia/clipper/releases/tag/v0.1.1
- Portable Windows: [clipper-0.1.1-windows-x64-portable.zip](https://github.com/hatermedia/clipper/releases/download/v0.1.1/clipper-0.1.1-windows-x64-portable.zip)
- Service page: https://hatermedia.github.io/clipper/service/
- Fiverr copy: `docs/service/FIVERR_GIG.md`
- Gumroad copy: `docs/service/GUMROAD_PRODUCT.md`
- Outreach: `docs/service/OUTREACH.md`
- Research: `docs/research/MARKET.md`, `docs/research/CONTENT_PLAN.md`

## The 20-minute path (no new product work)

1. **Log in to Fiverr.** Create a gig from `FIVERR_GIG.md`. Upload:
   - `docs/service/assets/fiverr-hero.png`
   - `docs/service/assets/fiverr-process.png`
   - `docs/service/assets/deliverables.jpg`
   Set $29 intro for the first five orders, then $49.
2. **Log in to Gumroad.** Create the product from `GUMROAD_PRODUCT.md`. Use
   `fiverr-hero.png` or `docs/og.png` as the cover. Price $29 / $49.
3. **Send 10 personalized contacts** from `OUTREACH.md`. One at a time. Offer 3
   free clips. No mass DMs.
4. **Post one technical launch** on a channel where you have an account:
   - Hacker News Show HN (GitHub URL, author comment below)
   - r/opensource (text post, disclose authorship)
   - r/Python (Showcase flair, technical angle)
5. **Log the results.** Stars, release downloads, inbound issues, replies,
   orders. Do not invent metrics.

## Show HN

**Title:** `Show HN: Clipper – Find gameplay highlights locally with FFmpeg`

**URL:** `https://github.com/hatermedia/clipper`

**First comment:**

```text
Author here. I record gameplay and rarely edit it, so I built a local tool that
scans a folder and cuts the loud, fast-moving moments.

Audio is RMS against a 4s rolling median; motion comes from a 320px/4fps OpenCV
proxy; scores are fused and overlapping windows merged. Default export is FFmpeg
stream copy, with optional re-encode. Python 3.10+, FFmpeg, MIT. No uploads,
models, telemetry, or account.

It is heuristic: it does not understand kills, objectives, or speech, and stream
copy can start on an earlier keyframe. Captions and vertical crop are not
included.

There is a Windows portable zip with Python/FFmpeg bundled, because install
friction was the obvious problem:
https://github.com/hatermedia/clipper/releases/tag/v0.1.1

`clipper --input <folder> --dry-run` shows timestamps and previews first. Demo
footage is synthetic and labeled.

Feedback wanted: detection misses (game + timestamp), install friction, keyframe
drift. No benchmark claims yet.
```

## r/opensource

**Title:** Clipper: a local-first gameplay highlight trimmer (MIT, Python + FFmpeg)

```text
I built Clipper because I had a ShadowPlay folder and no interest in scrubbing it.
It scans local gameplay files, scores audio spikes and visual motion, merges
overlapping moments, and exports with FFmpeg. No uploads, accounts, models, or
telemetry.

It is not a semantic editor: quiet tactical plays can be missed, loud menus can
score, and stream copy can include pre-roll. Captions and vertical reframing are
not included.

There is a Windows portable zip with Python and FFmpeg bundled, plus a source
install for macOS/Linux:
https://github.com/hatermedia/clipper/releases/tag/v0.1.1

`clipper --input ... --dry-run` shows cuts first. MIT.

I am the author, here for feedback on detection misses (game + timestamp) and CLI
vs. web UI. Mods, please remove if this is not appropriate.
```

## r/Python (Showcase flair)

**Title:** Clipper: audio RMS + OpenCV motion for local gameplay highlight detection

```text
I wanted a small, dependency-light example of fusing two cheap signals into a
useful edit decision list:

- 16kHz mono PCM → 50ms RMS → 4s rolling median baseline → robust z-score
- 320px/4fps FFmpeg proxy → OpenCV frame diff + p90 change + brightness flash
- resample both to 0.25s, weighted fusion, adaptive percentile peak picking,
  merge overlapping windows, pad, export with stream copy or re-encode

No ML model, no cloud, no telemetry. CLI + FastAPI local UI. MIT.

Portable Windows build (Python/FFmpeg bundled):
https://github.com/hatermedia/clipper/releases/tag/v0.1.1

Source and architecture: https://github.com/hatermedia/clipper

Happy to answer questions about the detection math or the packaging. Feedback on
false positives/negatives is more useful than stars.
```

## X / thread

1. `40GB of gameplay. I am not watching any of it.`
   `Clipper scans the folder, finds loud + fast moments, cuts them locally.`
   `[demo GIF]`
2. `Audio: RMS vs. a 4s rolling median.`
   `Motion: 320px/4fps OpenCV proxy.`
   `Fusion: weighted score + adaptive peaks + overlap merging.`
   `No model. No upload.`
3. `Windows portable zip: Python + FFmpeg bundled. Unzip, double-click, pick a folder.`
   `MIT. Repo + demo: https://hatermedia.github.io/clipper/`

## LinkedIn

```text
Most "AI clippers" upload your footage. I built the opposite: a local-first tool
that scans a gameplay folder, finds audio spikes and visual motion, and cuts the
shortlist with FFmpeg.

The interesting engineering was not the model. It was the packaging: a Windows
portable build with Python and FFmpeg bundled, so a gamer can unzip and run
instead of installing a toolchain.

Open source, MIT. Demo: https://hatermedia.github.io/clipper/
```

## TikTok / Shorts hooks

1. "40GB of clips. I'm not watching any of it."
2. "This is what a gunfight looks like to a waveform."
3. "No upload. No account. No model. Just FFmpeg."
4. "ShadowPlay saved the moment. It didn't cut it."
5. "Three hours of VOD. About forty seconds worth clipping."

Use the demo GIF/MP4 or record a real rights-cleared session. Label synthetic
footage.

## Channel rules

- r/pcgaming: ≤10% of your Reddit-wide submissions from one source; participate
  first. Native GIF + context, not a bare link.
- r/Twitch: clip/channel promotion is restricted; ask modmail before posting.
- r/VideoEditing: self-promo is often removed; use weekly threads.
- r/gaming: self-promo effectively banned; skip.
- r/opensource: disclose authorship, link repo + license, don't sell.
- r/Python: text post, Showcase flair, source link, no paywall.
- HN: must be tryable now; no landing-page-only post, no upvote asks.
- Product Hunt: one launch, real product page, no fake reviews.
- X/TikTok/YouTube: disclose synthetic footage; no fake engagement.

## Metrics to log weekly

- GitHub stars, forks, watchers
- Release asset downloads (portable, wheel, sdist)
- GitHub traffic views/uniques/referrers (14-day retention; export every Monday)
- Inbound issues and substantive replies
- Service requests and paid orders
- Which channel produced both referrers and issues

## What not to do

- No bought stars, downloads, reviews, or upvotes.
- No fake testimonials or user counts.
- No identical posts across ten subreddits/Discords.
- No mass DMs or scraped email lists.
- No "10x faster" claims without a benchmark.
- No promising views or monetization.
- No claiming "no uploads" for the done-for-you service; say "processed locally,
  deleted after 7 days."

## If the launch flops

Do not add features. Book 1:1 demos, send 10 more personalized 3-clip offers, and
publish one technical write-up. A launch is a distribution test, not a verdict.
