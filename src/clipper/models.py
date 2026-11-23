from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def fmt_time(seconds: float) -> str:
    """Format seconds as H:MM:SS.mmm (or M:SS.mmm for short clips)."""

    seconds = max(0.0, float(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours >= 1:
        return f"{int(hours)}:{int(minutes):02d}:{secs:06.3f}"
    return f"{int(minutes)}:{secs:06.3f}"


def fmt_short(seconds: float) -> str:
    return fmt_time(seconds).replace(".000", "")


@dataclass
class MediaInfo:
    path: str
    duration: float
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = False
    video_codec: str = ""
    audio_codec: str = ""
    size_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "duration": round(self.duration, 3),
            "duration_label": fmt_short(self.duration),
            "width": self.width,
            "height": self.height,
            "fps": round(self.fps, 3),
            "has_audio": self.has_audio,
            "video_codec": self.video_codec,
            "audio_codec": self.audio_codec,
            "size_bytes": self.size_bytes,
        }


@dataclass
class ClipWindow:
    start: float
    end: float
    peak: float
    score: float
    audio_score: float = 0.0
    visual_score: float = 0.0
    reason: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def score_pct(self) -> int:
        return int(round(float(self.score) * 100))

    @property
    def start_label(self) -> str:
        return fmt_time(self.start)

    @property
    def end_label(self) -> str:
        return fmt_time(self.end)

    @property
    def duration_label(self) -> str:
        return fmt_short(self.duration)

    @property
    def peak_label(self) -> str:
        return fmt_time(self.peak)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.duration, 3),
            "peak": round(self.peak, 3),
            "score": round(float(self.score), 4),
            "score_pct": int(round(float(self.score) * 100)),
            "audio_score": round(float(self.audio_score), 4),
            "visual_score": round(float(self.visual_score), 4),
            "reason": self.reason,
            "start_label": fmt_time(self.start),
            "end_label": fmt_time(self.end),
            "duration_label": fmt_short(self.duration),
            "peak_label": fmt_time(self.peak),
        }


@dataclass
class FileAnalysis:
    path: str
    name: str
    info: MediaInfo
    clips: list[ClipWindow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    previews: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self, include_previews: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "path": self.path,
            "name": self.name,
            "info": self.info.to_dict(),
            "clips": [clip.to_dict() for clip in self.clips],
            "warnings": list(self.warnings),
            "clip_count": len(self.clips),
            "error": self.error,
        }
        if include_previews:
            payload["previews"] = list(self.previews)
        return payload


@dataclass
class AnalysisSummary:
    files: list[FileAnalysis]
    input_path: str
    setting_summary: dict[str, Any] = field(default_factory=dict)

    @property
    def total_clips(self) -> int:
        return sum(len(item.clips) for item in self.files)

    def to_dict(self, include_previews: bool = True) -> dict[str, Any]:
        return {
            "input": self.input_path,
            "files": [f.to_dict(include_previews=include_previews) for f in self.files],
            "summary": {
                "files": len(self.files),
                "clips": self.total_clips,
                "settings": self.setting_summary,
            },
        }
