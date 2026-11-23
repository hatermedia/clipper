# Clipper Content & SEO Plan

Status: 23 Nov 2026. Baseline: 0 stars, 0 forks, 0 issues, 3 release downloads. No analytics account. Hypotheses, not a traffic or revenue forecast.

Publish on GitHub Pages at `/guides/<slug>.html`; syndicate with canonical URLs. Check autocomplete and page 1 first; skip queries owned by large brands. Start with long-tail problems where results are forums or thin vendor pages.

## 1. Ten search-led pages

**1. ShadowPlay batch trim**
- **Keyword / intent:** `batch trim shadowplay clips` — how-to.
- **Title:** Batch Trim ShadowPlay Clips Without Uploading
- **Meta:** Batch-trim ShadowPlay clips with local audio + motion detection, preview cuts, and lossless FFmpeg export. MIT.
- **Outline:** Capture vs. trim; install Python/FFmpeg; dry-run timestamps; stream-copy export; sensitivity.
- **Internal CTA:** Dry-run your folder; report a miss with game + timestamp.

**2. Automatic highlight finding**
- **Keyword / intent:** `find highlights in gameplay footage automatically` — informational.
- **Title:** Find Gameplay Highlights Automatically (No AI Model)
- **Meta:** Find loud reactions and sudden motion in gameplay footage, preview the moments, and cut clips locally.
- **Outline:** Why scrubbing fails; audio RMS vs. 4s median; 320px/4fps motion proxy; fusion + adaptive peaks; failure cases.
- **Internal CTA:** Try the demo; compare dry-run cuts to your timestamps.

**3. Lossless cuts**
- **Keyword / intent:** `trim gameplay video without re-encoding` — how-to.
- **Title:** Trim Gameplay Clips Without Re-Encoding
- **Meta:** How FFmpeg stream copy cuts gameplay without re-encoding, why keyframes shift the start, and when to re-encode.
- **Outline:** `-c copy`; keyframe boundary; command; default trade-off; `--reencode`; HDR note.
- **Internal CTA:** Export one clip both ways and compare.

**4. Capture vs. detection**
- **Keyword / intent:** `shadowplay vs obs replay buffer` — comparison.
- **Title:** ShadowPlay vs OBS Replay Buffer vs Clipper
- **Meta:** ShadowPlay, OBS Replay Buffer, and Clipper solve different parts of clipping. An honest comparison.
- **Outline:** Capture vs. detection; ShadowPlay is NVIDIA-only; OBS is manual but universal; Clipper post-processes files; no winner.
- **Internal CTA:** Have footage? Use Clipper. Still recording? Use OBS or ShadowPlay.

**5. Opus alternative**
- **Keyword / intent:** `free local opus clip alternative for gaming` — commercial.
- **Title:** A Free, Local Opus Clip Alternative for Gameplay
- **Meta:** Compare talking-video AI clipping with local audio + motion detection for gameplay. No uploads, no credits.
- **Outline:** Opus targets speech and often uploads; gameplay needs loud + motion, not transcripts; no captions/vertical crop.
- **Internal CTA:** Use Clipper for selects; finish in your editor.

**6. ShadowPlay folder**
- **Keyword / intent:** `where does shadowplay save highlights` — informational.
- **Title:** Where ShadowPlay Saves Highlights
- **Meta:** Find where NVIDIA ShadowPlay saves highlights, then batch-scan that folder and trim the good moments locally.
- **Outline:** Find the capture folder in NVIDIA settings (path varies); common `Videos/Captures`; `--recursive`; export.
- **Internal CTA:** Dry-run the folder before moving files.

**7. Twitch VOD**
- **Keyword / intent:** `trim twitch vod locally` — how-to.
- **Title:** Trim Twitch VOD Highlights Locally
- **Meta:** Trim highlights from your own Twitch VOD on your machine. Scan it, preview cuts, and export with FFmpeg.
- **Outline:** Only your own VOD or permission; TwitchDownloader/yt-dlp; no built-in downloader; scan; preview; export.
- **Internal CTA:** Dry-run your VOD; report a missed timestamp.

