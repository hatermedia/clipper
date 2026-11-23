# Clipper — Go-to-Market & Monetization Brief

*23 Nov 2026. Repo state: 0 stars, 0 forks, 5 commits, v0.1.0; `clipper-gg` is not on PyPI. Targets are planning numbers, not forecasts.*

## Bottom line

Clipper should not fight Eklipse, Opus Clip, or StreamLadder on AI clipping or vertical social video. Its defensible wedge is narrower and real: **post-hoc triage of a local gameplay folder, any game, no upload, lossless cuts, one-time price.** That buyer is a ShadowPlay/OBS hoarder, not a streamer with a VOD pipeline.

The constraint is distribution and install friction, not features. A gamer will not install Python + FFmpeg to try a clip tool. Fix that before any launch.

**Sequence:** one-click Windows build + PyPI (week 1) → technical credibility on HN/r/Python/r/opensource (weeks 2–3) → $49 done-for-you Highlight Pack for first dollar + testimonials (week 4) → $29 one-time Pro and $199 Studio licenses (months 2–3). Skip hosted cloud for now.

## 1. Competitive map

| Product | Positioning / price | Gap for Clipper |
|---|---|---|
| [Medal.tv](https://medal.tv) | Free capture + auto-clipping for supported games; Premium sub (price not shown). | Capture-first social network; no folder batch, no lossless local pipeline. |
| [NVIDIA App](https://www.nvidia.com/en-us/software/nvidia-app/) / [Steam Recording](https://store.steampowered.com/gamerecording) / [OBS](https://obsproject.com/) | Free/bundled. NVIDIA auto-captures game-specific moments; Steam/OBS are capture + manual clip. | Capture-time, per-game, or manual; no post-hoc folder triage. |
| [Eklipse.gg](https://eklipse.gg) | Cloud AI stream highlights, 3,000+ games; free tier + paid Pro (price gated in app). Claims 1.5M creators. | Account/OAuth/upload, subscription, vertical social output. |
| [Sizzle.gg](https://sizzle.gg/subscription) | AI highlights from Twitch/YouTube/uploads; $0 / $4.99/mo. | Platform-linked cloud tool; not a local folder. |
| [StreamLadder](https://www.streamladder.com/pricing) | Vertical editor + ClipGPT; free 720p, then $15/$27/$39 per month. | Editor/publisher, not batch trimming; cloud. |
| [Opus Clip](https://www.opus.pro/pricing) / [Klap](https://klap.app/pricing) | General AI shorts; Opus $0/$15/$29/mo; Klap $14.50–$94.50/mo billed yearly. | Talking-head/general focus; cloud; not gaming folders. |
| [PeakClips](https://www.peakclips.tv) | Done-for-you Twitch clip automation; $49/$79/$129/mo. | Twitch clips only, subscription, no local files. |
| [Auto-Editor](https://auto-editor.com/) / [LosslessCut](https://github.com/mifi/lossless-cut) | Local auto-cut; free CLI + app from $29 one-time. LosslessCut free GPL, 46.3k stars, paid store builds. | General editing or manual cutting; no gaming audio+motion fusion or gaming UI. |
| [ClippingCulture](https://clippingculture.com/blog/how-much-does-a-clipping-campaign-cost) / [MarkStudios](https://www.markstudios.com/blog/clipping-campaign-cost-2026) | Managed campaigns from ~$15k (~$1.50/1k views); payouts $1–5/1k views. | Brand-scale campaigns; not a $50 job. |

**The gap:** nobody owns “40GB folder → 10 horizontal clips” for non-streamers. Cloud tools assume a connected platform, capture tools assume you clip live, editors assume you already know the timestamps. The $4.99–$39/mo subscription umbrella and $15k agencies leave room for a $29 one-time utility; Auto-Editor proves that model.

**Weaknesses:** heuristic detection misses semantic moments; no vertical crop or captions—features every consumer competitor markets. Sell the narrow job, not parity.

**Name:** “Clipper” is generic and bad for search. Always pair it with “gameplay highlight trimmer” or “Clipper GG.”

**Caution:** [Powder](https://powder.gg), a consumer clipping app, shut down after 7 years: “we can no longer sustain the app.” Free defaults cap willingness to pay; retention is brutal.

## 2. Monetization paths, ranked by speed to first dollar

| Path | Offer | Time to first $ | Unit economics | Scalability |
|---|---|---|---|---|
| Done-for-you pack | $19 / $49 / $99 per batch | 3–10 days | 40–45% after labor; ~$18–22 contribution/order | Low: 3–5 orders/week solo |
| Pro license | $29 one-time ($19 launch) | 2–4 weeks | $25.60 net via Gumroad; ~$15 after 15 min support | Medium: 100 units = $2.5k one-time |
| Presets / templates | $9–$15 pack | 2–4 weeks | ~100% margin, tiny volume | Low; better as a lead magnet |
| Sponsorship | $5/$15/$50 monthly tiers | 4–8 weeks | GitHub Sponsors 0% for individuals; $0–100/mo realistic | Low |
| Affiliate | 20–30% of $15–$39/mo tools | 2–4 weeks | $3–$12/customer/mo | Low until traffic exists |
| B2B / studio | $199–$499/yr, 3 seats | 30–90 days | 80–90% margin; invoices + support | High ACV, slow cycle |
| Content / SEO | Ads + email capture | 3–12 months | $3–$10 RPM or lead gen | Compounding, slow |
| Hosted / cloud | $9–$19/mo | 2–4 months | $2–$5 COGS/user/mo at 5 × 10GB runs | High, but conflicts with the wedge |

**By scalability:** hosted > Pro > B2B > content > affiliate > presets > service > sponsorship. **By speed:** service > Pro > presets > sponsorship > affiliate > B2B > hosted > content.

**MIT caveat:** anyone can fork the code. Paid value must be the signed installer with bundled FFmpeg, presets, auto-update, and support—not artificial code locks. The moat is distribution and trust.

**Cloud is a trap for now:** uploads contradict the promise, egress/storage/support cost real money, and incumbents charge $15–39/mo. Build only if 20+ users prepay.

## 3. Launch channels and self-promotion rules

| Channel | Account required | Reality (Nov 2026) | Angle |
|---|---|---|---|
| r/pcgaming (~4M) | Yes; AutoMod may gate new accounts | Limited: ≤10% of your Reddit-wide submissions from one source; participation expected. Native GIF + context, not a bare link. | “40GB of ShadowPlay → 10 clips” |
| r/Twitch (~2M) | Yes | Channel/clip promotion banned; tool posts are mod discretion. Modmail first; likely removal if it reads as an ad. | VOD cleanup |
| r/VideoEditing (~1.5M) | Yes | Self-promo and service ads routinely removed; weekly threads only. High rejection. | FFmpeg workflow in weekly thread |
| r/opensource (~250k) | Yes | Project showcases are normal; disclose affiliation, link repo + license, don’t sell. | Architecture + MIT |
| r/Python (~1.5M) | Yes | Allowed with rules: text post, “Showcase” flair, description + source link, no paywalled content. | Audio z-score + proxy-motion write-up |
| r/gaming (~40M) | Yes | Self-promo effectively banned. | Skip |
| Hacker News “Show HN” | Yes, free | Must be tryable now; no landing page, no signup wall, no upvote asks. | “Show HN: Clipper – local-first gameplay highlight trimmer (MIT)” |
| Product Hunt | Yes | Product page + visuals; one launch; modest reach without a following. | Before/after demo + free download |
| X | Yes | No gatekeeper; low reach at 0 followers. | Dev log + 15s demos |
| TikTok / Shorts | Yes | Native demo videos can reach cold; rules target links, not content. | “10 clips from 2h of gameplay” |
| YouTube | Yes | Tutorial/SEO; slow but compounding. | “Find highlights without watching the VOD” |

Reddit rules pages were not directly fetchable here. The r/pcgaming 10% rule and r/Python showcase rules come from published rule text; the rest reflect current community practice. Re-check the sidebar the day you post. All require an account; none require payment. Discord `#self-promo` channels in 5–10 game/streamer servers will likely outperform r/gaming.

## 4. 30-day execution plan

| Week | Focus | Ship | Cumulative KPI |
|---|---|---|---|
| 1 | Remove friction | PyPI release; Windows zip with embedded Python + FFmpeg + launcher; GitHub Pages landing + waitlist; 60s demo; comparison page | PyPI live; 10 installs; 10 waitlist; 2 conversations |
| 2 | Credibility | r/Python Showcase post; r/opensource post; r/pcgaming post; 1 technical write-up; 10 personal micro-creator offers | 30 installs; 15 stars; 25 waitlist; 4 conversations |
| 3 | Launch spike | Show HN Tue/Wed 9am ET; Product Hunt 48h later; 3 Shorts; X thread | 120 installs; 50 stars; 40 waitlist; 7 conversations |
| 4 | First dollar | Highlight Pack at $29 intro/$49 standard; Fiverr + Gumroad; waitlist email; 2 Discord posts | 200 installs; 75 stars; 60 waitlist; 10 conversations; 2 orders (~$58–98) |

**Measure:** PyPI downloads via pypistats (upper bound; includes mirrors/CI), GitHub release asset downloads, stars, waitlist signups, replies/DMs, paid orders. No telemetry.

**Realism:** at 0 stars, a good Show HN might get 20–100 upvotes and 100–400 visits; many get under 10. Reddit tool posts often die at 0–5 upvotes or are removed. If week 3 flops, do not add features; book 1:1 demos and sell 5 service orders.

## 5. The first-dollar offer

**Clipper Highlight Pack — $49 ($29 for the first five).** Send up to 2 hours of gameplay; get 10 lossless clips, timestamps, and preview thumbnails in 48 hours. One revision. Horizontal only.

It uses Clipper as the production tool, needs zero feature work, has fixed scope, and Fiverr supplies buyer intent a 0-star repo lacks. It also produces testimonials and before/after assets.

**Unit economics:** $49 direct via Gumroad nets $43.60; ~35 minutes of labor ($20 at $35/hr) + ~$1 transfer leaves ~$22 contribution. Fiverr nets $39.20 → ~$18. Ten orders/month is ~$180–220—not a business, but proof. Fiverr holds funds ~14 days; Gumroad pays on a schedule.

**Exact copy:**

> **Fiverr title:** I will turn your raw gameplay footage into 10 highlight clips
>
> **Hero:** 40GB of gameplay. 10 clips worth posting. In 48 hours.
>
> **Sub:** Send a folder link. I run a local FFmpeg pipeline, cut the loud and fast moments losslessly, and deliver 10 named clips plus timestamps. $49 flat. No subscription, no watermark.
>
> **Packages:** Basic $19 — 3 clips, 45 min of footage. Standard $49 — 10 clips, 2 hours. Premium $99 — 25 clips, 6 hours.
>
> **Requirements:** game; resolution/fps; total runtime; folder link; deadline; moments to include or avoid; confirmation you own the footage.
>
> **FAQ:** “What counts as a highlight?” Loud reactions + sudden motion; I review every cut. “What if it misses?” One free revision; send timestamps. “Do you keep my footage?” No—deleted 7 days after delivery. “Vertical/captions?” Not yet. “Refunds?” Full refund if I deliver no usable clips.

**Assets needed:** (1) Fiverr gig with 3 images—before/after folder, contact sheet of 10 clips, price card; (2) 60–90s screen recording of dry-run → export; (3) Gumroad product page and checkout; (4) Tally intake form; (5) delivery template with clip naming (`Game_YYYYMMDD_clip01.mp4`) and `clips.csv`; (6) deletion/revision policy; (7) testimonial request.

**Launch sequence:** publish Fiverr + Gumroad → 10 personalized DMs offering a free 3-clip sample → 2 Discord `#self-promo` posts → waitlist email. No mass DMs.

**Payments:** Gumroad setup is instant, 10% + $0.50, merchant of record; payout needs bank/PayPal + tax details. Paddle is 5% + 50¢ but requires approval. Fiverr: ~20% + ID verification. “First dollar earned” is not cash received; Fiverr clearance can take two weeks.

**Privacy caveat:** the service requires a folder link, so never claim “no uploads” for it. Say: “Processed on one local machine, not an AI SaaS; deleted after 7 days.”

---

**Confidence:** competitor prices were checked on the linked pages on 23 Nov 2026 unless marked gated/reported. Reddit rules are partially unverified; re-read them before posting.
