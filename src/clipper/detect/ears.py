"""Local Omni audio review for highlight candidates.

Whisper is good at *what* was said, but it throws away prosody. This module
gives the Director a second pair of ears: a small local Omni model listens to
short chunks of a candidate clip and reports laughter, sarcasm, anger,
excitement, and the exact words it heard.

The Omni model is deliberately used as an *evidence source*, not as the only
judge. Its transcript is cross-checked against Whisper, so a hallucinated line
cannot invent a highlight. When the two agree, the Director can trust the tone
and use the chunk timing to tighten a clip around the real payoff.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from ..config import FFmpegBinaries
from .ai import AIError, _cache_dir, chat, ollama_status, runtime_active

OMNI_MODEL = "lfm3-omni"
OMNI_PROMPT_VERSION = "ears-v1"
CHUNK_SECONDS = 5.0
CHUNK_STEP = 2.5
MAX_CHUNKS = 24
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_TONE_SCORE = {
    "neutral": 0.0,
    "flat": 0.0,
    "playful": 0.38,
    "mocking": 0.58,
    "sarcastic": 0.62,
    "excited": 0.68,
    "angry": 0.68,
    "rage": 0.72,
    "scared": 0.42,
}
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "had", "has", "have", "he", "her", "here", "him", "his", "how", "i", "if",
    "in", "is", "it", "its", "just", "me", "my", "no", "not", "of", "on", "or",
    "our", "out", "she", "so", "that", "the", "their", "them", "then", "there",
    "they", "this", "to", "up", "was", "we", "were", "what", "when", "where",
    "which", "who", "why", "with", "you", "your", "yeah", "oh", "uh", "um",
}


@dataclass(frozen=True)
class AudioChunk:
    start: float
    end: float
    speech: str
    tone: str
    laughter: bool
    shouting: bool
    sound: str
    proof: str
    score: float
    trusted: bool
    overlap: float


@dataclass(frozen=True)
class AudioReading:
    chunks: tuple[AudioChunk, ...]
    score: float
    peak: float
    reason: str
    transcript: str
    trusted: bool
    laughter: bool
    tone: str


def omni_available(model: str = OMNI_MODEL) -> bool:
    try:
        from .llama_runtime import model_spec

        spec = model_spec(model)
        if spec is not None and not spec.audio:
            return False
    except Exception:
        pass
    if runtime_active(model):
        return True
    status = ollama_status()
    if not status.get("ok"):
        return False
    wanted = model.strip().lower()
    wanted_base, _, wanted_tag = wanted.partition(":")
    for item in status.get("models", []):
        name = str(item).lower()
        if name == wanted:
            return True
        base, _, tag = name.partition(":")
        if base == wanted_base and (not wanted_tag or wanted_tag == tag):
            return True
    return False


def _content_words(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {word.strip("'") for word in words if len(word) > 1 and word not in _STOPWORDS}


def transcript_overlap(speech: str, transcript: str) -> float:
    """How much of the Omni transcript is backed by Whisper's transcript.

    Containment is the right measure here: the Omni model often hears a short
    phrase while Whisper has the full sentence. A single common word is not
    enough to trust a line.
    """

    heard = _content_words(speech)
    if len(heard) < 2 or not transcript.strip():
        return 0.0
    known = _content_words(transcript)
    if not known:
        return 0.0
    return len(heard & known) / len(heard)


def _energy(audio: Any, start: float, end: float) -> float:
    try:
        times = audio.times
        scores = audio.scores
    except AttributeError:
        return 0.0
    if times is None or scores is None or len(times) == 0:
        return 0.0
    import numpy as np

    mask = (times >= start) & (times < end)
    if not np.any(mask):
        return 0.0
    return float(np.max(scores[mask]))


def _chunk_score(verdict: dict[str, Any], trusted: bool) -> float:
    tone = str(verdict.get("tone") or "").strip().lower()
    score = _TONE_SCORE.get(tone, 0.0)
    if bool(verdict.get("laughter")):
        score += 0.34
    if bool(verdict.get("shouting")):
        score += 0.16
    speech = str(verdict.get("speech") or "").strip()
    if speech:
        score += min(0.18, 0.025 * len(_content_words(speech)))
    score = max(0.0, min(1.0, score))
    return score if trusted else score * 0.25


def _chunk_prompt() -> str:
    return (
        "You are the audio witness for a gaming highlight editor. "
        "Listen to this 5-second clip. It may contain player voice chat, game "
        "audio, music, and sound effects. Return one compact JSON object:\n"
        '{"speech": "the exact words you hear, or empty", '
        '"tone": "neutral|playful|sarcastic|angry|excited|scared|mocking", '
        '"laughter": true|false, "shouting": true|false, '
        '"sound": "game sounds|music|speech|silence|other", '
        '"proof": "the words or sounds that prove the tone"}\n'
        "Only report what you actually hear. Do not guess and do not describe "
        "anything visual. A game announcer, a voice line, or an in-game character "
        "is not a player reaction. If speech is unclear, use an empty string."
    )


def _chunk_cache_key(video: Path, start: float, end: float, model: str) -> Path:
    try:
        mtime = video.stat().st_mtime
    except OSError:
        mtime = 0
    raw = (
        f"{video.resolve()}|{mtime}|{start:.2f}|{end:.2f}|{model}|"
        f"{OMNI_PROMPT_VERSION}"
    )
    return _cache_dir() / (hashlib.sha256(raw.encode()).hexdigest()[:24] + ".json")


def _ask_chunk(
    model: str,
    wav: Path,
    timeout: float = 120.0,
) -> dict[str, Any]:
    return chat(
        model,
        _chunk_prompt(),
        audio=wav.read_bytes(),
        timeout=timeout,
        num_predict=180,
        num_ctx=4096,
        temperature=0.0,
    )


def _slice_wav(
    wav: Path,
    start: float,
    end: float,
    output: Path,
    bins: FFmpegBinaries,
) -> Path:
    command = [
        bins.ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(wav),
        "-ss",
        f"{max(0.0, start):.3f}",
        "-t",
        f"{max(0.1, end - start):.3f}",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(output),
    ]
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_NO_WINDOW,
    )
    if proc.returncode != 0 or not output.is_file():
        detail = (proc.stderr or "").strip().splitlines()
        raise AIError(
            "Could not slice the candidate audio"
            + (f": {detail[-1]}" if detail else "")
        )
    return output


def _transcript_for(
    lines: Sequence[tuple[float, float, str]],
    start: float,
    end: float,
) -> str:
    return " / ".join(
        text for line_start, line_end, text in lines
        if line_end > start and line_start < end
    )


def _verdict_to_chunk(
    verdict: dict[str, Any],
    start: float,
    end: float,
    transcript: str,
    energy: float,
) -> AudioChunk:
    speech = str(verdict.get("speech") or "").strip()
    tone = str(verdict.get("tone") or "neutral").strip().lower()
    laughter = bool(verdict.get("laughter"))
    shouting = bool(verdict.get("shouting"))
    sound = str(verdict.get("sound") or "").strip()
    proof = str(verdict.get("proof") or "").strip()
    overlap = transcript_overlap(speech, transcript)
    words = len(_content_words(speech))
    # A laugh or shout is trustworthy when the acoustic track agrees, even if
    # the words are unclear. A tone claim needs at least two words that Whisper
    # also heard, so a hallucinated line cannot invent a reaction.
    trusted = (
        (overlap >= 0.25 and words >= 2)
        or (laughter and energy >= 0.22)
        or (shouting and energy >= 0.55)
    )
    return AudioChunk(
        start=start,
        end=end,
        speech=speech[:300],
        tone=tone[:24],
        laughter=laughter,
        shouting=shouting,
        sound=sound[:40],
        proof=proof[:300],
        score=_chunk_score(
            {
                "tone": tone,
                "laughter": laughter,
                "shouting": shouting,
                "speech": speech,
            },
            trusted,
        ),
        trusted=trusted,
        overlap=overlap,
    )


def listen_clip(
    video: Path,
    wav: Path | None,
    start: float,
    end: float,
    lines: Sequence[tuple[float, float, str]],
    audio: Any = None,
    model: str = OMNI_MODEL,
    bins: FFmpegBinaries | None = None,
    timeout: float = 120.0,
    progress: Any = None,
) -> AudioReading | None:
    """Listen to a candidate clip in short chunks and return affect evidence.

    Returns None when the Omni model or the audio track is unavailable. Callers
    must treat that as "no extra evidence", never as a reason to reject a clip.
    """

    if bins is None or wav is None or not wav.is_file() or end - start < 1.0:
        return None
    if not omni_available(model):
        return None

    step = CHUNK_STEP if end - start <= 35.0 else CHUNK_SECONDS
    spans: list[tuple[float, float]] = []
    cursor = start
    while cursor < end - 1.0 and len(spans) < MAX_CHUNKS:
        chunk_end = min(end, cursor + CHUNK_SECONDS)
        if chunk_end - cursor >= 1.0:
            spans.append((cursor, chunk_end))
        if chunk_end >= end:
            break
        cursor += step
    if not spans:
        return None

    transcript = _transcript_for(lines, start, end)
    chunks: list[AudioChunk] = []
    with tempfile.TemporaryDirectory(prefix="clipper_ears_") as raw:
        temp = Path(raw)
        for index, (chunk_start, chunk_end) in enumerate(spans):
            if progress:
                progress(
                    0.0,
                    f"AI ears: {index + 1}/{len(spans)}",
                )
            key = _chunk_cache_key(video, chunk_start, chunk_end, model)
            verdict: dict[str, Any] | None = None
            if key.is_file():
                try:
                    verdict = json.loads(key.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    verdict = None
            if verdict is None:
                chunk_wav = temp / f"chunk_{index}.wav"
                try:
                    _slice_wav(wav, chunk_start, chunk_end, chunk_wav, bins)
                    verdict = _ask_chunk(model, chunk_wav, timeout=timeout)
                except (AIError, OSError):
                    continue
                try:
                    key.write_text(
                        json.dumps(verdict, indent=2), encoding="utf-8"
                    )
                except OSError:
                    pass
            chunk_transcript = _transcript_for(
                lines, chunk_start, chunk_end
            )
            chunks.append(
                _verdict_to_chunk(
                    verdict,
                    chunk_start,
                    chunk_end,
                    chunk_transcript,
                    _energy(audio, chunk_start, chunk_end),
                )
            )

    if not chunks:
        return None
    trusted = [chunk for chunk in chunks if chunk.trusted]
    if not trusted:
        return AudioReading(
            chunks=tuple(chunks),
            score=0.0,
            peak=(start + end) / 2.0,
            reason="",
            transcript="",
            trusted=False,
            laughter=False,
            tone="",
        )
    ranked = sorted(trusted, key=lambda chunk: chunk.score, reverse=True)
    top = ranked[:3]
    score = max(0.0, min(1.0, 0.65 * top[0].score + 0.35 * (
        sum(chunk.score for chunk in top) / len(top)
    )))
    peak = (top[0].start + top[0].end) / 2.0
    if len(top) > 1:
        weight = sum(chunk.score for chunk in top) or 1.0
        peak = sum(
            ((chunk.start + chunk.end) / 2.0) * chunk.score for chunk in top
        ) / weight
    best = top[0]
    tone = best.tone if best.tone not in {"neutral", "flat"} else ""
    pieces = []
    if best.laughter:
        pieces.append("laughter")
    elif tone:
        pieces.append(tone)
    if best.speech:
        pieces.append(f'"{best.speech.strip().strip(chr(34))}"')
    elif best.proof:
        pieces.append(best.proof)
    reason = " + ".join(pieces)[:160]
    unique: list[str] = []
    for chunk in ranked:
        speech = chunk.speech.strip()
        if speech and speech not in unique:
            unique.append(speech)
    return AudioReading(
        chunks=tuple(chunks),
        score=score,
        peak=peak,
        reason=reason,
        transcript=" / ".join(unique)[:500],
        trusted=True,
        laughter=any(chunk.laughter for chunk in trusted),
        tone=tone,
    )
