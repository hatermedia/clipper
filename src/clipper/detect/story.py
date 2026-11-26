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
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..config import DetectionSettings
from ..ffmpeg import FFmpegBinaries, FFmpegError, make_thumbnail
from ..models import ClipWindow
from .ai import AIError, OLLAMA_URL, _parse_json, model_available, num_gpu_for, unload_model
from .audio import ScoreTrack
from .hud import HudLine, HudReading, chat_cue, display_text, event_lines, read_hud
from .signals import SIGNAL_VERSION, WindowSignal, analyze_signals, tag_transcript, window_signal

PROMPT_VERSION = "director-v7"
ProgressFn = Callable[[float, str], None]
MAX_SEGMENT_SECONDS = 120.0
SOCIAL_MAX_SECONDS = 45.0
ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
BUNDLED_WHISPER = ASSET_DIR / "models" / "base.en"
HUD_KIND_ORDER = ("round", "goal", "multikill", "clutch", "save", "demo")
SOCIAL_KINDS = {"funny", "banter", "reaction", "rage", "hype"}
KIND_ALIASES = {
    "ace": "multikill",
    "doublekill": "multikill",
    "triplekill": "multikill",
    "quadrakill": "multikill",
    "pentakill": "multikill",
    "roundwin": "round",
    "won": "round",
    "win": "round",
    "victory": "round",
    "loss": "round",
    "defeat": "round",
    "chaos": "hype",
}


def _window_kind(window: StoryWindow) -> str:
    kind = (
        str(window.visual.get("kind") or "gameplay")
        .split("|")[0]
        .strip()
        .lower()
        or "gameplay"
    )
    return KIND_ALIASES.get(kind, kind)
HUMOR_CUES = re.compile(
    r"\b(fuck|fucking|shit|bitch|ass|damn|bro|dude|bruh|lmao|lol|joke|joking|"
    r"troll|trolling|funny|haha|laugh|laughed|scream|screaming|yell|yelling|"
    r"rage|angry|cry|crying|wtf|no way|no no|oh my|what the|why would|"
    r"stop|serious|seriously|holy|clip that|clip it|did you see|can't say|"
    r"cannot say|wow|crazy|insane|unbelievable|kidding|my god|jesus|"
    r"nice one|great job|well done)\b",
    re.IGNORECASE,
)

# Concrete, observable game events. The VLM is allowed to be unsure, but a
# gameplay clip must name the HUD/event that proves it. This is what stops
# "player executes a clutch move" from becoming a posted clip.
_EVIDENCE_RULES = {
    "multikill": re.compile(
        r"kill ?feed|killfeed|\bace\b|double kill|triple kill|quadra|penta|"
        r"\b[2345] kills?\b|two kills|three kills|four kills|five kills",
        re.IGNORECASE,
    ),
    "goal": re.compile(r"\bgoal\b|goal line|score|explosion|ball", re.IGNORECASE),
    "round": re.compile(
        r"banner|\bwon\b|\blost\b|round (win|loss|result)|spike|defus|plant|"
        r"score|match point",
        re.IGNORECASE,
    ),
    "clutch": re.compile(
        r"kill ?feed|killfeed|banner|round|last (enemy|opponent|man)|1v\d|"
        r"clutch|defus|plant|ace",
        re.IGNORECASE,
    ),
    "save": re.compile(r"\bsave\b|\bgoal\b|ball|shot", re.IGNORECASE),
    "demo": re.compile(r"\bdemo\b|explosion|destroy", re.IGNORECASE),
}


def _evidence_supports(kind: str, evidence: str) -> bool:
    rule = _EVIDENCE_RULES.get(kind)
    if rule is None:
        return bool(evidence.strip())
    return bool(rule.search(evidence))


