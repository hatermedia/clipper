# Delivery checklist

Use this for every paid highlight pack. The goal is a clean, predictable delivery
that produces a testimonial and a repeat buyer.

## 1. Before work starts

- [ ] Package and price confirmed in writing.
- [ ] Buyer confirmed they own or have permission to use the footage.
- [ ] Game, resolution/FPS, total runtime, and deadline confirmed.
- [ ] "What counts as a highlight" and "what to skip" written down.
- [ ] Output preference: lossless source container or H.264 MP4.
- [ ] Payment terms agreed (Fiverr order, Gumroad order, or invoice).
- [ ] Private intake method sent; no public links or personal data in an issue.

## 2. Ingest

- [ ] Download footage to a dedicated folder: `work/<order-id>/input/`.
- [ ] Verify file count and total runtime with `ffprobe`.
- [ ] Confirm audio exists. If not, plan visual-only detection.
- [ ] Note any known timestamps from the buyer.
- [ ] Keep originals untouched.

## 3. Detect

```powershell
clipper --input "work\<order-id>\input" --output "work\<order-id>\dryrun" --dry-run --sensitivity 0.55 --pre 6 --post 4
```

- [ ] Open `clipper-report-*.json` and the previews.
- [ ] Check that the top windows match the buyer's definition of a highlight.
- [ ] Tune per genre:
  - fast shooter: defaults / sensitivity 0.6
  - tactical: `--visual-weight 0.6 --audio-weight 0.4`
  - racing/sports: `--visual-weight 0.7 --audio-weight 0.3`
  - horror/story: `--sensitivity 0.35 --pre 10 --post 6`
- [ ] Remove obvious menu/loading/downtime windows.
- [ ] If a known timestamp is missed, add it manually to the edit list.

## 4. Export

```powershell
clipper --input "work\<order-id>\input" --output "work\<order-id>\clips" --pre 6 --post 4 --sensitivity 0.55
# For exact edges:
clipper --input "work\<order-id>\input" --output "work\<order-id>\clips" --reencode --encoder libx264 --crf 20
```

- [ ] Verify every exported clip plays and has audio.
- [ ] Check duration and start/end against `clips.csv`.
- [ ] Rename to the delivery convention:
  `game_YYYYMMDD_clip01_00m12s-00m18s.mp4`
- [ ] Keep a lossless version if the buyer asked for it; otherwise H.264 MP4.

## 5. Package

```text
clipper-<order-id>-<date>/
  clips/
    game_YYYYMMDD_clip01_....mp4
    ... (10 files)
  previews/
    clip01.jpg ... clip10.jpg
  clips.csv
  delivery-notes.txt
```

`clips.csv` columns: `id, file, start, end, score, note`.

`delivery-notes.txt`:

```text
Hi <name>,

Your pack is ready.

- 10 clips in /clips
- Preview frames in /previews
- Timestamps and scores in clips.csv

I kept these moments: <one-line summary>.
I skipped these on purpose: <menus/downtime/etc.>.

One revision round is included. Reply with the clip number and the timestamp you
want changed.

Footage will be deleted 7 days after delivery.
```

## 6. Deliver

- [ ] Upload the folder to the agreed delivery method.
- [ ] Send the delivery message.
- [ ] Mark the order delivered only after the link is accessible.
- [ ] Ask one question: "Which clip is closest to what you wanted?"
- [ ] After the revision window, ask for a testimonial if the buyer is happy.

## 7. Clean up

- [ ] Delete the buyer's footage 7 days after delivery.
- [ ] Keep only the delivery notes and clips.csv for accounting (no footage).
- [ ] Confirm deletion to the buyer.
- [ ] Record the order in a simple ledger: date, package, revenue, labor time.

## Quality bar

- No black frames at the start.
- No clipped audio.
- No accidental menu/loading screens.
- No vertical/caption promises.
- No music you cannot license.
- No watermarks.
- No "AI magic" claims. It is a heuristic first pass plus human review.
