from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .config import (
    VIDEO_EXTENSIONS,
    Cancelled,
    ClipperError,
    DetectionSettings,
    FFmpegBinaries,
    configure_cpu_limits,
    find_ffmpeg,
)
from .detect.audio import ScoreTrack, analyze_wav
from .detect.merge import fuse_tracks, pick_peaks, resample_track
from .detect.visual import analyze_visual
from .ffmpeg import (
    FFmpegError,
    extract_audio,
    last_proxy_backend,
    make_proxy,
    make_thumbnail,
    probe_media,
    render_clip,
)
from .models import AnalysisSummary, ClipWindow, FileAnalysis, MediaInfo

ProgressFn = Callable[[float, str], None]


@dataclass
class ExportResult:
    outputs: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    reencoded: list[Path] = field(default_factory=list)
    clips_total: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "outputs": [str(path) for path in self.outputs],
            "errors": list(self.errors),
            "reencoded": [str(path) for path in self.reencoded],
            "clips_total": self.clips_total,
        }


def _report(progress: ProgressFn | None, fraction: float, message: str) -> None:
    if progress is not None:
        progress(max(0.0, min(1.0, fraction)), message)


def scan_inputs(target: str | Path, recursive: bool = False, exclude: Path | None = None) -> list[Path]:
    root = Path(target).expanduser().resolve()
    if root.is_file():
        if root.suffix.lower() not in VIDEO_EXTENSIONS:
            raise ClipperError(f"Unsupported video extension: {root.suffix}")
        return [root]
    if not root.is_dir():
        raise ClipperError(f"Input folder does not exist: {root}")

    iterator = root.rglob("*") if recursive else root.iterdir()
    excluded = exclude.resolve() if exclude is not None else None
    files: list[Path] = []
    for candidate in iterator:
        if not candidate.is_file() or candidate.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        if excluded is not None:
            try:
                candidate.resolve().relative_to(excluded)
                continue
            except ValueError:
                pass
        files.append(candidate)
    return sorted(files, key=lambda item: str(item).lower())


def _settings_payload(settings: DetectionSettings) -> dict[str, object]:
    return {
        "sensitivity": settings.sensitivity,
        "pre": settings.pre,
        "post": settings.post,
        "min_clip": settings.min_clip,
        "max_clips": settings.max_clips,
        "audio_weight": settings.audio_weight,
        "visual_weight": settings.visual_weight,
        "sample_fps": settings.sample_fps,
        "merge_gap": settings.merge_gap,
        "threads": settings.threads,
        "proxy_width": settings.proxy_width,
        "gpu": settings.gpu,
        "ai": settings.ai,
        "ai_model": settings.ai_model,
        "ai_game": settings.ai_game,
        "ai_mode": settings.ai_mode,
    }


def analyze_file(
    path: Path,
    settings: DetectionSettings,
    bins: FFmpegBinaries,
    preview_dir: Path | None = None,
    progress: ProgressFn | None = None,
) -> FileAnalysis:
    _report(progress, 0.01, "Reading media info")
    info = probe_media(path, bins)
    if info.duration < 1.0:
        raise ClipperError(f"{path.name}: video is too short to analyze")

    warnings: list[str] = []
    previews: list[str] = []
    audio_track = ScoreTrack(np.array([]), np.array([]))
    visual_track = ScoreTrack(np.array([]), np.array([]))
    wav: Path | None = None

    with tempfile.TemporaryDirectory(prefix="clipper_") as temp_raw:
        temp = Path(temp_raw)

        if info.has_audio:
            try:
                _report(progress, 0.08, "Extracting audio")
                wav = extract_audio(path, temp / "audio.wav", bins, threads=settings.threads)
                _report(progress, 0.22, "Detecting audio spikes")
                audio_track = analyze_wav(wav)
                if audio_track.empty:
                    warnings.append("Audio track is flat or silent; relying on motion.")
            except (FFmpegError, OSError, ValueError) as exc:
                warnings.append(f"Audio analysis skipped: {exc}")
        else:
            warnings.append("No audio track; using visual detection only.")

        try:
            _report(progress, 0.30, "Building low-res video proxy")
            proxy = make_proxy(
                path,
                temp / "proxy.mp4",
                fps=settings.sample_fps,
                width=settings.proxy_width,
                bins=bins,
                threads=settings.threads,
                gpu=settings.gpu,
            )
            _report(progress, 0.58, f"Detecting motion ({last_proxy_backend() or 'proxy'})")
            visual_track = analyze_visual(
                proxy,
                sample_fps=settings.sample_fps,
                threads=settings.threads,
            )
            backend = last_proxy_backend()
            if settings.gpu and backend and "NVENC" not in backend:
                warnings.append(
                    f"GPU proxy requested, but FFmpeg used {backend}. "
                    "Check the driver/encoder or run `clipper gpu`."
                )
            if visual_track.empty:
                warnings.append("Visual track is flat; relying on audio.")
        except (FFmpegError, OSError, RuntimeError) as exc:
            warnings.append(f"Visual analysis skipped: {exc}")

        if audio_track.empty and visual_track.empty and not settings.ai:
            warnings.append("No usable highlight signal was detected.")
            return FileAnalysis(
                path=str(path.resolve()),
                name=path.name,
                info=info,
                clips=[],
                warnings=warnings,
            )

        _report(progress, 0.80, "Fusing excitement score")
        grid = np.arange(0.0, max(0.25, info.duration), 0.25, dtype=np.float64)
        audio = resample_track(audio_track, grid)
        visual = resample_track(visual_track, grid)
        combined = fuse_tracks(
            grid,
            audio,
            visual,
            audio_weight=settings.audio_weight,
            visual_weight=settings.visual_weight,
        )

        _report(progress, 0.88, "Selecting and merging clips")
        if settings.ai:
            if settings.ai_mode == "director":
                try:
                    from .detect.story import direct_clip

                    clips, ai_warnings = direct_clip(
                        path,
                        info.duration,
                        settings,
                        wav,
                        audio_track,
                        bins,
                        progress=progress,
                    )
                    warnings.extend(ai_warnings)
                except Exception as exc:
                    warnings.append(f"AI director skipped: {exc}")
                    clips = pick_peaks(grid, combined, audio, visual, settings, info.duration)
            else:
                try:
                    from .detect.ai import build_candidates, review_candidates

                    candidates = build_candidates(grid, audio, visual, combined, settings, info.duration)
                    clips, ai_warnings = review_candidates(
                        path,
                        candidates,
                        settings,
                        info.duration,
                        progress=progress,
                    )
                    warnings.extend(ai_warnings)
                except Exception as exc:
                    warnings.append(f"AI review skipped: {exc}")
                    clips = pick_peaks(grid, combined, audio, visual, settings, info.duration)
        else:
            clips = pick_peaks(grid, combined, audio, visual, settings, info.duration)

        if preview_dir is not None and settings.preview:
            preview_dir.mkdir(parents=True, exist_ok=True)
            safe = _safe_stem(path.stem)
            for index, clip in enumerate(clips, start=1):
                try:
                    thumb = preview_dir / f"{safe}_clip{index:02d}_{int(clip.peak * 1000):08d}.jpg"
                    make_thumbnail(path, clip.peak, thumb, bins=bins)
                    previews.append(str(thumb.resolve()))
                except (FFmpegError, OSError) as exc:
                    warnings.append(f"Preview failed for clip {index}: {exc}")

        _report(progress, 1.0, f"Found {len(clips)} clip(s)")
        return FileAnalysis(
            path=str(path.resolve()),
            name=path.name,
            info=info,
            clips=clips,
            warnings=warnings,
            previews=previews,
        )


