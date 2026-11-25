from __future__ import annotations

import csv
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly

from .audio import ScoreTrack

SIGNAL_VERSION = "signals-v2"
ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
YAMNET_MODEL = ASSET_DIR / "yamnet.onnx"
YAMNET_CLASSES = ASSET_DIR / "yamnet_class_map.csv"

LAUGH_TAG = 0.25
CHEER_TAG = 0.30
SHOUT_TAG = 0.30
JERK_TAG = 0.55
LOUD_TAG = 0.55
FAST_TAG = 0.55
PITCH_TAG = 0.55

LAUGH_NAMES = {
    "laughter",
    "baby laughter",
    "giggle",
    "snicker",
    "belly laugh",
    "chuckle, chortle",
}
CHEER_NAMES = {"cheering", "crowd", "applause", "whoop"}
SHOUT_NAMES = {"shout", "bellow", "yell", "screaming", "children shouting"}

CALLOUT_RE = re.compile(
    r"\b(enemy remaining|reloading|rotating|rotate|site [abc]|plant|defus|spike|"
    r"watch|push|hold|mid|flank|behind|one shot|low|heal|buy|eco|force)\b",
    re.IGNORECASE,
)
EXCITEMENT_RE = re.compile(
    r"\b(let'?s go|go go|run|oh my god|what the|no way|holy|fuck|shit|bro|dude|"
    r"bruh|laugh|haha|insane|crazy|unbelievable|clip|stop|wait|look|we won|"
    r"come on|yes|yeah|wow|jesus|kidding|serious)\b",
    re.IGNORECASE,
)

_YAMNET_SESSION = None
_YAMNET_FAILED_AT = 0.0
_YAMNET_RETRY_SECONDS = 60.0
_YAMNET_LOCK = threading.Lock()
_YAMNET_INDEX: dict[str, list[int]] | None = None
_YAMNET_INDEX_LOCK = threading.Lock()


@dataclass
class AcousticSignals:
    times: np.ndarray = field(default_factory=lambda: np.array([]))
    rms_db: np.ndarray = field(default_factory=lambda: np.array([]))
    pitch_times: np.ndarray = field(default_factory=lambda: np.array([]))
    pitch_hz: np.ndarray = field(default_factory=lambda: np.array([]))
    yamnet_times: np.ndarray = field(default_factory=lambda: np.array([]))
    laugh: np.ndarray = field(default_factory=lambda: np.array([]))
    cheer: np.ndarray = field(default_factory=lambda: np.array([]))
    shout: np.ndarray = field(default_factory=lambda: np.array([]))
    p95_db: float = 0.0
    pitch_median: float = 0.0
    wps_median: float = 2.5
    yamnet: bool = False


@dataclass
class LineSignal:
    loud: float = 0.0
    fast: float = 0.0
    pitch: float = 0.0
    wps: float = 0.0
    pitch_ratio: float = 1.0
    laugh: float = 0.0
    cheer: float = 0.0
    shout: float = 0.0
    jerk: float = 0.0
    tags: str = ""

    def labels(self) -> list[str]:
        tags: list[str] = []
        if self.laugh >= LAUGH_TAG:
            tags.append("LAUGH")
        if self.jerk >= JERK_TAG:
            tags.append("JERK")
        if self.fast >= FAST_TAG:
            tags.append("FAST")
        if self.pitch >= PITCH_TAG and self.loud >= 0.45:
            tags.append("PITCH")
        if self.loud >= LOUD_TAG:
            tags.append("LOUD")
        if self.cheer >= CHEER_TAG:
            tags.append("CHEER")
        if self.shout >= SHOUT_TAG:
            tags.append("SHOUT")
        return tags

    def words_per_second(self) -> str:
        return f"{self.wps:.1f}wps"


