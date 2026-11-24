"""Whole-clip AI director.

The older AI pass reviews peaks found by audio/motion. This pass watches the
whole clip in short windows, transcribes the audio locally with Whisper, and
then asks the local model to choose the actual story beats: a funny exchange,
a rage, a clutch, a round win, or a genuinely unusual moment. It can keep a
54-second interaction instead of forcing it into a 6-second peak window.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

from ..config import DetectionSettings
from ..ffmpeg import FFmpegBinaries, make_thumbnail
from ..models import ClipWindow
from .ai import AIError, AI_CROP, OLLAMA_URL, _parse_json, model_available
from .audio import ScoreTrack

PROMPT_VERSION = "director-v2"
ProgressFn = Callable[[float, str], None]
MAX_SEGMENT_SECONDS = 120.0
HUMOR_CUES = re.compile(
    r"\b(fuck|fucking|shit|bitch|ass|damn|bro|dude|bruh|lmao|lol|joke|joking|"
    r"troll|trolling|funny|haha|laugh|laughed|wtf|no way|what the|why would|"
    r"stop|serious|holy|clip that|did you see|can't say)\b",
    re.IGNORECASE,
)


@dataclass
class StoryWindow:
    start: float
    end: float
    transcript: str
    audio_label: str
    visual: dict[str, Any]


@dataclass
class TranscriptLine:
    start: float
    end: float
    text: str

    def label(self) -> str:
        return f"[{self.start:.1f}-{self.end:.1f}] {self.text}"


def _cache_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
    path = base / "Clipper" / "ai-cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_key(video: Path, tag: str, model: str) -> Path:
    try:
        mtime = video.stat().st_mtime
    except OSError:
        mtime = 0
    raw = f"{video.resolve()}|{mtime}|{tag}|{model}|{PROMPT_VERSION}"
    return _cache_dir() / (hashlib.sha256(raw.encode()).hexdigest()[:24] + ".json")


def _ollama_chat(
    model: str,
    prompt: str,
    *,
    images: list[str] | None = None,
    timeout: float = 300.0,
    num_predict: int = 700,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                **({"images": images} if images else {}),
            }
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.1,
            "num_predict": num_predict,
            "num_ctx": 8192,
            "num_gpu": 99,
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
    except Exception as exc:
        raise AIError(f"Ollama request failed: {exc}") from exc
    content = str((data.get("message") or {}).get("content") or "").strip()
    if not content:
        raise AIError("The local model returned an empty response")
    return _parse_json(content)


def transcribe_audio(
    wav: Path,
    *,
    model_name: str = "base.en",
    threads: int = 6,
) -> list[TranscriptLine]:
    """Transcribe the extracted 16kHz WAV locally with faster-whisper."""

    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
    os.environ.setdefault("HF_HOME", str(base / "Clipper" / "models" / "huggingface"))
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise AIError(
            "Speech transcription needs faster-whisper. "
            "Install the desktop extra or run: pip install faster-whisper"
        ) from exc

    model = WhisperModel(
        model_name,
        device="cpu",
        compute_type="int8",
        cpu_threads=max(1, min(8, threads or 6)),
    )
    segments, _info = model.transcribe(
        str(wav),
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
        language="en",
    )
    lines: list[TranscriptLine] = []
    for row in segments:
        text = str(row.text or "").strip()
        if not text:
            continue
        if len(text) <= 2 and text.lower().strip(".,!?") in {"a", "ah", "uh", "hmm"}:
            continue
        if float(getattr(row, "no_speech_prob", 0.0) or 0.0) > 0.75:
            continue
        lines.append(TranscriptLine(float(row.start), float(row.end), text))
    return lines


def _window_size(duration: float) -> float:
    if duration <= 180:
        return 15.0
    if duration <= 600:
        return 20.0
    return max(30.0, duration / 30.0)


def _audio_label(audio: ScoreTrack | None, start: float, end: float) -> str:
    if audio is None or audio.times.size == 0:
        return "unknown"
    mask = (audio.times >= start) & (audio.times < end)
    if not np.any(mask):
        return "low"
    peak = float(audio.scores[mask].max(initial=0.0))
    mean = float(audio.scores[mask].mean())
    level = 0.65 * peak + 0.35 * mean
    if level >= 0.65:
        return "high"
    if level >= 0.30:
        return "medium"
    return "low"


def _window_transcript(lines: list[TranscriptLine], start: float, end: float) -> str:
    picked = [
        line.text
        for line in lines
        if line.end >= start and line.start < end
    ]
    return " / ".join(picked)[:600]


def _contact_sheet(
    video: Path,
    start: float,
    end: float,
    output: Path,
    bins: FFmpegBinaries,
) -> Path:
    span = max(0.1, end - start)
    offsets = (0.08, 0.35, 0.65, 0.92)
    tiles: list[np.ndarray] = []
    with tempfile.TemporaryDirectory(prefix="clipper_story_") as raw:
        temp = Path(raw)
        for index, offset in enumerate(offsets):
            timestamp = min(end - 0.05, start + span * offset)
            jpg = temp / f"frame_{index}.jpg"
            make_thumbnail(video, timestamp, jpg, width=320, bins=bins, crop=AI_CROP)
            image = cv2.imread(str(jpg))
            if image is None:
                image = np.zeros((180, 320, 3), dtype=np.uint8)
            cv2.putText(
                image,
                f"{timestamp:.1f}s",
                (8, 22),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
            tiles.append(image)
    top = np.hstack([tiles[0], tiles[1]])
    bottom = np.hstack([tiles[2], tiles[3]])
    sheet = np.vstack([top, bottom])
    cv2.imwrite(str(output), sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return output


def _window_prompt(window: StoryWindow) -> str:
    return f"""You are reviewing one window of a gaming clip for a highlight editor.
