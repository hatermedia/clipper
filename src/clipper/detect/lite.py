from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from ..config import DetectionSettings
from ..ffmpeg import FFmpegBinaries
from ..models import ClipWindow
from .audio import ScoreTrack
from .hud import display_text, event_lines, read_hud
from .merge import merge_windows
from .signals import analyze_signals, tag_transcript, window_signal
from .story import HUD_KIND_ORDER, HUMOR_CUES, transcribe_audio

ProgressFn = Callable[[float, str], None]


def _report(progress: ProgressFn | None, fraction: float, message: str) -> None:
    if progress is not None:
        progress(max(0.0, min(1.0, fraction)), message)


def _unique_candidates(
    candidates: list[ClipWindow],
    lines: list,
    analysis,
    duration: float,
) -> list[ClipWindow]:
    windows = [
        ClipWindow(
            start=max(0.0, window.start),
            end=min(duration, window.end),
            peak=min(max(0.0, window.peak), duration),
            score=float(window.score),
        )
        for window in candidates
        if window.end > window.start
    ]

    # Spoken cues are cheap to inspect and do not require OCR.
    for line in lines:
        if not line.text:
            continue
        hot = HUMOR_CUES.search(line.text) or any(
            tag in line.tags for tag in ("LAUGH", "FAST", "PITCH", "SHOUT", "CHEER")
        )
        if hot:
            center = (line.start + line.end) / 2.0
            windows.append(
                ClipWindow(
                    start=max(0.0, center - 8.0),
                    end=min(duration, center + 8.0),
                    peak=min(max(0.0, center), duration),
                    score=0.74,
                )
            )

    # HUD banners are often quieter than the action peak. Scan the timeline in
    # blocks, but bound the number of blocks on long videos so a one-hour VOD
    # does not become an unbounded OCR job.
    hud_step = 15.0 if duration <= 180.0 else max(30.0, duration / 36.0)
    hud_windows: list[ClipWindow] = []
    hud_start = 0.0
    while hud_start < duration:
        hud_end = min(duration, hud_start + hud_step)
        hud_windows.append(
            ClipWindow(
                start=hud_start,
                end=hud_end,
                peak=(hud_start + hud_end) / 2.0,
                score=0.90,
            )
        )
        hud_start += hud_step

    # Pure laughter or a camera flick may not create a strong fused audio peak.
    step = 5.0
    start = 0.0
    while start < duration:
        end = min(duration, start + 8.0)
        signal = window_signal(analysis, start, end, lines)
        if signal.agreement():
            center = min(max(0.0, signal.peak_time), duration)
            windows.append(
                ClipWindow(
                    start=max(0.0, center - 8.0),
                    end=min(duration, center + 8.0),
                    peak=center,
                    score=0.78,
                )
            )
        start += step

    def pick_unique(items: list[ClipWindow], limit: int) -> list[ClipWindow]:
        ordered = sorted(items, key=lambda window: (window.score, window.start), reverse=True)
        picked: list[ClipWindow] = []
        for window in ordered:
            if any(
                window.start < other.end - 1.0 and window.end > other.start + 1.0
                for other in picked
            ):
                continue
            picked.append(window)
            if len(picked) >= limit:
                break
        return picked

    # Keep every bounded HUD block (including late-video events) and cap the
    # social/signal candidates separately.
    picked = pick_unique(hud_windows, len(hud_windows)) + pick_unique(windows, 8)
    picked.sort(key=lambda window: window.start)
    return picked


def lite_clip(
    video: Path,
    duration: float,
    settings: DetectionSettings,
    wav: Path | None,
    audio: ScoreTrack | None,
    visual: ScoreTrack | None,
    jerk: ScoreTrack | None,
    candidates: list[ClipWindow],
    bins: FFmpegBinaries,
    progress: ProgressFn | None = None,
) -> tuple[list[ClipWindow], list[str]]:
    warnings: list[str] = []
    lines: list = []

    def wait_for_game(stage: str) -> None:
        guard = settings.game_guard
        if guard is None:
            return
        game = guard()
        if not game:
            return
        while guard():
            if progress:
                progress(0.90, f"Lite paused · {game} is running")
            time.sleep(2.0)
        if progress:
            progress(0.90, f"Lite resumed · {stage}")

    wait_for_game("transcribing")

    _report(progress, 0.86, "Lite mode: transcribing audio")
    if wav is not None and wav.is_file():
        try:
            lines = transcribe_audio(wav, threads=settings.threads)
            lines = [line for line in lines if line.start < duration]
            if not lines:
                warnings.append("Lite: no speech found; using HUD and signal tags.")
        except Exception as exc:
            warnings.append(f"Lite transcription skipped: {exc}")
    else:
        warnings.append("Lite: no audio track; using HUD and motion only.")

    _report(progress, 0.89, "Lite mode: reading acoustic/motion signals")
    analysis = analyze_signals(wav, jerk, threads=settings.threads)
    tag_transcript(lines, analysis)
    if wav is not None and not analysis.acoustic.yamnet:
        warnings.append("Lite: YAMNet unavailable; laughter tags are off.")

    shortlist = _unique_candidates(candidates, lines, analysis, duration)
    clips: list[ClipWindow] = []
    for index, candidate in enumerate(shortlist, start=1):
        wait_for_game(f"reading HUD {index}")
        _report(
            progress,
            0.90 + 0.09 * (index - 1) / max(1, len(shortlist)),
            f"Lite mode: reading HUD {index}/{len(shortlist)}",
        )
        start = candidate.start
        end = candidate.end
        signal = window_signal(analysis, start, end, lines)

        reading = read_hud(video, start, end, bins)
        hud_kind = ""
        hud_hits = []
        if reading.available:
            for kind in HUD_KIND_ORDER:
                hits = event_lines(kind, reading.lines)
                if hits:
                    hud_kind = kind
                    hud_hits = hits
                    break

        if hud_hits:
            event_time = min(duration, max(0.0, max(hit.time for hit in hud_hits)))
            start = max(0.0, event_time - 6.0)
            end = min(duration, event_time + 6.0)
            reason = f"AI {hud_kind} (HUD): {display_text(hud_hits, 2 if hud_kind == 'round' else 1)}"
            clips.append(
                ClipWindow(
                    start=start,
                    end=end,
                    peak=event_time,
                    score=0.80,
                    reason=reason[:180],
                )
            )
            continue

        if signal.agreement():
            kind = "hype"
            center = signal.peak_time
            start = max(0.0, center - 8.0)
            end = min(duration, center + 8.0)
            if signal.quote:
                start = max(0.0, min(start, signal.quote_start - 4.0))
                end = min(duration, max(end, signal.quote_end + 5.0))
            score = min(0.90, 0.58 + 0.06 * len(signal.labels()))
            clips.append(
                ClipWindow(
                    start=start,
                    end=end,
                    peak=center,
                    score=score,
                    reason=f"AI {kind}: {signal.reason()}"[:180],
                )
            )

    clips = [
        clip
        for clip in merge_windows(clips, merge_gap=1.0, duration=duration)
        if clip.duration >= settings.min_clip
    ]
    clips.sort(key=lambda clip: clip.score, reverse=True)
    clips = clips[: settings.max_clips]
    clips.sort(key=lambda clip: clip.start)
    if not clips:
        warnings.append("Lite mode found no highlights.")
    _report(progress, 1.0, f"Found {len(clips)} clip(s)")
    return clips, warnings