**8. Steam Deck**
- **Keyword / intent:** `trim steam deck gameplay recording` — how-to.
- **Title:** How to Trim Steam Deck Gameplay Recordings
- **Meta:** Turn Steam Deck recordings into short clips in Desktop Mode or on a PC. Local Python + FFmpeg.
- **Outline:** Export from Steam Game Recording; copy to PC or Desktop Mode; check `python3` + FFmpeg; venv + CLI; UI may be heavy.
- **Internal CTA:** Report Deck-specific install issues.

**9. Large folder triage**
- **Keyword / intent:** `organize large gameplay clip folder` — problem-aware.
- **Title:** How to Triage 100GB of Gameplay Clips
- **Meta:** Triage a huge gameplay folder with dry-run reports, preview frames, scores, and batch export instead of watching everything.
- **Outline:** Inventory by folder/date/size; dry run writes JSON + previews; keep/delete by score; keep originals; not a library manager.
- **Internal CTA:** Export only top candidates.

**10. Open-source detector**
- **Keyword / intent:** `open source gameplay highlight detector` — commercial.
- **Title:** Open-Source Gameplay Highlight Detection
- **Meta:** Clipper is an MIT, local-first gameplay highlight detector. Audio + motion, FFmpeg export, no model download.
- **Outline:** What it detects/does not; supported containers; install; shooter vs. racing tuning; roadmap: presets, vertical, VOD import.
- **Internal CTA:** Test one genre; report misses.

## 2. 30-day social/content calendar

Each channel needs an account; create early, participate first. Spend 15 min/day answering threads without links. Logins marked.

| Day | Channel / login | Hook | Format | CTA |
|---|---|---|---|---|
| 1 | Hacker News (account; no vote asks) | "I built a local tool that finds the loud parts of gameplay." | Show HN + author comment | Dry run; report misses |
| 2 | r/opensource (account; rules/flair) | "MIT local clipper — here is what it does not do." | Text + screenshot | Critique detection |
| 4 | X (account) | "40GB folder → 4 clips, one command." | 30s recording + thread | Repo link |
| 6 | dev.to (account) | "How I detect highlights without an ML model." | 900-word technical post | Canonical repo link |
| 8 | YouTube (channel, login) | "46s demo, scanned and cut." | 60–90s demo; label synthetic | Install link |
| 10 | TikTok/Shorts (account) | "Your highlight reel is in the audio spikes." | 15s vertical capture | Repo in bio |
| 12 | LinkedIn (profile login) | "Local-first: Python + FFmpeg, no telemetry." | Short post + screenshot | Ask for feedback |
| 15 | r/VideoEditing (account; promo rules) | "Stream copy vs re-encode for gameplay cuts." | Explainer; link if asked | Ask for edge cases |
| 18 | Hashnode (account) | "What a 320px proxy reveals about pacing." | Cross-post, canonical | Repo link |
| 21 | r/SteamDeck (account; rules) | "Trimming Deck recordings in Desktop Mode." | Walkthrough; one option | Share Deck issues |
| 24 | YouTube Shorts (channel) | "No upload. No account. No model." | 20s vertical demo | Pinned repo link |
| 28 | X (account) | "Three detection misses, and what changed." | Changelog thread | Open an issue |

Day 30: review; don't compensate with extra posts.

## 3. Short-form hooks (first 3 seconds)

1. **"40GB of clips. I'm not watching any of it."** — folder size → one dry run.
2. **"This is what a gunfight looks like to a waveform."** — spike synced to the detected clip.
3. **"No upload. No account. No model. Just FFmpeg."** — airplane mode on, then run.
4. **"ShadowPlay saved the moment. It didn't cut it."** — folder → preview thumbnails.
5. **"Three hours of VOD. About forty seconds worth clipping."** — timeline zooms to peaks.

Use synthetic or rights-cleared footage, and label synthetic footage. Do not imply a real match if it is generated.

## 4. Launch drafts

### Show HN

**Title:** Show HN: Clipper – Find gameplay highlights locally with FFmpeg

Submit the GitHub URL (not a landing page), then add this as the first comment:

