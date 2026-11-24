"""Local vision-language review of highlight candidates via Ollama.

This is intentionally an optional second stage, not a replacement for the
cheap audio/motion pass. The VLM looks at three frames around a candidate and
decides whether the moment is worth clipping. Everything runs locally.
"""

from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import urllib.error
import urllib.request

import cv2
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ..config import DetectionSettings
from ..ffmpeg import FFmpegError, make_thumbnail
from ..models import ClipWindow
from .merge import merge_windows, pick_peaks

OLLAMA_URL = os.environ.get("CLIPPER_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODEL = "qwen2.5vl:7b"
FAST_MODEL = "qwen2.5vl:3b"
DEEP_MODEL = "qwen3-vl:4b"
PROMPT_VERSION = "valorant-v5"
AI_CROP = (0.10, 0.08, 0.80, 0.84)
AI_HUD_CROP = (0.10, 0.0, 0.88, 0.26)
AI_FRAME_WIDTH = 512
AI_HUD_WIDTH = 768
ProgressFn = Callable[[float, str], None]


class AIError(RuntimeError):
    """The local AI reviewer is unavailable or returned an unusable response."""


def _get_json(path: str, timeout: float = 4.0) -> dict[str, Any]:
    request = urllib.request.Request(f"{OLLAMA_URL}{path}", headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def ollama_status(timeout: float = 4.0) -> dict[str, Any]:
    try:
        payload = _get_json("/api/tags", timeout=timeout)
        models = [str(item.get("name", "")) for item in payload.get("models", [])]
        return {"ok": True, "models": models, "error": None}
    except Exception as exc:
        return {"ok": False, "models": [], "error": str(exc)}


def model_available(model: str) -> bool:
    status = ollama_status()
    if not status["ok"]:
        return False
    wanted = model.lower()
    wanted_base, _, wanted_tag = wanted.partition(":")
    for item in status["models"]:
        name = item.lower()
        if name == wanted:
            return True
        base, _, tag = name.partition(":")
        if base == wanted_base and (not wanted_tag or wanted_tag == tag):
            return True
    return False


def unload_model(model: str, timeout: float = 8.0) -> bool:
    """Ask Ollama to release the model's VRAM immediately."""

    payload = {"model": model, "prompt": "", "keep_alive": 0, "stream": False}
    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(200)
        return True
    except Exception:
        return False


def _cache_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
    path = base / "Clipper" / "ai-cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_key(video: Path, peak: float, model: str, game: str) -> Path:
    import hashlib

    try:
        mtime = video.stat().st_mtime
    except OSError:
        mtime = 0
    raw = f"{video.resolve()}|{mtime}|{peak:.2f}|{model}|{game}|{PROMPT_VERSION}"
    return _cache_dir() / (hashlib.sha256(raw.encode()).hexdigest()[:24] + ".json")


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = text.strip().replace("```json", "").replace("```", "").strip()
    start = cleaned.find("{")
    if start < 0:
        raise AIError("The model did not return JSON")
    try:
        value, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    except json.JSONDecodeError as exc:
        raise AIError(f"Could not parse AI JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise AIError("AI response was not a JSON object")
    return value


def _prompt(game: str, peak: float, count: int, hud: bool = False) -> str:
    game_label = game.strip() or "this game"
    hud_text = ""
    if hud:
        hud_text = (
            "\nThe final image is a zoomed crop of the top HUD (score, round timer, kill feed) "
            "from the frame after the candidate. Use it to read kill-feed entries, the score, "
            "or round text; do not treat HUD text alone as proof if it is unreadable.\n"
        )
    return f"""You are a strict highlight judge for {game_label} footage.
The first {count} images are center-cropped frames around {peak:.1f}s: before, at, and after the candidate.
The footage may be a Discord or streaming window; ignore chat, sidebars, overlays, and stream controls.
Look only at the game viewport in the center.{hud_text}
Step 1 - gameplay: Is this actual in-game gameplay with a visible game world and HUD?
A black screen, desktop, launcher, loading screen, menu, agent select, or buy menu is NOT gameplay.
If not gameplay: gameplay=false, highlight=false, confidence=1, category="none", reason="not gameplay".

Step 2 - event: Only for gameplay, look for a concrete visible event in these frames:
- a kill-feed entry (weapon icon or elimination text in the top-right)
- multikill, ace, or clutch text
- a round result banner (WON/LOST) or score change
- a spike plant/defuse indicator or timer change
- an active firefight: visible muzzle flash, tracer, bullet impact, damage feedback,
  or a kill-feed entry. Merely seeing an enemy, aiming, or holding an angle is NOT a firefight.
- a genuine reaction or clearly unusual play

Round-start spawning, running to site, and the buy phase are NOT highlights.
Do not describe anything you cannot actually see. The reason must cite the visible region
or text that proves the event. Only accept when the middle frame or the frame after it
shows the event itself.
If no concrete event is visible, return highlight=false.

Return JSON only, no markdown:
{{"gameplay": true|false, "highlight": true|false, "confidence": 0.0, "category": "multikill|clutch|round|firefight|reaction|ability|other|none", "reason": "short visible evidence with region", "best_frame": 1|2|3}}"""


def review_window(
    video: Path,
    peak: float,
    duration: float,
    model: str,
    game: str,
    timeout: float = 180.0,
) -> dict[str, Any]:
    cache = _cache_key(video, peak, model, game)
    if cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    offsets = (-2.0, 0.0, 2.0)
    times = [min(max(0.0, peak + offset), max(0.0, duration - 0.05)) for offset in offsets]
    with tempfile.TemporaryDirectory(prefix="clipper_ai_") as temp_raw:
        temp = Path(temp_raw)
        images: list[str] = []
        blank_flags: list[bool] = []
        for index, timestamp in enumerate(times):
            jpg = temp / f"frame_{index}.jpg"
            make_thumbnail(video, timestamp, jpg, width=AI_FRAME_WIDTH, crop=AI_CROP)
            image = cv2.imread(str(jpg), cv2.IMREAD_GRAYSCALE)
            if image is None:
                blank_flags.append(True)
            else:
                blank_flags.append(float(image.mean()) < 10 and float(image.std()) < 8)
            images.append(base64.b64encode(jpg.read_bytes()).decode("ascii"))

        if blank_flags and all(blank_flags):
            result = {
                "gameplay": False,
                "highlight": False,
                "confidence": 1.0,
                "category": "none",
                "reason": "blank/desktop frame",
                "best_frame": 2,
                "model": model,
                "peak": peak,
            }
            try:
                cache.write_text(json.dumps(result, indent=2), encoding="utf-8")
            except OSError:
                pass
            return result

        hud_available = False
        try:
            hud_jpg = temp / "hud.jpg"
            make_thumbnail(
                video,
                times[-1],
                hud_jpg,
                width=AI_HUD_WIDTH,
                crop=AI_HUD_CROP,
            )
            images.append(base64.b64encode(hud_jpg.read_bytes()).decode("ascii"))
            hud_available = True
        except (OSError, FFmpegError):
            hud_available = False

        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": _prompt(game, peak, len(offsets), hud=hud_available),
                    "images": images,
                }
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.0,
                "num_predict": 160,
                "num_ctx": 8192,
                "num_gpu": 99,
            },
            "keep_alive": "10m",
        }
        if model.lower().startswith("qwen3"):
            payload["think"] = False
        request = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read(800).decode("utf-8", errors="replace")
            raise AIError(f"Ollama HTTP {exc.code}: {body}") from exc
        except Exception as exc:
            raise AIError(f"Ollama request failed: {exc}") from exc

    content = str((data.get("message") or {}).get("content") or "")
    if not content:
        thinking = str((data.get("message") or {}).get("thinking") or "")
        raise AIError(
            "The model returned no final JSON"
            + (" (it exhausted the output budget while thinking)" if thinking else "")
        )
    verdict = _parse_json(content)
    gameplay = verdict.get("gameplay", True)
    if isinstance(gameplay, str):
        gameplay = gameplay.lower() == "true"
    highlight = verdict.get("highlight")
    if isinstance(highlight, str):
        highlight = highlight.lower() == "true"
    try:
        confidence = float(verdict.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    try:
        best_frame = int(verdict.get("best_frame", 2))
    except (TypeError, ValueError):
        best_frame = 2
    if not gameplay:
        highlight = False
        confidence = max(confidence, 0.95)
    result = {
        "gameplay": bool(gameplay),
        "highlight": bool(highlight),
        "confidence": max(0.0, min(1.0, confidence)),
        "category": str(verdict.get("category") or "other")[:40],
        "reason": str(verdict.get("reason") or "")[:240],
        "best_frame": max(1, min(3, best_frame)),
        "model": model,
        "peak": peak,
    }
    try:
        cache.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except OSError:
        pass
    return result


def build_candidates(
    grid: np.ndarray,
    audio: np.ndarray,
    visual: np.ndarray,
    combined: np.ndarray,
    settings: DetectionSettings,
    duration: float,
) -> list[ClipWindow]:
    """Higher-recall candidate windows for the VLM to review."""

    boosted = replace(
        settings,
        sensitivity=min(0.95, settings.sensitivity + 0.20),
        max_clips=max(1, settings.ai_max_candidates),
    )
    candidates: list[ClipWindow] = []
    candidates.extend(pick_peaks(grid, combined, audio, visual, boosted, duration))
    candidates.extend(pick_peaks(grid, audio, audio, visual, boosted, duration))
    candidates.extend(pick_peaks(grid, visual, audio, visual, boosted, duration))

    # Short ShadowPlay/DVR files are often 60-120s and contain one moment.
    # A cheap dense pass guarantees the VLM sees the gameplay even when the
    # heuristic peaks are dominated by a desktop or loading screen.
    if duration <= 300:
        step = max(8.0, duration / 12.0)
        t = step / 2
        while t < duration - 1.0:
            start = max(0.0, t - 2.0)
            end = min(duration, t + 2.0)
            candidates.append(
                ClipWindow(
                    start=start,
                    end=end,
                    peak=t,
                    score=0.05,
                    audio_score=0.0,
                    visual_score=0.0,
                    reason="AI dense scan",
                )
            )
            t += step
    elif not candidates:
        # Long, quiet video fallback: evenly spaced windows.
        step = max(12.0, duration / max(1, settings.ai_max_candidates))
        t = step / 2
        while t < duration - 1.0:
            start = max(0.0, t - 2.0)
            end = min(duration, t + 2.0)
            candidates.append(
                ClipWindow(
                    start=start,
                    end=end,
                    peak=t,
                    score=0.05,
                    audio_score=0.0,
                    visual_score=0.0,
                    reason="AI scan",
                )
            )
            t += step

    # Review needs peaks, not padded exports. Normalise every candidate to a
    # compact probe; otherwise the default 8s/5s padding makes neighbouring
    # short-video candidates overlap and merge into a single whole-file window.
    probes = [
        ClipWindow(
            start=max(0.0, clip.peak - 2.0),
            end=min(duration, clip.peak + 2.0),
            peak=clip.peak,
            score=clip.score,
            audio_score=clip.audio_score,
            visual_score=clip.visual_score,
            reason=clip.reason,
        )
        for clip in candidates
        if 0.0 <= clip.peak <= duration
    ]
    merged = merge_windows(
        probes,
        merge_gap=min(1.0, settings.merge_gap),
        duration=duration,
    )
    merged.sort(key=lambda clip: clip.score, reverse=True)
    merged = merged[: settings.ai_max_candidates]
    merged.sort(key=lambda clip: clip.start)
    return merged


def review_candidates(
    video: Path,
    candidates: list[ClipWindow],
    settings: DetectionSettings,
    duration: float,
    progress: ProgressFn | None = None,
) -> tuple[list[ClipWindow], list[str]]:
    if not candidates:
        return [], ["AI review found no candidate windows."]
    if not model_available(settings.ai_model):
        raise AIError(
            f"Local vision model {settings.ai_model!r} is not available. "
            f"Run: ollama pull {settings.ai_model}"
        )

    accepted: list[ClipWindow] = []
    warnings: list[str] = []
    total = len(candidates)
    for index, candidate in enumerate(candidates, start=1):
        if progress:
            progress(
                0.88 + 0.10 * (index - 1) / total,
                f"AI review {index}/{total} ({settings.ai_model})",
            )
        try:
            verdict = review_window(
                video,
                candidate.peak,
                duration,
                settings.ai_model,
                settings.ai_game,
            )
        except AIError as exc:
            warnings.append(str(exc))
            break
        if not verdict.get("highlight"):
            continue
        confidence = float(verdict.get("confidence", 0.0))
        if confidence < settings.ai_min_confidence:
            continue
        frame = int(verdict.get("best_frame", 2))
        peak = candidate.peak + (-2.0, 0.0, 2.0)[max(0, min(2, frame - 1))]
        peak = min(max(0.0, peak), max(0.0, duration - 0.05))
        start = max(0.0, peak - settings.pre)
        end = min(duration, peak + settings.post)
        if end <= start:
            continue
        category = str(verdict.get("category") or "other")
        reason = str(verdict.get("reason") or "").strip()
        blended = 0.55 * confidence + 0.45 * min(1.0, max(0.0, candidate.score))
        accepted.append(
            ClipWindow(
                start=start,
                end=end,
                peak=peak,
                score=max(0.01, min(0.99, blended)),
                audio_score=candidate.audio_score,
                visual_score=candidate.visual_score,
                reason=f"AI {category}: {reason}"[:180] if reason else f"AI {category}",
            )
        )

    if progress:
        progress(1.0, f"AI reviewed {total} candidate(s)")
    merged = merge_windows(accepted, merge_gap=settings.merge_gap, duration=duration)
    merged = [clip for clip in merged if clip.duration >= settings.min_clip]
    merged.sort(key=lambda clip: clip.score, reverse=True)
    merged = merged[: settings.max_clips]
    merged.sort(key=lambda clip: clip.start)
    if not merged and not warnings:
        warnings.append(
            "AI reviewed the candidates but found no clear highlights. "
            "Lower --ai-min-confidence or review the dry-run frames."
        )
    return merged, warnings
