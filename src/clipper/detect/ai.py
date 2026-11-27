"""Local vision-language review of highlight candidates via Ollama.

The director is Clipper's only highlight path. It looks at full-clip windows
with frames, transcript, HUD, and audio signals, then decides what to keep.
Everything runs locally.
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
from typing import Any, Callable, Sequence

import numpy as np

from ..config import DetectionSettings
from ..ffmpeg import FFmpegError, make_thumbnail
from ..gpu import VramError
from ..models import ClipWindow
from .merge import merge_windows, pick_peaks

OLLAMA_URL = os.environ.get("CLIPPER_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODEL = "qwen2.5vl:7b"
VISION_MODEL_FAMILIES = ("gemma3", "qwen2.5vl", "qwen3-vl")
_RUNTIME_SERVERS: dict[str, Any] = {}
_RUNTIME_MAIN: str | None = None
_EXTERNAL_URL = ""
_EXTERNAL_MODEL = ""


def is_supported_vision_model(name: str) -> bool:
    """True only for model families the Director is built and tested around."""

    lowered = name.strip().lower()
    if not lowered or "qwen2.5vl:3b" in lowered:
        return False
    family = lowered.split(":", 1)[0]
    return family in VISION_MODEL_FAMILIES


def num_gpu_for(model: str) -> int:
    # Full offload of the 3B Qwen vision model emits garbage tokens on some
    # CUDA setups. A partial offload is correct and still keeps most layers on
    # the GPU, which matters for 6 GB cards.
    if "qwen2.5vl:3b" in model.lower():
        return 20
    return 99
FAST_MODEL = "gemma3:4b"
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


def configure_runtime(
    settings: DetectionSettings,
    *,
    main: bool = True,
    ears: bool = True,
) -> str:
    """Start the bundled llama.cpp servers this scan needs.

    The vision model and the Omni ears model are independent. That lets a
    strong vision model (Ollama) work with the fast LFM3 ears model, or lets two
    GGUF models run side by side when there is enough VRAM. Low-power mode uses
    the ``main`` and ``ears`` switches to keep only one of them resident.
    Returns ``llamacpp`` when the *vision* model runs through the runtime.
    """

    global _RUNTIME_SERVERS, _RUNTIME_MAIN, _EXTERNAL_URL, _EXTERNAL_MODEL
    try:
        from .llama_runtime import (
            model_ready,
            model_spec,
            runtime_ready,
            start_server,
            stop_server,
        )
    except Exception:
        _RUNTIME_SERVERS = {}
        _RUNTIME_MAIN = None
        return "ollama"
    external = main and settings.ai_model.startswith("server:")
    _EXTERNAL_MODEL = settings.ai_model if external else ""
    _EXTERNAL_URL = settings.ai_server_url.strip() if external else ""
    if external and not _EXTERNAL_URL:
        raise AIError("The local server URL is missing. Reconnect it in AI Setup.")
    wants_llama = settings.ai_runtime in {"auto", "llamacpp"}
    if not wants_llama and not external:
        stop_server()
        _RUNTIME_SERVERS = {}
        _RUNTIME_MAIN = None
        return "ollama"
    main_spec = model_spec(settings.ai_model) if main and not external else None
    ears_spec = (
        model_spec(settings.ai_ears_model) if settings.ai_ears and ears else None
    )
    if ears_spec is not None and not ears_spec.audio:
        from .llama_runtime import LFM3_OMNI_2B

        ears_spec = LFM3_OMNI_2B
    if ears_spec is not None and ears_spec.id == (main_spec.id if main_spec else ""):
        ears_spec = None
    needed = {
        spec.id
        for spec in (main_spec, ears_spec)
        if spec is not None and spec.engine == "llamacpp"
    }
    for stale in list(_RUNTIME_SERVERS):
        if stale not in needed:
            stop_server(stale)
            _RUNTIME_SERVERS.pop(stale, None)

    def run(spec, required: bool = False) -> bool:
        if (
            not wants_llama
            or spec is None
            or spec.engine != "llamacpp"
            or not runtime_ready()
            or not model_ready(spec)
        ):
            return False
        try:
            _RUNTIME_SERVERS[spec.id] = start_server(spec)
            return True
        except VramError:
            _RUNTIME_SERVERS.pop(spec.id, None)
            raise
        except Exception:
            _RUNTIME_SERVERS.pop(spec.id, None)
            if required and settings.ai_runtime == "llamacpp":
                raise
            return False

    try:
        main_started = run(main_spec, required=main and not external)
    except VramError:
        _RUNTIME_MAIN = None
        raise
    run(ears_spec)
    _RUNTIME_MAIN = main_spec.id if main_started and main_spec else None
    if (
        main
        and not external
        and settings.ai_runtime == "llamacpp"
        and not main_started
    ):
        stop_server()
        _RUNTIME_SERVERS = {}
        raise AIError(
            f"{settings.ai_model!r} is not downloaded for the bundled runtime."
        )
    if external:
        return "server"
    return "llamacpp" if main_started else "ollama"


def runtime_name() -> str:
    if _EXTERNAL_MODEL:
        return "server"
    return "llamacpp" if _RUNTIME_MAIN is not None else "ollama"


def _runtime_key(model: str) -> str:
    try:
        from .llama_runtime import model_spec

        spec = model_spec(model)
        if spec is not None:
            return spec.id
    except Exception:
        pass
    return model.strip().lower()


def runtime_active(model: str) -> bool:
    return _runtime_key(model) in _RUNTIME_SERVERS


def stop_runtime() -> None:
    global _RUNTIME_SERVERS, _RUNTIME_MAIN, _EXTERNAL_URL, _EXTERNAL_MODEL
    _EXTERNAL_URL = ""
    _EXTERNAL_MODEL = ""
    if not _RUNTIME_SERVERS:
        _RUNTIME_MAIN = None
        return
    try:
        from .llama_runtime import stop_server

        stop_server()
    except Exception:
        pass
    _RUNTIME_SERVERS = {}
    _RUNTIME_MAIN = None


def _image_bytes(value: str | bytes) -> bytes:
    if isinstance(value, bytes):
        return value
    return base64.b64decode(value)


def chat(
    model: str,
    prompt: str,
    *,
    images: Sequence[str | bytes] = (),
    audio: bytes | None = None,
    timeout: float = 300.0,
    num_predict: int = 700,
    num_ctx: int = 4096,
    temperature: float = 0.1,
) -> dict[str, Any]:
    """Ask the active local model and parse its JSON answer.

    The same call works for Ollama vision models and the bundled llama.cpp
    omni model. Audio is sent through ``input_audio`` on llama.cpp and through
    the ``images`` list on Ollama, which is where its audio models expect WAV
    bytes.
    """

    if _EXTERNAL_URL and model == _EXTERNAL_MODEL:
        from .llama_runtime import openai_chat_base

        try:
            text = openai_chat_base(
                _EXTERNAL_URL,
                model.split(":", 1)[1] if ":" in model else model,
                prompt,
                images=[_image_bytes(value) for value in images],
                audio=audio,
                max_tokens=num_predict,
                timeout=timeout,
                json_mode=True,
                label="Local server",
            )
        except Exception as exc:
            raise AIError(f"Local server model failed: {exc}") from exc
        return _parse_json(text)

    server = _RUNTIME_SERVERS.get(_runtime_key(model))
    if server is not None:
        from .llama_runtime import openai_chat

        try:
            text = openai_chat(
                server,
                prompt,
                images=[_image_bytes(value) for value in images],
                audio=audio,
                max_tokens=num_predict,
                timeout=timeout,
                json_mode=True,
            )
        except Exception as exc:
            raise AIError(f"Local omni model failed: {exc}") from exc
        return _parse_json(text)

    payload_images = [
        value
        if isinstance(value, str)
        else base64.b64encode(value).decode("ascii")
        for value in images
    ]
    if audio is not None:
        payload_images.append(base64.b64encode(audio).decode("ascii"))
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                **({"images": payload_images} if payload_images else {}),
            }
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
            "num_ctx": num_ctx,
            "num_gpu": num_gpu_for(model),
            "repeat_penalty": 1.25,
            "repeat_last_n": 64,
        },
        "keep_alive": "10m",
    }
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
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AIError(f"Ollama returned malformed JSON: {exc}") from exc
    except Exception as exc:
        raise AIError(f"Ollama request failed: {exc}") from exc
    if not isinstance(data, dict):
        raise AIError("Ollama returned an unexpected response")
    message = data.get("message")
    if not isinstance(message, dict):
        raise AIError("Ollama returned no message object")
    content = str(message.get("content") or "").strip()
    if not content:
        raise AIError("The local model returned an empty response")
    return _parse_json(content)


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
                "num_gpu": num_gpu_for(model),
                "repeat_penalty": 1.25,
                "repeat_last_n": 64,
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
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AIError(f"Ollama returned malformed JSON: {exc}") from exc
        except Exception as exc:
            raise AIError(f"Ollama request failed: {exc}") from exc

    if not isinstance(data, dict):
        raise AIError("Ollama returned an unexpected response")
    message = data.get("message")
    if not isinstance(message, dict):
        message = {}
    content = str(message.get("content") or "")
    if not content:
        thinking = str(message.get("thinking") or "")
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
            if "malformed json" in str(exc).lower():
                continue
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
