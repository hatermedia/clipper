from __future__ import annotations

import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import FFmpegBinaries
from ..ffmpeg import make_thumbnail

# OCR is used only to verify what the vision model claims. Sampling the whole
# frame at 1280 px keeps kill-feed names, round banners, score bugs, and chat
# readable without dominating runtime.
HUD_SAMPLE_OFFSETS = (0.0, 0.25, 0.50, 0.75, 1.0)
HUD_WIDTH = 1280
HUD_MIN_SCORE = 0.45


@dataclass(frozen=True)
class HudLine:
    time: float
    text: str


@dataclass
class HudReading:
    lines: list[HudLine] = field(default_factory=list)
    available: bool = False


_ENGINE: Any = None
_ENGINE_FAILED_AT = 0.0
_ENGINE_RETRY_SECONDS = 60.0
_ENGINE_LOCK = threading.Lock()


def _engine() -> Any:
    global _ENGINE, _ENGINE_FAILED_AT
    if _ENGINE is not None:
        return _ENGINE
    now = time.monotonic()
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        if _ENGINE_FAILED_AT and now - _ENGINE_FAILED_AT < _ENGINE_RETRY_SECONDS:
            return None
        try:
            from rapidocr_onnxruntime import RapidOCR

            _ENGINE = RapidOCR()
            _ENGINE_FAILED_AT = 0.0
        except Exception:
            _ENGINE_FAILED_AT = time.monotonic()
            return None
    return _ENGINE


def _mark_engine_failed() -> None:
    global _ENGINE, _ENGINE_FAILED_AT
    with _ENGINE_LOCK:
        _ENGINE = None
        _ENGINE_FAILED_AT = time.monotonic()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def read_hud(
    video: Path,
    start: float,
    end: float,
    bins: FFmpegBinaries,
    *,
    samples: tuple[float, ...] = HUD_SAMPLE_OFFSETS,
    width: int = HUD_WIDTH,
) -> HudReading:
    engine = _engine()
    if engine is None:
        return HudReading(available=False)
    span = max(0.1, end - start)
    seen: set[str] = set()
    lines: list[HudLine] = []
    engine_attempts = 0
    engine_successes = 0
    with tempfile.TemporaryDirectory(prefix="clipper_hud_") as raw:
        temp = Path(raw)
        for index, offset in enumerate(samples):
            timestamp = min(end - 0.05, start + span * offset)
            jpg = temp / f"hud_{index}.jpg"
            try:
                make_thumbnail(video, timestamp, jpg, width=width, bins=bins, crop=None)
            except Exception:
                continue
            engine_attempts += 1
            try:
                result, _ = engine(str(jpg))
            except Exception:
                continue
            engine_successes += 1
            for item in result or []:
                try:
                    _box, text, score = item
                except (TypeError, ValueError):
                    continue
                cleaned = _clean(text)
                try:
                    score_value = float(score or 0.0)
                except (TypeError, ValueError):
                    continue
                if len(cleaned) < 2 or score_value < HUD_MIN_SCORE:
                    continue
                key = re.sub(r"[^a-z0-9]", "", cleaned.lower())
                if not key or key in seen:
                    continue
                seen.add(key)
                lines.append(HudLine(timestamp, cleaned))
    if engine_attempts and not engine_successes:
        _mark_engine_failed()
        return HudReading(available=False)
    return HudReading(lines=lines, available=True)


