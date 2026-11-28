# Clipper 0.9 workflow

Clipper 0.9 turns the detector into a complete local clipping workflow. This
page documents the features in the 0.9 development work. They are not part of
the 0.8.4 installer yet.

Everything here is local. The library, queue, notes, and evidence are JSON or
text on this PC. Footage is never uploaded.

## Clip library

Every finished scan is saved to:

```text
%LOCALAPPDATA%\Clipper\library\library.json
```

Poster frames live next to it in `library\previews`. The library stores:

- Source paths, clip ranges, scores, and reasons
- Keep or reject decisions
- Notes and tags
- Director evidence
- Export history

Open **Library** in the title bar to reopen a scan, delete history, or review an
older result. A rescan of the same source inherits keep, note, tag, and export
history for clips whose start and end still match. If the director changes the
cut boundaries, that clip gets a new identity and starts clean.

The library is versioned JSON and is written atomically. A corrupt file is
backed up next to the original instead of being overwritten silently.

## Creator export presets

The export panel now has a **Format** picker and a **Name** template.

| Preset | Output | Codec | Reframe |
| --- | --- | --- | --- |
| Lossless cut | Original size and container | Stream copy | No |
| YouTube Shorts | 1080 x 1920 | H.264 | Auto |
| TikTok | 1080 x 1920 | H.264 | Auto |
| Instagram Reels | 1080 x 1920 | H.264 | Auto |
| Square | 1080 x 1080 | H.264 | Auto |
| Landscape 1080p | 1920 x 1080 | H.264 | No |
| Shorts HEVC | 1080 x 1920 | HEVC | Auto |
| Frame-accurate H.264 | Source size | H.264 | No |

NVENC is used when the installed FFmpeg build and driver can actually encode.
Otherwise Clipper falls back to libx264 or libx265.

The filename template supports:

```text
{source} {index:02d} {start} {end} {duration} {score} {peak}
{preset} {game} {date}
```

The default is:

```text
{source}_clip_{index:02d}_{start}-{end}
```

Creator presets add their own suffix, such as `_shorts` or `_square`.

Batch export already works through **Export all** and **Export selected**. Each
row's checkbox is the keep/reject decision and the export selection.

## Automatic vertical reframe

Vertical and square presets crop the source instead of stretching it. Clipper
samples the clip, follows the strongest motion, smooths the crop path, and sends
the result to FFmpeg as tracked crop commands.

**Reframe** offers:

- **Auto (action)**: follow the motion centroid. Best for gameplay.
- **Facecam**: follow the largest stable face. Falls back to action tracking
  when no face is found.
- **Center**: fixed center crop. Fastest and most predictable.

Reframe planning is best-effort. Fast cuts, full-screen effects, dark scenes,
and unusual HUD layouts can confuse motion tracking. Review vertical exports
before posting. A center crop is used if tracking cannot produce a usable path.

## Why this clip?

The area below the highlight table has two tabs:

- **Preview**: the existing inline player
- **Why this clip?**: the evidence behind the selected row

The evidence panel shows:

- Director summary and concrete proof
- Whisper transcript around the clip, with signal tags
- HUD lines that verified the event
- Audio ears tone, laughter, and score
- Audio and motion signal labels
- Windows the director reviewed, with scores
- Final edit confirmation
- Previous exports
- Your notes and tags

Notes and tags are edited in the same tab and saved to the library when the
field loses focus.

## Watch folders and scan queue

Open **Queue** in the title bar to manage background work.

- **Add folder** starts watching a folder. Existing files are marked as seen,
  so adding a large archive does not enqueue years of old footage. Enabling
  **Subfolders** baselines the existing subfolder files the same way.
- New or changed recordings are queued after a 15 second settle period.
- Exports written inside a watched folder are ignored, so Clipper does not
  scan its own output.
- **Only when idle** waits for two minutes without keyboard or mouse input.
- Game Guard prevents a queued scan from starting while a known game is running.
- **Pause queue** stops new jobs. An active job finishes.
- **Scan current now** enqueues the path in the main footage box.
- **Retry** requeues a failed job. **Clear finished** removes completed rows.
- A running job shows progress and an estimated time remaining.

Queue state is stored in:

```text
%LOCALAPPDATA%\Clipper\workflow.json
```

If Clipper crashes or quits while a scan is running, the job is requeued on the
next start. A job that stops three times is marked failed instead of looping
forever.

## CLI

The same presets are available from the command line:

```powershell
clipper --input .\footage --export-preset shorts --reframe auto
clipper --input .\footage --export-preset square --name-template "{game}_{index:02d}"
clipper --input .\clip.mp4 --format shorts_hevc --reframe facecam
```

`--reframe` accepts `auto`, `action`, `facecam`, `center`, or `none`.
`--name-template` accepts the same tokens as the desktop app.

## Privacy and storage

- The library stores paths and text, not copies of footage.
- Preview JPGs are stored in `%LOCALAPPDATA%\Clipper\library\previews`.
- Notes, tags, and queue state stay in `%LOCALAPPDATA%\Clipper`.
- Deleting a scan removes its library record and does not touch the source video.
- Export history contains output paths and preset names only.

See [VALIDATION_0.9.md](VALIDATION_0.9.md) for the checks run so far and the
gaps that still need real-footage testing.

## Not in this release

These are intentionally not part of 0.9:

- Burned-in captions or word highlighting
- Target file size or two-pass bitrate mode
- HUD-region or scoreboard-aware reframing
- Manual start/end trimming in the table
- Code signing for the installer