@dataclass
class WindowSignal(LineSignal):
    start: float = 0.0
    end: float = 0.0
    quote: str = ""
    quote_start: float = 0.0
    quote_end: float = 0.0
    peak_time: float = 0.0

    def tag_parts(self) -> list[str]:
        parts: list[str] = []
        if self.laugh >= LAUGH_TAG:
            parts.append(f"laugh {self.laugh:.2f}")
        if self.jerk >= JERK_TAG:
            parts.append(f"jerk {self.jerk:.2f}")
        if self.fast >= FAST_TAG:
            parts.append(f"fast {self.wps:.1f}wps")
        if self.pitch >= PITCH_TAG and self.loud >= 0.45:
            parts.append(f"pitch +{max(0.0, self.pitch_ratio - 1.0) * 100:.0f}%")
        if self.loud >= LOUD_TAG:
            parts.append(f"loud {self.loud:.2f}")
        if self.cheer >= CHEER_TAG:
            parts.append(f"cheer {self.cheer:.2f}")
        if self.shout >= SHOUT_TAG:
            parts.append(f"shout {self.shout:.2f}")
        return parts

    def prompt_text(self) -> str:
        parts = self.tag_parts()
        if not parts:
            return "(no strong acoustic or motion signals)"
        peak = f" @ {self.peak_time:.1f}s" if self.peak_time > 0 else ""
        return "; ".join(parts) + peak

    def agreement(self) -> bool:
        tags = set(self.labels())
        quote = self.quote.strip()
        if quote and CALLOUT_RE.search(quote) and not EXCITEMENT_RE.search(quote):
            return False
        if quote:
            words = re.findall(r"[A-Za-z0-9']+", quote)
            if len(words) <= 1:
                # "Yeah." / "Stop." alone is not a social highlight. A one-word
                # yell may still be a laugh burst when the audio agrees.
                return "LAUGH" in tags and bool(tags & {"JERK", "LOUD"})
            strong = tags & {"LAUGH", "FAST", "PITCH", "SHOUT", "CHEER"}
            if (
                len(tags) >= 2
                and strong
                and EXCITEMENT_RE.search(quote)
            ):
                return True
            # Three independent cues including a camera/mouse jerk are enough
            # for a chaos clip even when the transcript is a flat sentence.
            if len(tags) >= 3 and "JERK" in tags and strong:
                return True
            return False
        # Whisper often returns nothing for a pure laughter burst.
        return "LAUGH" in tags and bool(tags & {"JERK", "LOUD"})

    def reason(self) -> str:
        parts = self.tag_parts()
        quote = self.quote.strip()
        if len(re.findall(r"[A-Za-z0-9']+", quote)) <= 1:
            quote = ""
        if parts:
            if quote:
                return f'"{quote}" [' + ", ".join(parts[:3]) + "]"
            return "[" + ", ".join(parts[:3]) + "]"
        if quote:
            return f'"{quote}"'
        return "[strong reaction]"


@dataclass
class SignalAnalysis:
    acoustic: AcousticSignals
    jerk: ScoreTrack

    @property
    def available(self) -> bool:
        return bool(self.acoustic.times.size or self.jerk.times.size)


def _read_wav(path: Path | str) -> tuple[int, np.ndarray]:
    sample_rate, data = wavfile.read(str(path), mmap=True)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if data.dtype == np.uint8:
        samples = (data.astype(np.float32) - 128.0) / 128.0
    elif data.dtype == np.int16:
        samples = data.astype(np.float32) / 32768.0
    elif data.dtype == np.int32:
        samples = data.astype(np.float32) / 2147483648.0
    else:
        samples = data.astype(np.float32, copy=False)
    return int(sample_rate), samples