GAME_GUIDANCE = {
    "rocket league": (
        "This is Rocket League. Strong highlights: goals, aerial goals, redirects, "
        "bicycle/ceiling shots, saves, assists, passing plays, demos, kickoff goals, "
        "overtime and 0-second goals, and a visible score change. Ordinary driving, "
        "boost pickups, rotation, and kickoff setup are filler. A late-night 'fakes' "
        "or whiff chain can be funny when the audio/banter supports it."
    ),
    "mimesis": (
        "This is Mimesis, a social/party horror game. Prioritise human reactions: "
        "screaming, laughter, trolling, betrayal, fake-outs, prop chases, and friend "
        "banter. The visuals may be dark or ambiguous, so the transcript is the main "
        "signal. Quiet walking and ordinary exploration are filler."
    ),
    "valorant": (
        "This is Valorant. Strong highlights: kill-feed entries, multikills, aces, "
        "clutches, round wins, spike plants/defuses, and clear firefights. Tactical "
        "callouts and buy-phase talk are filler unless people are genuinely joking. "
        "Read the kill feed and round banner when visible."
    ),
    "apex legends": (
        "This is Apex Legends. Strong highlights: squad wipes, knocks, clutches, "
        "revives, third parties, big damage, and genuine reactions. Looting and "
        "rotating are filler."
    ),
    "counter-strike 2": (
        "This is Counter-Strike 2. Strong highlights: multikills, aces, clutches, "
        "bomb plants/defuses, round wins, and clear firefights. Buy phase and "
        "ordinary rotations are filler."
    ),
    "arc raiders": (
        "This is Arc Raiders. Strong highlights: extraction fights, downed and "
        "revived teammates, loot discoveries, tense escapes, and genuine reactions. "
        "Ordinary looting and traversal are filler."
    ),
    "chained together": (
        "This is Chained Together, a co-op climbing game. Strong highlights: falls, "
        "near-misses, chain saves, rage, laughter, and friend banter. Ordinary "
        "climbing is filler unless someone is clearly reacting."
    ),
    "destiny 2": (
        "This is Destiny 2. Strong highlights: raid and dungeon clears, boss damage "
        "phases, Crucible multikills, clutch revives, exotic drops, and genuine "
        "fireteam reactions. Routine patrol and inventory time are filler."
    ),
    "forza horizon 5": (
        "This is Forza Horizon 5. Strong highlights: race wins, drift chains, big "
        "jumps, near-misses, skill chains, and visible crashes. Ordinary driving "
        "and menu time are filler."
    ),
    "garry's mod": (
        "This is Garry's Mod. Strong highlights: sandbox chaos, prop hunts, funny "
        "physics, trolling, betrayal, and friend banter. Quiet building and menu "
        "time are filler."
    ),
    "peak": (
        "This is PEAK, a co-op climbing game. Strong highlights: falls, rescues, "
        "scary moments, exhaustion, rage, laughter, and team banter. Ordinary "
        "climbing is filler unless someone reacts."
    ),
    "satisfactory": (
        "This is Satisfactory. Strong highlights: factory milestones, big builds, "
        "train or conveyor chaos, unexpected deaths, and genuine reactions. "
        "Ordinary mining and menu time are filler."
    ),
    "muck": (
        "This is Muck, a survival co-op game. Strong highlights: deaths, boss "
        "fights, loot finds, betrayal, panic, and friend banter. Ordinary "
        "resource gathering is filler."
    ),
    "fivem": (
        "This is FiveM/GTA roleplay. Strong highlights: funny interactions, police "
        "chases, betrayals, crashes, and character banter. Driving without a "
        "reaction and menu time are filler."
    ),
    "warframe": (
        "This is Warframe. Strong highlights: mission clears, boss kills, rare "
        "drops, clutch revives, and genuine reactions. Ordinary traversal and "
        "inventory time are filler."
    ),
    "social": (
        "This is desktop/social footage (chat, Omegle, trolling, browsing), not a "
        "game. Ignore game HUD, score, kill feed, and gameplay logic. Strong "
        "highlights: jokes, trolling, reactions, banter, awkward or funny "
        "exchanges, and visible human responses. Silence, menus, typing, and "
        "ordinary browsing are filler."
    ),
}