def analyze_target(
    input_path: str | Path,
    settings: DetectionSettings,
    recursive: bool = False,
    preview_dir: Path | None = None,
    exclude: Path | None = None,
    progress: ProgressFn | None = None,
) -> AnalysisSummary:
    settings.validate()
    configure_cpu_limits(settings.threads)
    bins = find_ffmpeg()
    files = scan_inputs(input_path, recursive=recursive, exclude=exclude)
    if not files:
        raise ClipperError(
            f"No supported video files found in {Path(input_path).expanduser().resolve()}"
        )

    analyses: list[FileAnalysis] = []
    for index, file in enumerate(files):
        def file_progress(fraction: float, message: str, *, i: int = index, f: Path = file) -> None:
            overall = (i + fraction) / len(files)
            _report(progress, overall, f"[{i + 1}/{len(files)}] {f.name}: {message}")

        try:
            analyses.append(
                analyze_file(file, settings, bins, preview_dir=preview_dir, progress=file_progress)
            )
        except Cancelled:
            raise
        except Exception as exc:  # keep batch runs alive when one file is broken
            analyses.append(
                FileAnalysis(
                    path=str(file.resolve()),
                    name=file.name,
                    info=MediaInfo(path=str(file.resolve()), duration=0.0),
                    warnings=[],
                    error=str(exc),
                )
            )
            _report(progress, (index + 1) / len(files), f"[{index + 1}/{len(files)}] {file.name}: failed")

    return AnalysisSummary(
        files=analyses,
        input_path=str(Path(input_path).expanduser().resolve()),
        setting_summary=_settings_payload(settings),
    )


def _safe_stem(stem: str, limit: int = 70) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    return (cleaned or "clip")[:limit]


def _compact_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes:02d}m{secs:02d}s"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise ClipperError(f"Could not find a free filename for {path.name}")


def export_analysis(
    summary: AnalysisSummary,
    output_dir: str | Path = "./trimmed",
    reencode: bool = False,
    encoder: str = "libx264",
    crf: int = 20,
    preset: str = "veryfast",
    progress: ProgressFn | None = None,
    threads: int = 0,
) -> ExportResult:
    configure_cpu_limits(threads)
    bins = find_ffmpeg()
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[FileAnalysis, int, ClipWindow]] = []
    for analysis in summary.files:
        if analysis.error:
            continue
        for index, clip in enumerate(analysis.clips, start=1):
            jobs.append((analysis, index, clip))

    result = ExportResult(clips_total=len(jobs))
    if not jobs:
        return result

    for done, (analysis, index, clip) in enumerate(jobs):
        suffix = ".mp4" if reencode else Path(analysis.path).suffix.lower()
        if suffix not in VIDEO_EXTENSIONS:
            suffix = ".mp4"
        filename = (
            f"{_safe_stem(Path(analysis.path).stem)}_clip_{index:02d}_"
            f"{_compact_time(clip.start)}-{_compact_time(clip.end)}{suffix}"
        )
        target = _unique_path(destination / filename)
        _report(
            progress,
            done / len(jobs),
            f"Exporting {target.name} ({done + 1}/{len(jobs)})",
        )
        try:
            rendered, used_reencode = render_clip(
                analysis.path,
                clip,
                target,
                reencode=reencode,
                encoder=encoder,
                crf=crf,
                preset=preset,
                bins=bins,
                threads=threads,
            )
            result.outputs.append(rendered)
            if used_reencode:
                result.reencoded.append(rendered)
        except (FFmpegError, OSError) as exc:
            result.errors.append(f"{analysis.name} clip {index}: {exc}")

    _report(progress, 1.0, f"Exported {len(result.outputs)} clip(s)")
    return result