def compact(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


_MATCHERS: dict[str, re.Pattern[str]] = {
    "round": re.compile(
        r"^(WON|LOST|VICTORY|DEFEAT)(ROUND)?$|ENEMYTEAMELIMINATED|"
        r"SPIKE(DEFUSED|PLANTED)|ROUND(WIN|LOSS)"
    ),
    "goal": re.compile(r"SCORED|OWNGOAL|AERIALGOAL|^GOAL$|GOALSCORED"),
    "multikill": re.compile(
        r"^(ACE|DOUBLEKILL|TRIPLEKILL|QUADRAKILL|PENTAKILL|MULTIKILL)$"
    ),
    "clutch": re.compile(r"^CLUTCH|^1V[2-5]$|ENEMYTEAMELIMINATED"),
    "save": re.compile(r"EPICSAVE|^SAVED$"),
    "demo": re.compile(r"DEMOLITION|^DEMO$"),
}

# Big events are often printed on their own banner. A lone "WON" or "ACE" in a
# different UI element should still count, so the round/ace matchers allow the
# token at the start of a short line.
_SHORT_EVENT_PREFIXES = {
    "round": ("WON", "LOST", "VICTORY", "DEFEAT"),
    "multikill": ("ACE",),
    "clutch": ("CLUTCH",),
}

_CHAT_CUES = re.compile(
    r"\b(lol|lmao|lmfao|haha|hehe|bruh|ez|gg|no way|what a save|nice shot|"
    r"great pass|nice bump|whoops|stop|serious|rage|crying|wow|crazy|insane|"
    r"unbelievable|kidding|clip it)\b",
    re.IGNORECASE,
)
_NON_CHAT = (
    "SPOTTEDANENEMY",
    "ENEMYREMAINING",
    "RELOADING",
    "SPIKE",
    "CLIENTVERSION",
    "CLIENTFPS",
    "BALLCAM",
    "PRESS",
)


_DISPLAY = (
    ("ENEMYTEAMELIMINATED", "ENEMY TEAM ELIMINATED"),
    ("SPIKEDEFUSED", "SPIKE DEFUSED"),
    ("SPIKEPLANTED", "SPIKE PLANTED"),
    ("LOVELYSCORED", "LOVELY SCORED"),
    ("GOALSCORED", "GOAL SCORED"),
    ("SCOREDBY", "SCORED"),
    ("SHOTONGOAL", "SHOT ON GOAL"),
    ("TRIPLEKILL", "TRIPLE KILL"),
    ("QUADRAKILL", "QUADRA KILL"),
    ("PENTAKILL", "PENTA KILL"),
    ("DOUBLEKILL", "DOUBLE KILL"),
    ("MULTIKILL", "MULTI KILL"),
    ("EPICSAVE", "EPIC SAVE"),
    ("CLUTCH", "CLUTCH"),
    ("WON", "WON"),
    ("LOST", "LOST"),
    ("VICTORY", "VICTORY"),
    ("DEFEAT", "DEFEAT"),
    ("ACE", "ACE"),
    ("SAVED", "SAVED"),
)


def event_lines(kind: str, lines: list[HudLine]) -> list[HudLine]:
    matcher = _MATCHERS.get(kind)
    if matcher is None:
        return []
    hits: list[HudLine] = []
    for line in lines:
        text = compact(line.text)
        if matcher.search(text):
            hits.append(line)
            continue
        for prefix in _SHORT_EVENT_PREFIXES.get(kind, ()):
            if text.startswith(prefix) and len(text) <= len(prefix) + 4:
                hits.append(line)
                break
    if kind == "goal":
        hits = [line for line in hits if "SHOTON" not in compact(line.text)]
        hits.sort(key=lambda line: 0 if "SCORED" in compact(line.text) else 1)
    return hits


def chat_cue(lines: list[HudLine]) -> HudLine | None:
    for line in lines:
        text = compact(line.text)
        if any(token in text for token in _NON_CHAT):
            continue
        if _CHAT_CUES.search(line.text):
            return line
    return None


def display_text(lines: list[HudLine], limit: int = 2) -> str:
    picked: list[str] = []
    for line in lines:
        text = _clean(line.text).strip(" -_|")
        if not text:
            continue
        compacted = compact(text)
        for token, nice in _DISPLAY:
            if token in compacted:
                text = nice
                break
        if any(text.lower() == existing.lower() for existing in picked):
            continue
        picked.append(text)
        if len(picked) >= limit:
            break
    return " / ".join(picked)