def _game_guidance(game: str) -> str:
    key = game.strip().lower()
    for name, text in GAME_GUIDANCE.items():
        if name in key:
            return text
    return (
        "Use the visible action, score, HUD, and transcript. A highlight is a clear "
        "goal, kill, clutch, round result, genuine reaction, or funny interaction. "
        "Ordinary traversal and menu time are filler."
    )


@dataclass
class StoryWindow:
    start: float
    end: float
    transcript: str
    audio_label: str
    visual: dict[str, Any]
    signals: WindowSignal | None = None


@dataclass
class TranscriptLine:
    start: float
    end: float
    text: str
    tags: str = ""

    def label(self) -> str:
        if self.tags:
            return f"[{self.start:.1f}-{self.end:.1f} | {self.tags}] {self.text}"
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
    raw = f"{video.resolve()}|{mtime}|{tag}|{model}|{PROMPT_VERSION}|{SIGNAL_VERSION}"
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
            "num_ctx": 4096,
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


def transcribe_audio(
    wav: Path,
    *,
    model_name: str = "base.en",
    threads: int = 6,
) -> list[TranscriptLine]:
    """Transcribe the extracted 16kHz WAV locally with faster-whisper."""

    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
    download_root = base / "Clipper" / "models" / "huggingface"
    os.environ.setdefault("HF_HOME", str(download_root))
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise AIError(
            "Speech transcription needs faster-whisper. "
            "Install the desktop extra or run: pip install faster-whisper"
        ) from exc

    bundled_override = os.environ.get("CLIPPER_WHISPER_MODEL")
    bundled = Path(bundled_override).expanduser() if bundled_override else BUNDLED_WHISPER
    local_model = (bundled / "model.bin").is_file()
    model = WhisperModel(
        str(bundled) if local_model else model_name,
        device="cpu",
        compute_type="int8",
        cpu_threads=max(1, min(8, threads or 6)),
        download_root=str(download_root),
        local_files_only=local_model,
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
            image = None
            for candidate in (timestamp, max(start, timestamp - 0.5)):
                try:
                    make_thumbnail(
                        video, candidate, jpg, width=480, bins=bins, crop=None
                    )
                except (FFmpegError, OSError):
                    continue
                image = cv2.imread(str(jpg))
                if image is not None:
                    timestamp = candidate
                    break
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


def _window_prompt(window: StoryWindow, game: str) -> str:
    social = game.strip().lower() in {"social", "desktop", "omegle", "ome.tv"}
    social_note = (
        "This is social/desktop footage, not a game. There may be no HUD or game "
        "events. Prioritise human jokes, trolling, reactions, and banter; ignore "
        "the gameplay category below."
        if social
        else ""
    )
    return f"""You are the strict highlight editor for a gaming channel.
Game: {game or "generic"}.
{social_note}
{_game_guidance(game)}
Window: {window.start:.1f}s to {window.end:.1f}s.
Audio energy: {window.audio_label}.
Transcript or game audio in this window: {window.transcript or "(none)"}
Acoustic/motion evidence for this window:
{window.signals.prompt_text() if window.signals else "(none)"}
Only cite signal tags that literally appear in that evidence line. If it says
"(no strong acoustic or motion signals)", do not claim LAUGH, JERK, or LOUD.
Audio energy high/medium/low is not a signal tag.
The image is four chronological FULL frames, including the HUD, left to right then
top to bottom. The timestamps are drawn on each frame. Read the kill feed, score,
and round banner when they are visible.

Keep this window ONLY for one of these reasons:
1. Social: a person is joking, teasing, trolling, raging, laughing, or reacting.
   Evidence must quote their actual words from the transcript. Game voice lines,
   tactical callouts, and strategy talk do NOT count as banter.
2. Gameplay: a concrete result is visible. Name it and its timestamp: a kill-feed
   entry, ace/multikill, WON/LOST banner, score change, goal explosion, save,
   spike plant/defuse, or demo.
3. Hype/chaos: use the acoustic/motion evidence. A high-energy human reaction can
   be kind="hype" with NO HUD event when at least two independent signals agree:
   LAUGH + JERK, LAUGH + LOUD, or LOUD + FAST + JERK. Pure laughter may have no
   transcript words; quote the signal tags in that case. Explosions and scene cuts
   can produce LOUD or JERK alone: never call those hype without LAUGH or a real
   excited human quote.
4. A clearly unusual visible event that a viewer would react to.

Reject buy phase, menus, loading, walking, rotations, looting, ordinary fights,
and any "player reacts" claim without a quoted human line. Never guess an event
that happens off-screen or between frames. If you cannot name the exact evidence,
set interesting to false. Vague summaries like "player executes a clutch move"
are not evidence.
Scoring: 0.0 filler/menu, 0.3-0.5 ordinary gameplay, 0.6-0.8 notable with concrete
evidence, 0.8-1.0 must keep. Be conservative.
Return JSON only:
{{"interesting": true|false, "score": 0.0, "kind": "funny|banter|rage|hype|clutch|multikill|goal|round|reaction|gameplay|filler", "summary": "one short sentence", "evidence": "timestamp + exact HUD text, visible event, human quote, or signal tags"}}"""


def _review_window(
    video: Path,
    window: StoryWindow,
    model: str,
    bins: FFmpegBinaries,
    game: str,
) -> dict[str, Any]:
    key = _cache_key(video, f"window:{window.start:.2f}-{window.end:.2f}:{game.lower()}", model)
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
            _window_prompt(window, game),
            images=[encoded],
            num_predict=360 if "7b" in model.lower() else 240,
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
    hud_reader: Callable[[float, float], HudReading] | None = None,
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
        ranked = sorted(
            cluster,
            key=lambda item: (
                float(item.visual.get("score", 0.0)),
                _audio_rank(item.audio_label),
                item.start,
            ),
            reverse=True,
        )
        chosen: StoryWindow | None = None
        chosen_kind = ""
        chosen_signal: WindowSignal | None = None
        hud_hits: list[HudLine] = []
        chat_line: HudLine | None = None

        # Verify in strict priority order:
        # 1. concrete gameplay HUD events
        # 2. HUD events inside a window the VLM called social/hype
        # 3. strong acoustic/motion agreement
        # 4. transcript/chat humor cues
        gameplay = [
            window for window in ranked if _window_kind(window) not in SOCIAL_KINDS
        ]
        social = [
            window for window in ranked if _window_kind(window) in SOCIAL_KINDS
        ]
        readings: dict[tuple[float, float], HudReading | None] = {}

        def read_candidate(candidate: StoryWindow) -> HudReading | None:
            key = (round(candidate.start, 3), round(candidate.end, 3))
            if key not in readings and hud_reader is not None:
                readings[key] = hud_reader(candidate.start, candidate.end)
            return readings.get(key)

        for candidate in gameplay:
            candidate_kind = _window_kind(candidate)
            candidate_evidence = str(candidate.visual.get("evidence") or "").strip()
            checked = read_candidate(candidate)
            if checked is not None and checked.available:
                hits = event_lines(candidate_kind, checked.lines)
                if not hits:
                    for alt in HUD_KIND_ORDER:
                        hits = event_lines(alt, checked.lines)
                        if hits:
                            candidate_kind = alt
                            break
                if hits:
                    chosen = candidate
                    chosen_kind = candidate_kind
                    hud_hits = hits
                    break
                continue
            if not _evidence_supports(candidate_kind, candidate_evidence):
                continue
            chosen = candidate
            chosen_kind = candidate_kind
            break

        if chosen is None:
            for candidate in social:
                checked = read_candidate(candidate)
                if checked is None or not checked.available:
                    continue
                for alt in HUD_KIND_ORDER:
                    hits = event_lines(alt, checked.lines)
                    if hits:
                        chosen = candidate
                        chosen_kind = alt
                        chosen_signal = candidate.signals
                        hud_hits = hits
                        break
                if chosen is not None:
                    break

        if chosen is None:
            for candidate in social:
                if candidate.signals is not None and candidate.signals.agreement():
                    chosen = candidate
                    chosen_kind = "hype"
                    chosen_signal = candidate.signals
                    break

        if chosen is None:
            for candidate in social:
                candidate_kind = _window_kind(candidate)
                if candidate_kind == "hype":
                    # Hype must be earned by real signal agreement, never by a
                    # quick-chat line or a flat transcript phrase.
                    continue
                candidate_lines = [
                    line
                    for line in lines
                    if line.end > candidate.start + 0.2
                    and line.start < candidate.end - 0.2
                ]
                if any(HUMOR_CUES.search(line.text) for line in candidate_lines):
                    chosen = candidate
                    chosen_kind = candidate_kind
                    chosen_signal = candidate.signals
                    break
                checked = read_candidate(candidate)
                if checked is not None and checked.available:
                    cue = chat_cue(checked.lines)
                    if cue is not None:
                        chosen = candidate
                        chosen_kind = candidate_kind
                        chosen_signal = candidate.signals
                        chat_line = cue
                        break

        if chosen is None:
            continue

        best = chosen
        kind = chosen_kind
        social_kind = kind in SOCIAL_KINDS
        evidence = str(best.visual.get("evidence") or "").strip()
        start = cluster[0].start
        end = cluster[-1].end
        peak = (best.start + best.end) / 2
        spoken_lines = [
            line
            for line in lines
            if line.end > start + 0.2 and line.start < end - 0.2
        ]
        cue_lines = [line for line in spoken_lines if HUMOR_CUES.search(line.text)]

        # For a conversation, trim to the spoken interaction instead of the
        # arbitrary window boundary. Keep a little breath before/after.
        if social_kind:
            if spoken_lines:
                start = max(start, spoken_lines[0].start - 1.0)
                end = min(end, spoken_lines[-1].end + 1.0)
                if cue_lines:
                    peak = (cue_lines[-1].start + cue_lines[-1].end) / 2
                elif chosen_signal is not None:
                    peak = chosen_signal.peak_time
            elif chat_line is not None:
                start = max(cluster[0].start, chat_line.time - 8.0)
                end = min(cluster[-1].end, chat_line.time + 8.0)
                peak = chat_line.time
            elif chosen_signal is not None:
                center = chosen_signal.peak_time
                start = max(cluster[0].start, center - 8.0)
                end = min(cluster[-1].end, center + 8.0)
                peak = center
        if social_kind and end - start > SOCIAL_MAX_SECONDS:
            # Do not ship a 90-second VOD because the model liked every window.
            # Keep a tight window around the strongest cue in the best window.
            if cue_lines:
                center = (best.start + best.end) / 2
                chosen = min(
                    cue_lines,
                    key=lambda line: abs((line.start + line.end) / 2 - center),
                )
                middle = (chosen.start + chosen.end) / 2
                start = max(cluster[0].start, middle - SOCIAL_MAX_SECONDS / 2)
                end = min(cluster[-1].end, start + SOCIAL_MAX_SECONDS)
                peak = middle
                cue_lines = [
                    line for line in cue_lines
                    if line.end > start and line.start < end
                ] or [chosen]
            elif chat_line is not None:
                start = max(cluster[0].start, chat_line.time - SOCIAL_MAX_SECONDS / 2)
                end = min(cluster[-1].end, start + SOCIAL_MAX_SECONDS)
                peak = chat_line.time
            elif chosen_signal is not None:
                center = chosen_signal.peak_time
                start = max(cluster[0].start, center - SOCIAL_MAX_SECONDS / 2)
                end = min(cluster[-1].end, start + SOCIAL_MAX_SECONDS)
                peak = center
        if end - start < 4.0:
            middle = (best.start + best.end) / 2
            start = max(0.0, middle - 2.5)
            end = min(duration, middle + 2.5)
        if not social_kind:
            start = max(cluster[0].start, best.start - 5.0)
            end = min(cluster[-1].end, best.end + 5.0)
        if not social_kind and end - start > 30.0:
            end = min(cluster[-1].end, start + 30.0)
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
        if (
            social_kind
            and kind == "hype"
            and chosen_signal is not None
            and chosen_signal.agreement()
        ):
            reason = f"AI hype: {chosen_signal.reason()}"[:180]
        elif social_kind and cue_lines:
            quotes = [line.text.strip().strip('"') for line in cue_lines]
            quote = quotes[-1] if len(quotes) == 1 else f"{quotes[0]} / {quotes[-1]}"
            if len(quote) > 110:
                quote = quote[:107].rsplit(" ", 1)[0] + "..."
            reason = f'AI {kind}: "{quote}"'[:180]
        elif social_kind and chat_line is not None:
            reason = f'AI {kind}: chat "{chat_line.text}"'[:180]
        elif social_kind and chosen_signal is not None:
            reason = f"AI hype: {chosen_signal.reason()}"[:180]
        elif hud_hits:
            limit = 2 if kind == "round" else 1
            reason = f"AI {kind} (HUD): {display_text(hud_hits, limit)}"[:180]
        elif evidence:
            reason = f"AI {kind}: {evidence}"[:180]
        else:
            reason = f"AI {kind}: {summary}"[:180]
        clips.append(
            ClipWindow(
                start=max(0.0, start),
                end=min(duration, end),
                peak=min(duration - 0.05, max(0.0, peak)),
                score=max(0.05, min(0.99, float(best.visual.get("score", 0.7)))),
                audio_score=0.0,
                visual_score=0.0,
                reason=reason,
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
    jerk: ScoreTrack | None = None,
) -> tuple[list[ClipWindow], list[str]]:
    if not model_available(settings.ai_model):
        raise AIError(
            f"Local vision model {settings.ai_model!r} is not available. "
            f"Run: ollama pull {settings.ai_model}"
        )

    def wait_for_game(stage: str) -> None:
        guard = settings.game_guard
        if guard is None:
            return
        game = guard()
        if not game:
            return
        unload_model(settings.ai_model)
        if progress:
            progress(0.86, f"AI paused · {game} is running")
        while guard():
            time.sleep(2.0)
            if progress:
                progress(0.86, f"AI paused · {game} is running")
        if progress:
            progress(0.86, f"AI resumed · {stage}")

    wait_for_game("transcribing")

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

    if progress:
        progress(0.865, "AI director: reading audio/motion signals")
    signal_analysis = analyze_signals(wav, jerk, threads=settings.threads)
    tag_transcript(lines, signal_analysis)
    if wav is not None and not signal_analysis.acoustic.yamnet:
        warnings.append("AI director: YAMNet unavailable; laughter tags are off.")

    size = _window_size(duration)
    windows: list[StoryWindow] = []
    failed_windows = 0
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
            signals=window_signal(signal_analysis, start, end, lines),
        )
        if progress:
            progress(
                0.87 + 0.08 * index / max(1, count),
                f"AI director: watching {index + 1}/{count}",
            )
        wait_for_game(f"watching {index + 1}/{count}")
        try:
            window.visual = _review_window(
                video, window, settings.ai_model, bins, settings.ai_game
            )
        except (AIError, FFmpegError, OSError):
            failed_windows += 1
            window.visual = {
                "interesting": False,
                "score": 0.0,
                "kind": "filler",
                "summary": "",
                "evidence": "",
            }
        windows.append(window)

    if failed_windows:
        warnings.append(
            f"AI director skipped {failed_windows} unreadable window(s)."
        )

    if progress:
        progress(0.96, "AI director: choosing the story")

    def read_hud_window(start: float, end: float) -> HudReading:
        if progress:
            progress(0.96, "AI director: checking HUD evidence")
        return read_hud(video, start, end, bins)

    clips = _segments_from_windows(
        windows,
        lines,
        duration,
        settings,
        audio=audio,
        hud_reader=read_hud_window,
    )
    if not clips:
        warnings.append("AI director found no story beats in this clip.")
    clips = [clip for clip in _merge(clips) if clip.duration >= settings.min_clip]
    clips.sort(key=lambda clip: clip.score, reverse=True)
    clips = clips[: settings.max_clips]
    clips.sort(key=lambda clip: clip.start)
    if progress:
        progress(0.99, f"AI director: {len(clips)} segment(s)")
    return clips, warnings
