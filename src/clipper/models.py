from __future__ import annotations

import hashlib
import os
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


def clip_key(source: str, start: float, end: float) -> str:
    """A stable local identifier for one clip in one source file.

    The key is derived from the source path and the cut boundaries. It is used
    to keep library notes, keep/reject decisions, and export history attached
    when a scan is reopened. No footage or personal text leaves the machine.
    """

    try:
        normalized = os.path.normcase(os.path.abspath(str(source)))
    except (OSError, TypeError, ValueError):
        normalized = str(source).strip().lower()
    raw = f"{normalized}|{float(start):.2f}|{float(end):.2f}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


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

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "MediaInfo":
        data = _as_dict(payload)
        path = str(data.get("path") or "")
        return cls(
            path=path,
            duration=max(0.0, _as_float(data.get("duration"))),
            width=max(0, _as_int(data.get("width"))),
            height=max(0, _as_int(data.get("height"))),
            fps=max(0.0, _as_float(data.get("fps"))),
            has_audio=bool(data.get("has_audio")),
            video_codec=str(data.get("video_codec") or ""),
            audio_codec=str(data.get("audio_codec") or ""),
            size_bytes=max(0, _as_int(data.get("size_bytes"))),
        )


@dataclass
class ClipWindow:
    start: float
    end: float
    peak: float
    score: float
    audio_score: float = 0.0
    visual_score: float = 0.0
    reason: str = ""
    id: str = ""
    keep: bool = True
    note: str = ""
    tags: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    exports: list[dict[str, Any]] = field(default_factory=list)

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
            "id": self.id,
            "keep": bool(self.keep),
            "note": self.note,
            "tags": list(self.tags),
            "evidence": dict(self.evidence),
            "exports": [dict(item) for item in self.exports],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ClipWindow":
        data = _as_dict(payload)
        start = max(0.0, _as_float(data.get("start")))
        end = max(start, _as_float(data.get("end"), start))
        peak = min(end, max(start, _as_float(data.get("peak"), (start + end) / 2.0)))
        tags = [str(tag) for tag in _as_list(data.get("tags")) if str(tag).strip()]
        return cls(
            start=start,
            end=end,
            peak=peak,
            score=max(0.0, min(1.0, _as_float(data.get("score")))),
            audio_score=_as_float(data.get("audio_score")),
            visual_score=_as_float(data.get("visual_score")),
            reason=str(data.get("reason") or ""),
            id=str(data.get("id") or ""),
            keep=bool(data.get("keep", True)),
            note=str(data.get("note") or ""),
            tags=tags,
            evidence=_as_dict(data.get("evidence")),
            exports=[dict(item) for item in _as_list(data.get("exports")) if isinstance(item, dict)],
        )


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

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "FileAnalysis":
        data = _as_dict(payload)
        path = str(data.get("path") or "")
        name = str(data.get("name") or Path(path).name or "video")
        info = MediaInfo.from_dict(data.get("info"))
        if not info.path:
            info.path = path
        clips = [
            ClipWindow.from_dict(item)
            for item in _as_list(data.get("clips"))
            if isinstance(item, dict)
        ]
        return cls(
            path=path,
            name=name,
            info=info,
            clips=clips,
            warnings=[str(item) for item in _as_list(data.get("warnings"))],
            previews=[str(item) for item in _as_list(data.get("previews"))],
            error=str(data["error"]) if data.get("error") else None,
        )


@dataclass
class AnalysisSummary:
    files: list[FileAnalysis]
    input_path: str
    setting_summary: dict[str, Any] = field(default_factory=dict)
    scan_id: str = ""
    created_at: str = ""
    updated_at: str = ""

    @property
    def total_clips(self) -> int:
        return sum(len(item.clips) for item in self.files)

    def to_dict(self, include_previews: bool = True) -> dict[str, Any]:
        return {
            "input": self.input_path,
            "scan_id": self.scan_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "files": [f.to_dict(include_previews=include_previews) for f in self.files],
            "summary": {
                "files": len(self.files),
                "clips": self.total_clips,
                "kept": sum(
                    1
                    for item in self.files
                    for clip in item.clips
                    if clip.keep
                ),
                "settings": self.setting_summary,
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "AnalysisSummary":
        data = _as_dict(payload)
        summary = _as_dict(data.get("summary"))
        files = [
            FileAnalysis.from_dict(item)
            for item in _as_list(data.get("files"))
            if isinstance(item, dict)
        ]
        settings = summary.get("settings")
        if not isinstance(settings, dict):
            settings = data.get("setting_summary")
        return cls(
            files=files,
            input_path=str(data.get("input") or data.get("input_path") or ""),
            setting_summary=_as_dict(settings),
            scan_id=str(data.get("scan_id") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )
