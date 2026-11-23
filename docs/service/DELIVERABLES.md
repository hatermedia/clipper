# What you get

A clean delivery folder, not a zip of random timestamps.

```text
clipper-<order>-<date>/
  clips/
    gameplay_20261123_clip01_00m12s-00m18s.mp4
    gameplay_20261123_clip02_00m49s-00m55s.mp4
    ... (10 clips on Warm-up)
  previews/
    clip01.jpg
    clip02.jpg
    ...
  clips.csv
  delivery-notes.txt
```

## Clips

- 16:9, source resolution and frame rate where possible.
- Lossless stream copy by default; clean H.264 MP4 when exact edges or container
  compatibility matter.
- No watermark.
- Named with game, date, clip number, and timestamps.

## `clips.csv`

```csv
id,file,start,end,score,note
1,gameplay_20261123_clip01_00m12s-00m18s.mp4,00:12.500,00:18.500,0.93,audio + motion
2,gameplay_20261123_clip02_00m49s-00m55s.mp4,00:49.000,00:55.000,0.88,audio spike
```

## `previews/`

One JPG per clip at the detected peak, so you can scan the pack before opening
the videos.

## `delivery-notes.txt`

A short note: what was kept, what was skipped on purpose, revision instructions,
and the deletion date.

## What is not included

- Vertical 9:16 crops
- Burned-in captions
- Thumbnails, titles, descriptions, or publishing
- Music licensing
- Footage you do not own or have permission to use

## Revision

Warm-up includes one revision round; Session and Grind include two. Send the clip
number and the timestamp you want changed. Revisions stay within the original
scope and footage.