Window: {window.start:.1f}s to {window.end:.1f}s.
Audio energy: {window.audio_label}.
Transcript or game audio in this window: {window.transcript or "(none)"}
The image is four chronological frames, left to right then top to bottom.
The timestamps are drawn on each frame.

Decide whether this window contains something worth keeping in a highlight reel:
funny banter or trolling, a genuine reaction, rage, a clutch, a multikill,
a round result, a spike/objective play, or a clearly unusual moment.
Buy phase, menus, loading screens, walking, and ordinary filler are not interesting.
Ordinary game callouts and strategy talk ("enemy remaining", "reloading", "B site")
are NOT funny banter. Banter requires people joking, teasing, laughing, or reacting.
Ignore game voice lines when judging whether people are being funny.

Scoring: 0.0 filler/menu, 0.3-0.5 ordinary gameplay, 0.6-0.8 notable,
0.8-1.0 must keep. Be conservative. Do not invent audio or events.
Return JSON only:
{{"interesting": true|false, "score": 0.0, "kind": "funny|banter|rage|clutch|multikill|round|reaction|gameplay|filler", "summary": "one short sentence", "evidence": "what you saw or heard"}}"""


def _review_window(
    video: Path,
    window: StoryWindow,
    model: str,
    bins: FFmpegBinaries,
) -> dict[str, Any]:
    key = _cache_key(video, f"window:{window.start:.2f}-{window.end:.2f}", model)
    if key.is_file():
        try:
            return json.loads(key.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    with tempfile.TemporaryDirectory(prefix="clipper_story_") as raw:
        sheet = Path(raw) / "sheet.jpg"
        _contact_sheet(video, window.start, window.end, sheet, bins)
        import base64

        encoded = base64.b64encode(sheet.read_bytes()).decode("ascii")
        verdict = _ollama_chat(
            model,
            _window_prompt(window),
            images=[encoded],
            num_predict=180,
        )
    interesting = verdict.get("interesting")
    if isinstance(interesting, str):
        interesting = interesting.lower() == "true"
    try:
        score = float(verdict.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    result = {
        "interesting": bool(interesting),
        "score": max(0.0, min(1.0, score)),
        "kind": str(verdict.get("kind") or "filler")[:24],
        "summary": str(verdict.get("summary") or "")[:240],
        "evidence": str(verdict.get("evidence") or "")[:240],
    }
    try:
        key.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except OSError:
        pass
    return result


def _audio_rank(label: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(label, 0)


def _segments_from_windows(
    windows: list[StoryWindow],
    lines: list[TranscriptLine],
    duration: float,
    settings: DetectionSettings,
    audio: ScoreTrack | None = None,
) -> list[ClipWindow]:
    threshold = max(0.45, min(0.95, settings.ai_min_confidence))
    clusters: list[list[StoryWindow]] = []
    for window in windows:
        keep = bool(window.visual.get("interesting")) and float(
            window.visual.get("score", 0.0)
        ) >= threshold
        if not keep:
            continue
        if clusters and window.start - clusters[-1][-1].end <= 0.5:
            clusters[-1].append(window)
        else:
            clusters.append([window])

    clips: list[ClipWindow] = []
    for cluster in clusters:
        best = max(
            cluster,
            key=lambda item: (
                float(item.visual.get("score", 0.0)),
                _audio_rank(item.audio_label),
                item.start,
            ),
        )
        start = cluster[0].start
        end = cluster[-1].end
        kind = str(best.visual.get("kind") or "gameplay").split("|")[0].strip() or "gameplay"
        peak = (best.start + best.end) / 2
        if kind in {"funny", "banter"}:
            spoken = " ".join(
                line.text
                for line in lines
                if line.end > start + 0.2 and line.start < end - 0.2
            )
            if not HUMOR_CUES.search(spoken):
                # Game voice lines and tactical callouts are transcribed the
                # same way as people talking. Do not sell a strategy chat as a
                # funny clip unless there is an actual humour cue.
                continue
        # For a conversation, trim to the spoken interaction instead of the
        # arbitrary window boundary. Keep a little breath before/after.
        if kind in {"funny", "banter", "reaction", "rage"}:
            spoken_lines = [
                line
                for line in lines
                if line.end > start + 0.2 and line.start < end - 0.2
            ]
            if spoken_lines:
                start = max(start, spoken_lines[0].start - 1.0)
                end = min(end, spoken_lines[-1].end + 1.0)
                cue_lines = [line for line in spoken_lines if HUMOR_CUES.search(line.text)]
                if cue_lines:
                    peak = (cue_lines[-1].start + cue_lines[-1].end) / 2
        if end - start < 4.0:
            middle = (best.start + best.end) / 2
            start = max(0.0, middle - 2.5)
            end = min(duration, middle + 2.5)
        if end - start > MAX_SEGMENT_SECONDS:
            middle = (best.start + best.end) / 2
            start = max(cluster[0].start, middle - MAX_SEGMENT_SECONDS / 2)
            end = min(cluster[-1].end, start + MAX_SEGMENT_SECONDS)
        if end <= start:
            continue
        summary = str(best.visual.get("summary") or "").strip()
        if not summary:
            summary = next(
                (
                    line.text
                    for line in lines
                    if line.end > start and line.start < end
                ),
                "notable moment",
            )
        clips.append(
            ClipWindow(
                start=max(0.0, start),
                end=min(duration, end),
                peak=min(duration - 0.05, max(0.0, peak)),
                score=max(0.05, min(0.99, float(best.visual.get("score", 0.7)))),
                audio_score=0.0,
                visual_score=0.0,
                reason=f"AI {kind}: {summary}"[:180],
            )
        )
    return _merge(clips)


def _merge(clips: list[ClipWindow]) -> list[ClipWindow]:
    clips.sort(key=lambda clip: clip.start)
    merged: list[ClipWindow] = []
    for clip in clips:
        if merged and clip.start - merged[-1].end <= 1.0:
            last = merged[-1]
            best = last if last.score >= clip.score else clip
            merged[-1] = ClipWindow(
                start=last.start,
                end=max(last.end, clip.end),
                peak=best.peak,
                score=max(last.score, clip.score),
                reason=best.reason,
            )
        else:
            merged.append(clip)
    return merged


def direct_clip(
    video: Path,
    duration: float,
    settings: DetectionSettings,
    wav: Path | None,
    audio: ScoreTrack | None,
    bins: FFmpegBinaries,
    progress: ProgressFn | None = None,
) -> tuple[list[ClipWindow], list[str]]:
    if not model_available(settings.ai_model):
        raise AIError(
            f"Local vision model {settings.ai_model!r} is not available. "
            f"Run: ollama pull {settings.ai_model}"
        )

    warnings: list[str] = []
    lines: list[TranscriptLine] = []
    if wav is not None and wav.is_file():
        if progress:
            progress(0.86, "AI director: transcribing audio (local Whisper)")
        try:
            lines = transcribe_audio(wav, threads=settings.threads)
            lines = [line for line in lines if line.start < duration]
            if not lines:
                warnings.append("AI director: no speech found; using visual/audio context only.")
        except AIError as exc:
            warnings.append(f"AI director transcription skipped: {exc}")
    else:
        warnings.append("AI director: no audio track to transcribe.")

    size = _window_size(duration)
    windows: list[StoryWindow] = []
    count = max(1, int(np.ceil(duration / size)))
    for index in range(count):
        start = index * size
        end = min(duration, start + size)
        if end - start < 1.0:
            continue
        window = StoryWindow(
            start=start,
            end=end,
            transcript=_window_transcript(lines, start, end),
            audio_label=_audio_label(audio, start, end),
            visual={},
        )
        if progress:
            progress(
                0.87 + 0.08 * index / max(1, count),
                f"AI director: watching {index + 1}/{count}",
            )
        try:
            window.visual = _review_window(video, window, settings.ai_model, bins)
        except AIError as exc:
            warnings.append(f"AI director window failed: {exc}")
            window.visual = {
                "interesting": False,
                "score": 0.0,
                "kind": "filler",
                "summary": "",
                "evidence": "",
            }
        windows.append(window)

    if progress:
        progress(0.96, "AI director: choosing the story")
    clips = _segments_from_windows(windows, lines, duration, settings, audio=audio)
    if not clips:
        warnings.append("AI director found no story beats in this clip.")
    clips = [clip for clip in _merge(clips) if clip.duration >= settings.min_clip]
    clips.sort(key=lambda clip: clip.score, reverse=True)
    clips = clips[: settings.max_clips]
    clips.sort(key=lambda clip: clip.start)
    if progress:
        progress(0.99, f"AI director: {len(clips)} segment(s)")
    return clips, warnings
