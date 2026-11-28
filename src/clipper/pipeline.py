from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
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
from .detect.visual import analyze_visual_tracks
from .ffmpeg import (
    FFmpegError,
    extract_audio,
    last_proxy_backend,
    make_proxy,
    make_thumbnail,
    nvenc_available,
    probe_media,
    render_clip,
)
from .models import (
    AnalysisSummary,
    ClipWindow,
    FileAnalysis,
    MediaInfo,
    clip_key,
)
from .presets import (
    ExportPreset,
    LOSSLESS,
    output_suffix,
    preset_for,
    render_filename,
)
from .reframe import plan_reframe

ProgressFn = Callable[[float, str], None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class ExportItem:
    source: str
    clip_id: str
    start: float
    end: float
    preset: str = "lossless"
    path: str = ""
    error: str = ""
    at: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "clip_id": self.clip_id,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "preset": self.preset,
            "path": self.path,
            "error": self.error,
            "at": self.at or _utc_now(),
        }


@dataclass
class ExportResult:
    outputs: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    reencoded: list[Path] = field(default_factory=list)
    clips_total: int = 0
    items: list[ExportItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "outputs": [str(path) for path in self.outputs],
            "errors": list(self.errors),
            "reencoded": [str(path) for path in self.reencoded],
            "clips_total": self.clips_total,
            "items": [item.to_dict() for item in self.items],
            "warnings": list(self.warnings),
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
        "ai_server_url": settings.ai_server_url,
        "ai_runtime": settings.ai_runtime,
        "ai_ears": settings.ai_ears,
        "ai_ears_model": settings.ai_ears_model,
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
    jerk_track = ScoreTrack(np.array([]), np.array([]))
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
            visual_track, jerk_track = analyze_visual_tracks(
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

        _report(progress, 0.88, "Selecting and merging clips")
        if settings.ai:
            file_settings = settings
            if settings.ai_game.strip().lower() == "auto":
                from .gameguard import detect_game_from_path

                guessed = detect_game_from_path(path)
                if guessed:
                    file_settings = replace(settings, ai_game=guessed)
            try:
                from .detect.story import direct_clip

                clips, ai_warnings = direct_clip(
                    path,
                    info.duration,
                    file_settings,
                    wav,
                    audio_track,
                    bins,
                    progress=progress,
                    jerk=jerk_track,
                )
                warnings.extend(ai_warnings)
            except Exception as exc:
                # AI-only product: never silently replace the director with the
                # old audio/motion peak cutter. Report the failure instead.
                warnings.append(f"AI director failed: {exc}")
                clips = []
        else:
            # Library/test path only: the CLI, desktop, and web UI always use
            # the director. The fused audio/motion score is computed only here,
            # because the director ignores the detector weights.
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
    on_file_done: Callable[[FileAnalysis], None] | None = None,
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
            analysis = analyze_file(
                file, settings, bins, preview_dir=preview_dir, progress=file_progress
            )
            analyses.append(analysis)
            if on_file_done is not None:
                on_file_done(analysis)
        except Cancelled:
            raise
        except Exception as exc:  # keep batch runs alive when one file is broken
            analysis = FileAnalysis(
                path=str(file.resolve()),
                name=file.name,
                info=MediaInfo(path=str(file.resolve()), duration=0.0),
                warnings=[],
                error=str(exc),
            )
            analyses.append(analysis)
            if on_file_done is not None:
                on_file_done(analysis)
            _report(progress, (index + 1) / len(files), f"[{index + 1}/{len(files)}] {file.name}: failed")

    return AnalysisSummary(
        files=analyses,
        input_path=str(Path(input_path).expanduser().resolve()),
        setting_summary=_settings_payload(settings),
    )


def _safe_stem(stem: str, limit: int = 70) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    return (cleaned or "clip")[:limit]


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise ClipperError(f"Could not find a free filename for {path.name}")


def _custom_preset(reencode: bool, encoder: str, crf: int) -> ExportPreset:
    if not reencode:
        return LOSSLESS
    key = str(encoder).lower()
    codec = "hevc" if "hevc" in key or "265" in key else "h264"
    return ExportPreset(
        id="custom",
        label="Custom re-encode",
        description="Frame-accurate re-encode with the selected encoder.",
        fit="source",
        codec=codec,
        quality=int(crf),
        suffix="",
    )


def export_analysis(
    summary: AnalysisSummary,
    output_dir: str | Path = "./trimmed",
    reencode: bool = False,
    encoder: str = "libx264",
    crf: int = 20,
    preset: str = "veryfast",
    progress: ProgressFn | None = None,
    threads: int = 0,
    *,
    export_preset: ExportPreset | str | None = None,
    filename_template: str | None = None,
    reframe_mode: str = "auto",
) -> ExportResult:
    """Export clips with lossless copy or a creator preset.

    ``preset`` remains the x264 speed preset for compatibility. The output
    format is selected with ``export_preset``. When it is omitted, the old
    ``reencode``/``encoder``/``crf`` behavior is preserved.
    """

    configure_cpu_limits(threads)
    bins = find_ffmpeg()
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)

    if export_preset is None:
        chosen = _custom_preset(reencode, encoder, crf)
        explicit_encoder = encoder if reencode else ""
    else:
        chosen = preset_for(export_preset)
        explicit_encoder = ""

    nvenc = False if chosen.lossless else nvenc_available(bins)
    if chosen.codec == "copy":
        resolved_encoder = "libx264"
    elif chosen.codec == "hevc":
        resolved_encoder = "hevc_nvenc" if nvenc else "libx265"
    else:
        resolved_encoder = "h264_nvenc" if nvenc else "libx264"
    if explicit_encoder and explicit_encoder not in {"auto", "gpu"}:
        resolved_encoder = explicit_encoder

    jobs: list[tuple[FileAnalysis, int, ClipWindow]] = []
    for analysis in summary.files:
        if analysis.error:
            continue
        for index, clip in enumerate(analysis.clips, start=1):
            if not clip.id:
                clip.id = clip_key(analysis.path, clip.start, clip.end)
            jobs.append((analysis, index, clip))

    result = ExportResult(clips_total=len(jobs))
    if not jobs:
        return result

    game = str(summary.setting_summary.get("ai_game") or "")
    created_at = summary.created_at or _utc_now()
    for done, (analysis, index, clip) in enumerate(jobs):
        suffix = output_suffix(chosen, analysis.path)
        filename = render_filename(
            filename_template,
            source=analysis.path,
            clip=clip,
            index=index,
            preset=chosen,
            game=game,
            created_at=created_at,
        )
        target = _unique_path(destination / f"{filename}{suffix}")
        item = ExportItem(
            source=analysis.path,
            clip_id=clip.id,
            start=clip.start,
            end=clip.end,
            preset=chosen.id,
            at=_utc_now(),
        )
        _report(
            progress,
            done / len(jobs),
            f"Exporting {target.name} ({done + 1}/{len(jobs)})",
        )
        plan = None
        wants_reframe = (
            chosen.reframe == "auto"
            and chosen.width > 0
            and chosen.height > 0
            and not chosen.lossless
            and str(reframe_mode).lower() not in {"none", "off", "center"}
        )
        if wants_reframe:
            _report(
                progress,
                done / len(jobs),
                f"Tracking the action for {target.name} ({done + 1}/{len(jobs)})",
            )
            try:
                plan = plan_reframe(
                    analysis.path,
                    clip.start,
                    clip.end,
                    chosen.width,
                    chosen.height,
                    mode=reframe_mode,
                )
            except Exception as exc:
                result.warnings.append(
                    f"{analysis.name} clip {index}: reframe skipped ({exc})."
                )
        try:
            rendered, used_reencode = render_clip(
                analysis.path,
                clip,
                target,
                reencode=not chosen.lossless,
                encoder=resolved_encoder,
                crf=chosen.quality if export_preset is not None else crf,
                preset=preset,
                bins=bins,
                threads=threads,
                target_width=chosen.width,
                target_height=chosen.height,
                fit=chosen.fit,
                fps=chosen.fps,
                audio_bitrate=chosen.audio_bitrate,
                reframe_plan=plan,
                fallback_encoder=(
                    "libx265" if chosen.codec == "hevc" else "libx264"
                ),
            )
            item.path = str(rendered)
            result.outputs.append(rendered)
            result.items.append(item)
            if used_reencode:
                result.reencoded.append(rendered)
        except (FFmpegError, OSError) as exc:
            message = f"{analysis.name} clip {index}: {exc}"
            item.error = str(exc)
            result.errors.append(message)
            result.items.append(item)

    _report(progress, 1.0, f"Exported {len(result.outputs)} clip(s)")
    return result