def _rms_track(samples: np.ndarray, sample_rate: int, hop: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    frame = max(1, int(round(sample_rate * hop)))
    total = samples.size // frame
    if total <= 0:
        return np.array([]), np.array([])
    blocks = samples[: total * frame].reshape(total, frame)
    rms = np.sqrt(np.mean(blocks * blocks, axis=1) + 1e-12)
    db = (20.0 * np.log10(rms + 1e-9)).astype(np.float32)
    times = (np.arange(total) + 0.5) * hop
    return times, db


def _pitch_track(
    samples: np.ndarray,
    sample_rate: int,
    frame: float = 0.04,
    hop: float = 0.02,
) -> tuple[np.ndarray, np.ndarray]:
    size = max(32, int(round(sample_rate * frame)))
    step = max(1, int(round(sample_rate * hop)))
    if samples.size < size:
        return np.array([]), np.array([])
    count = 1 + (samples.size - size) // step
    window = np.hanning(size).astype(np.float32)
    fft_size = 1
    while fft_size < size * 2:
        fft_size *= 2
    low_lag = max(2, int(sample_rate / 600.0))
    high_lag = min(size - 1, int(sample_rate / 80.0))
    values = np.zeros(count, dtype=np.float32)
    for index in range(count):
        chunk = samples[index * step : index * step + size]
        chunk = chunk - float(chunk.mean())
        if float(np.sqrt(np.mean(chunk * chunk))) < 0.004:
            continue
        chunk = chunk * window
        spectrum = np.fft.rfft(chunk, fft_size)
        corr = np.fft.irfft(spectrum * np.conj(spectrum))[:size]
        if corr[0] <= 1e-9:
            continue
        corr /= corr[0]
        lag = low_lag + int(np.argmax(corr[low_lag:high_lag]))
        if corr[lag] >= 0.25:
            values[index] = sample_rate / lag
    times = (np.arange(count) * hop) + frame / 2.0
    return times, values


def _yamnet_session(threads: int = 4):
    global _YAMNET_SESSION, _YAMNET_FAILED_AT
    if _YAMNET_SESSION is not None:
        return _YAMNET_SESSION
    now = time.monotonic()
    with _YAMNET_LOCK:
        if _YAMNET_SESSION is not None:
            return _YAMNET_SESSION
        if _YAMNET_FAILED_AT and now - _YAMNET_FAILED_AT < _YAMNET_RETRY_SECONDS:
            return None
        if not YAMNET_MODEL.is_file() or not YAMNET_CLASSES.is_file():
            _YAMNET_FAILED_AT = time.monotonic()
            return None
        try:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = max(1, min(4, int(threads or 4)))
            options.inter_op_num_threads = 1
            _YAMNET_SESSION = ort.InferenceSession(
                str(YAMNET_MODEL),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
            _YAMNET_FAILED_AT = 0.0
        except Exception:
            _YAMNET_FAILED_AT = time.monotonic()
            return None
    return _YAMNET_SESSION


def _mark_yamnet_failed() -> None:
    global _YAMNET_SESSION, _YAMNET_FAILED_AT
    with _YAMNET_LOCK:
        _YAMNET_SESSION = None
        _YAMNET_FAILED_AT = time.monotonic()


def _yamnet_indices() -> dict[str, list[int]] | None:
    global _YAMNET_INDEX
    if _YAMNET_INDEX is not None:
        return _YAMNET_INDEX
    with _YAMNET_INDEX_LOCK:
        if _YAMNET_INDEX is not None:
            return _YAMNET_INDEX
        if not YAMNET_CLASSES.is_file():
            return None
        try:
            index: dict[str, list[int]] = {"laugh": [], "cheer": [], "shout": []}
            with YAMNET_CLASSES.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    name = str(row.get("display_name") or "").strip().lower()
                    try:
                        class_id = int(row.get("index") or -1)
                    except ValueError:
                        continue
                    if name in LAUGH_NAMES:
                        index["laugh"].append(class_id)
                    elif name in CHEER_NAMES:
                        index["cheer"].append(class_id)
                    elif name in SHOUT_NAMES:
                        index["shout"].append(class_id)
            _YAMNET_INDEX = index
        except (OSError, UnicodeDecodeError, csv.Error):
            return None
    return _YAMNET_INDEX


def _yamnet_track(
    samples: np.ndarray,
    sample_rate: int,
    threads: int = 4,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    session = _yamnet_session(threads)
    indices = _yamnet_indices()
    if session is None or indices is None or not any(indices.values()):
        empty = np.array([])
        return empty, empty, empty, empty
    if sample_rate != 16000:
        samples = resample_poly(samples, 16000, sample_rate).astype(np.float32)
        sample_rate = 16000
    input_name = session.get_inputs()[0].name
    chunk_samples = 16000 * 60
    overlap = 16000
    step = max(1, chunk_samples - overlap)
    times: list[np.ndarray] = []
    laughs: list[np.ndarray] = []
    cheers: list[np.ndarray] = []
    shouts: list[np.ndarray] = []
    for start in range(0, max(1, samples.size), step):
        chunk = samples[start : start + chunk_samples + overlap]
        if chunk.size < 16000:
            continue
        try:
            scores = session.run(None, {input_name: chunk})[0]
        except Exception:
            _mark_yamnet_failed()
            return np.array([]), np.array([]), np.array([]), np.array([])
        if scores.ndim != 2:
            continue
        count = scores.shape[0]
        frame_times = (start / 16000.0) + (np.arange(count) * 0.48) + 0.48
        times.append(frame_times)
        laughs.append(scores[:, indices["laugh"]].max(axis=1))
        cheers.append(scores[:, indices["cheer"]].max(axis=1))
        shouts.append(scores[:, indices["shout"]].max(axis=1))
        if start + chunk.size >= samples.size:
            break
    if not times:
        empty = np.array([])
        return empty, empty, empty, empty
    return tuple(
        np.concatenate(parts).astype(np.float32)
        for parts in (times, laughs, cheers, shouts)
    )


def analyze_signals(
    wav: Path | None,
    jerk: ScoreTrack | None,
    *,
    threads: int = 4,
) -> SignalAnalysis:
    acoustic = AcousticSignals()
    if wav is not None and wav.is_file():
        try:
            sample_rate, samples = _read_wav(wav)
            if sample_rate > 0 and samples.size:
                times, rms = _rms_track(samples, sample_rate)
                pitch_times, pitch = _pitch_track(samples, sample_rate)
                acoustic = AcousticSignals(
                    times=times,
                    rms_db=rms,
                    pitch_times=pitch_times,
                    pitch_hz=pitch,
                )
                if rms.size:
                    acoustic.p95_db = float(np.percentile(rms, 95))
                voiced = pitch[pitch > 0]
                if voiced.size:
                    acoustic.pitch_median = float(np.median(voiced))
                y_times, laugh, cheer, shout = _yamnet_track(
                    samples, sample_rate, threads=threads
                )
                if y_times.size:
                    acoustic.yamnet = True
                    acoustic.yamnet_times = y_times
                    acoustic.laugh = laugh
                    acoustic.cheer = cheer
                    acoustic.shout = shout
        except Exception:
            acoustic = AcousticSignals()
    if jerk is None:
        jerk = ScoreTrack(np.array([]), np.array([]))
    return SignalAnalysis(acoustic=acoustic, jerk=jerk)


def _max_in(times: np.ndarray, values: np.ndarray, start: float, end: float) -> float:
    if times.size == 0 or values.size == 0:
        return 0.0
    mask = (times >= start) & (times <= end)
    if not np.any(mask):
        return 0.0
    return float(values[mask].max(initial=0.0))


def _pct_in(times: np.ndarray, values: np.ndarray, start: float, end: float, q: float) -> float:
    if times.size == 0 or values.size == 0:
        return 0.0
    mask = (times >= start) & (times <= end)
    if not np.any(mask):
        return 0.0
    return float(np.percentile(values[mask], q))


def _peak_time(times: np.ndarray, values: np.ndarray, start: float, end: float) -> float:
    if times.size == 0 or values.size == 0:
        return (start + end) / 2.0
    mask = (times >= start) & (times <= end)
    if not np.any(mask):
        return (start + end) / 2.0
    indices = np.flatnonzero(mask)
    best = indices[int(np.argmax(values[mask]))]
    return float(times[best])


def _words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))


def _line_signal(analysis: SignalAnalysis, line, wps_median: float) -> LineSignal:
    acoustic = analysis.acoustic
    start, end = float(line.start), float(line.end)
    span = max(0.4, end - start)
    words = _words(str(getattr(line, "text", "")))
    wps = words / span
    loud_db = _pct_in(acoustic.times, acoustic.rms_db, start, end, 90)
    loud = max(0.0, min(1.0, (loud_db - (acoustic.p95_db - 6.0)) / 12.0))
    fast_floor = max(4.5, wps_median * 1.5)
    fast = max(0.0, min(1.0, 0.55 + (wps - fast_floor) / 2.0))
    pitch_mask = (acoustic.pitch_times >= start) & (acoustic.pitch_times <= end)
    pitch_values = acoustic.pitch_hz[pitch_mask] if pitch_mask.any() else np.array([])
    voiced = pitch_values[pitch_values > 0] if pitch_values.size else np.array([])
    pitch_ratio = 1.0
    if voiced.size and acoustic.pitch_median > 0:
        pitch_ratio = float(np.percentile(voiced, 85) / acoustic.pitch_median)
        pitch_ratio = min(2.0, max(1.0, pitch_ratio))
    pitch = max(0.0, min(1.0, (pitch_ratio - 1.1) / 0.6))
    laugh = _max_in(acoustic.yamnet_times, acoustic.laugh, start - 0.2, end + 0.2)
    cheer = _max_in(acoustic.yamnet_times, acoustic.cheer, start - 0.2, end + 0.2)
    shout = _max_in(acoustic.yamnet_times, acoustic.shout, start - 0.2, end + 0.2)
    jerk = _max_in(analysis.jerk.times, analysis.jerk.scores, start - 0.5, end + 0.5)
    signal = LineSignal(
        loud=loud,
        fast=fast,
        pitch=pitch,
        wps=wps,
        pitch_ratio=pitch_ratio,
        laugh=laugh,
        cheer=cheer,
        shout=shout,
        jerk=jerk,
    )
    signal.tags = "; ".join(
        part
        for part in (
            f"LAUGH {laugh:.2f}" if laugh >= LAUGH_TAG else "",
            f"JERK {jerk:.2f}" if jerk >= JERK_TAG else "",
            f"FAST {wps:.1f}wps" if fast >= FAST_TAG else "",
            f"PITCH +{(pitch_ratio - 1) * 100:.0f}%" if pitch >= PITCH_TAG and loud >= 0.45 else "",
            f"LOUD {loud:.2f}" if loud >= LOUD_TAG else "",
        )
        if part
    )
    return signal


def tag_transcript(lines: list, analysis: SignalAnalysis) -> None:
    if not lines:
        analysis.acoustic.wps_median = 2.5
        return
    rates = []
    for line in lines:
        span = max(0.4, float(line.end) - float(line.start))
        rates.append(_words(str(getattr(line, "text", ""))) / span)
    rates = [rate for rate in rates if rate > 0]
    if rates:
        analysis.acoustic.wps_median = max(2.0, float(np.median(rates)))
    for line in lines:
        signal = _line_signal(analysis, line, analysis.acoustic.wps_median)
        line.tags = signal.tags


def window_signal(
    analysis: SignalAnalysis,
    start: float,
    end: float,
    lines: list,
) -> WindowSignal:
    acoustic = analysis.acoustic
    window_lines = [
        line for line in lines
        if float(line.end) > start and float(line.start) < end
    ]
    metrics = [
        (line, _line_signal(analysis, line, acoustic.wps_median))
        for line in window_lines
    ]
    quote_line = None
    quote_metrics = None
    best_score = -1.0
    excited = [
        (line, signal)
        for line, signal in metrics
        if EXCITEMENT_RE.search(str(getattr(line, "text", "")))
        and not (
            CALLOUT_RE.search(str(getattr(line, "text", "")))
            and not EXCITEMENT_RE.search(str(getattr(line, "text", "")))
        )
    ]
    for line, signal in (excited or metrics):
        score = (
            0.30 * signal.loud
            + 0.20 * signal.fast
            + 0.20 * signal.pitch
            + 0.50 * signal.laugh
            + 0.20 * signal.cheer
            + 0.15 * signal.shout
            + 0.10 * signal.jerk
        )
        text = str(getattr(line, "text", ""))
        if EXCITEMENT_RE.search(text):
            score += 0.55
        if CALLOUT_RE.search(text) and not EXCITEMENT_RE.search(text):
            score -= 0.35
        if score > best_score:
            best_score = score
            quote_line = line
            quote_metrics = signal
    loud_db = _pct_in(acoustic.times, acoustic.rms_db, start, end, 90)
    loud = max(0.0, min(1.0, (loud_db - (acoustic.p95_db - 6.0)) / 12.0))
    wps = max((signal.wps for _, signal in metrics), default=0.0)
    fast = max((signal.fast for _, signal in metrics), default=0.0)
    pitch_ratio = max((signal.pitch_ratio for _, signal in metrics), default=1.0)
    pitch = max((signal.pitch for _, signal in metrics), default=0.0)
    laugh = _max_in(acoustic.yamnet_times, acoustic.laugh, start, end)
    cheer = _max_in(acoustic.yamnet_times, acoustic.cheer, start, end)
    shout = _max_in(acoustic.yamnet_times, acoustic.shout, start, end)
    jerk = _max_in(analysis.jerk.times, analysis.jerk.scores, start, end)
    quote = str(getattr(quote_line, "text", "")).strip() if quote_line else ""
    quote_start = float(quote_line.start) if quote_line else 0.0
    quote_end = float(quote_line.end) if quote_line else 0.0
    if quote:
        peak = (quote_start + quote_end) / 2.0
    elif laugh >= LAUGH_TAG:
        peak = _peak_time(acoustic.yamnet_times, acoustic.laugh, start, end)
    elif jerk >= JERK_TAG:
        peak = _peak_time(analysis.jerk.times, analysis.jerk.scores, start, end)
    else:
        peak = _peak_time(acoustic.times, acoustic.rms_db, start, end)
    return WindowSignal(
        start=start,
        end=end,
        loud=loud,
        fast=fast,
        pitch=pitch,
        wps=wps,
        pitch_ratio=pitch_ratio,
        laugh=laugh,
        cheer=cheer,
        shout=shout,
        jerk=jerk,
        quote=quote,
        quote_start=quote_start,
        quote_end=quote_end,
        peak_time=peak,
    )
