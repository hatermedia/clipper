"""Creator export presets and filename templates.

Presets describe the output container, frame size, fit mode, codec, quality, and
whether the clip should follow the action with an automatic vertical reframe.
The pipeline turns these descriptions into FFmpeg arguments; the desktop and CLI
share the same registry so a preset behaves the same everywhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import ClipWindow


@dataclass(frozen=True)
class ExportPreset:
    id: str
    label: str
    description: str
    container: str = ".mp4"
    width: int = 0
    height: int = 0
    fit: str = "source"
    codec: str = "copy"
    quality: int = 20
    audio_bitrate: str = "192k"
    fps: int = 0
    reframe: str = "none"
    suffix: str = ""

    @property
    def lossless(self) -> bool:
        return self.codec == "copy"

    @property
    def vertical(self) -> bool:
        return self.width > 0 and self.width < self.height

    @property
    def square(self) -> bool:
        return self.width > 0 and self.width == self.height

    def encoder(self, prefer_nvenc: bool = True) -> str:
        if self.codec == "hevc":
            return "hevc_nvenc" if prefer_nvenc else "libx265"
        if self.codec == "h264":
            return "h264_nvenc" if prefer_nvenc else "libx264"
        return "libx264"


LOSSLESS = ExportPreset(
    id="lossless",
    label="Lossless cut",
    description="Original video and audio, stream copy. Fast and edit-ready.",
)

PRESETS: tuple[ExportPreset, ...] = (
    LOSSLESS,
    ExportPreset(
        id="shorts",
        label="YouTube Shorts",
        description="1080 x 1920, 9:16 auto reframe, H.264.",
        width=1080,
        height=1920,
        fit="crop",
        codec="h264",
        quality=20,
        reframe="auto",
        suffix="_shorts",
    ),
    ExportPreset(
        id="tiktok",
        label="TikTok",
        description="1080 x 1920, 9:16 auto reframe, H.264.",
        width=1080,
        height=1920,
        fit="crop",
        codec="h264",
        quality=20,
        reframe="auto",
        suffix="_tiktok",
    ),
    ExportPreset(
        id="reels",
        label="Instagram Reels",
        description="1080 x 1920, 9:16 auto reframe, H.264.",
        width=1080,
        height=1920,
        fit="crop",
        codec="h264",
        quality=20,
        reframe="auto",
        suffix="_reels",
    ),
    ExportPreset(
        id="square",
        label="Square",
        description="1080 x 1080, 1:1 auto reframe, H.264.",
        width=1080,
        height=1080,
        fit="crop",
        codec="h264",
        quality=20,
        reframe="auto",
        suffix="_square",
    ),
    ExportPreset(
        id="landscape",
        label="Landscape 1080p",
        description="1920 x 1080, 16:9 crop, H.264.",
        width=1920,
        height=1080,
        fit="crop",
        codec="h264",
        quality=20,
        suffix="_1080p",
    ),
    ExportPreset(
        id="shorts_hevc",
        label="Shorts HEVC",
        description="1080 x 1920, 9:16 auto reframe, HEVC. Smaller files.",
        width=1080,
        height=1920,
        fit="crop",
        codec="hevc",
        quality=23,
        reframe="auto",
        suffix="_shorts_hevc",
    ),
    ExportPreset(
        id="h264",
        label="Frame-accurate H.264",
        description="Source size, H.264 re-encode, no reframe.",
        fit="source",
        codec="h264",
        quality=18,
        suffix="_h264",
    ),
)

_BY_ID = {preset.id: preset for preset in PRESETS}
DEFAULT_TEMPLATE = "{source}_clip_{index:02d}_{start}-{end}"
# Letters and digits from any script are kept (\w is Unicode-aware), so a
# Japanese or accented source name survives. Path separators, Windows-reserved
# punctuation, spaces, and emoji become underscores.
_FILENAME_RE = re.compile(r"[^\w.-]+")
_DOTS_RE = re.compile(r"\.{2,}")
# Format specs with a 4+ digit width/precision (e.g. {index:99999999}) are
# refused so a template cannot allocate gigantic strings.
_HUGE_FORMAT_RE = re.compile(r"\{[^{}]*:[^{}]*\d{4,}[^{}]*\}")


def preset_for(value: str | ExportPreset | None) -> ExportPreset:
    if isinstance(value, ExportPreset):
        return value
    key = str(value or "").strip().lower()
    if not key:
        return LOSSLESS
    found = _BY_ID.get(key)
    if found is not None:
        return found
    for preset in PRESETS:
        if preset.label.lower() == key:
            return preset
    raise KeyError(f"Unknown export preset: {value}")


def preset_choices() -> tuple[ExportPreset, ...]:
    return PRESETS


def safe_stem(stem: str, limit: int = 70) -> str:
    cleaned = _DOTS_RE.sub(".", _FILENAME_RE.sub("_", str(stem))).strip("._-")
    return (cleaned or "clip")[:limit]


def compact_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    minutes, secs = divmod(int(round(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}h{minutes:02d}m{secs:02d}s"
    return f"{minutes:02d}m{secs:02d}s"


def render_filename(
    template: str | None,
    *,
    source: str,
    clip: ClipWindow,
    index: int,
    preset: ExportPreset,
    game: str = "",
    created_at: str = "",
) -> str:
    """Render a user filename template without allowing path traversal."""

    pattern = (template or DEFAULT_TEMPLATE).strip() or DEFAULT_TEMPLATE
    source_stem = safe_stem(Path(source).stem)
    try:
        date_value = datetime.fromisoformat(created_at).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        date_value = datetime.now().strftime("%Y-%m-%d")
    values = {
        "source": source_stem,
        "index": max(1, int(index)),
        "start": compact_time(clip.start),
        "end": compact_time(clip.end),
        "duration": compact_time(clip.duration),
        "score": clip.score_pct,
        "peak": compact_time(clip.peak),
        "preset": preset.id,
        "game": safe_stem(game) if game and game.lower() != "auto" else "game",
        "date": date_value,
    }
    if _HUGE_FORMAT_RE.search(pattern) or len(pattern) > 300:
        pattern = DEFAULT_TEMPLATE
    try:
        rendered = pattern.format_map(values)
    except (KeyError, ValueError, IndexError):
        rendered = DEFAULT_TEMPLATE.format_map(values)
    for extension in (".mp4", ".mkv", ".mov", ".avi"):
        if rendered.lower().endswith(extension):
            rendered = rendered[: -len(extension)]
            break
    if preset.suffix and "{preset}" not in pattern:
        rendered = f"{rendered}{preset.suffix}"
    rendered = safe_stem(rendered, limit=120)
    if not rendered:
        rendered = safe_stem(f"{source_stem}_clip_{index:02d}", limit=120)
    return rendered


def output_suffix(preset: ExportPreset, source: str | Path) -> str:
    if preset.lossless:
        suffix = Path(source).suffix.lower()
        if suffix in {".mp4", ".mkv", ".mov", ".avi"}:
            return suffix
        return ".mp4"
    return preset.container or ".mp4"


def aspect_label(preset: ExportPreset) -> str:
    if preset.width and preset.height:
        from math import gcd

        divisor = gcd(int(preset.width), int(preset.height)) or 1
        return f"{preset.width // divisor}:{preset.height // divisor}"
    return "source"