> Author here. I record gameplay and rarely edit it, so I built a local tool that scans a folder and cuts loud, fast-moving moments.
>
> Audio is RMS against a 4s rolling median; motion comes from a 320px/4fps OpenCV proxy; scores fuse and overlapping windows merge. Default export is FFmpeg stream copy, with optional re-encode. Python 3.10+, FFmpeg, MIT. No uploads, models, telemetry, or accounts.
>
> It is heuristic: it does not understand kills, objectives, or speech, and stream copy can start on an earlier keyframe. Captions and vertical crop are not included.
>
> `clipper --input <folder> --dry-run` shows timestamps and previews first. The bundled demo clip is synthetic.
>
> Feedback wanted: detection misses (game + timestamp), install friction, keyframe drift. No benchmark claims yet.

### r/opensource

**Title:** Clipper: a local-first gameplay highlight trimmer (MIT, Python + FFmpeg)

> I built Clipper because I had a ShadowPlay folder and no interest in scrubbing it. It scans local gameplay files, scores audio spikes and visual motion, merges overlapping moments, and exports with FFmpeg. No uploads, accounts, models, or telemetry.
>
> It is not a semantic editor: quiet tactical plays can be missed, loud menus can score, and stream copy can include pre-roll. Captions and vertical reframing are not included.
>
> Install: `pipx install git+https://github.com/hatermedia/clipper.git`; FFmpeg required. `clipper --input ... --dry-run` shows cuts first. MIT.
>
> I am the author, here for feedback on detection misses (game + timestamp) and CLI vs. web UI. Mods, please remove if this is not appropriate.

Follow the subreddit rules and flair requirements: https://www.reddit.com/r/opensource/about/rules/. Disclose authorship every time: https://www.reddit.com/wiki/selfpromotion.

## 5. Measurement without an analytics account

Baseline (23 Nov 2026): 0 stars, 0 forks, 0 issues, 3 release-asset downloads (2 wheel, 1 sdist).

| Metric | Source | Cadence |
|---|---|---|
| Views, uniques, clones, referrers, popular paths | Insights → Traffic; `gh api repos/hatermedia/clipper/traffic/views` (push access) | Weekly; traffic retains only 14 days, so export every Monday |
| Release downloads | Releases page or `/releases` API; downloads ≠ installs | Weekly |
| Stars, forks, watchers | Repo API | Weekly, secondary |
| Inbound issues | GitHub Issues; label `install`, `detection`, `docs`; add "Where did you find Clipper?" to the issue template | Weekly |
| PyPI installs | pypistats.org, once `clipper-gg` is published | Monthly |

At day 30, keep the two channels that produced both referrers and substantive issues; drop the rest. A referrer with no issues is awareness, not traction. Do not infer installs from stars.

## 6. What not to do

- **No vote manipulation.** Do not ask friends to upvote or use pods. HN bans it: https://news.ycombinator.com/newsfaq.html. Reddit's content policy and X's manipulation rules also apply: https://www.redditinc.com/policies/content-policy, https://help.x.com/en/rules-and-policies/platform-manipulation.
- **No fake reviews, testimonials, benchmarks, or user counts.** Do not claim "10x faster" or "thousands of users." State that the demo is synthetic.
- **No astroturfing or sockpuppets.** Disclose that you are the author in every post and comment.
- **No spam or copy-paste promotion.** Do not post identical text to ten subreddits, Discords, or YouTube comments; do not DM creators. YouTube spam policy: https://support.google.com/youtube/answer/2801973.
- **No bought stars or downloads.** GitHub's acceptable-use policy prohibits fake engagement: https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies.
- **No mass AI content or scraped gameplay.** dev.to requires substantial, on-topic posts: https://dev.to/terms. TikTok prohibits fake engagement and spam: https://www.tiktok.com/community-guidelines. LinkedIn prohibits unwanted promotional spam: https://www.linkedin.com/legal/professional-community-policies.
- **No virality, traffic, or revenue promises.** Report what happened, including misses and bugs.

Rule sources: https://news.ycombinator.com/showhn.html and https://news.ycombinator.com/newsguidelines.html.
