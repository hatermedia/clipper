from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from clipper.config import FFmpegBinaries
from clipper.detect import ears
from clipper.detect.ears import (
    AudioChunk,
    AudioReading,
    _chunk_score,
    _verdict_to_chunk,
    listen_clip,
    transcript_overlap,
)


def test_overlap_accepts_a_quote_whisper_also_heard() -> None:
    assert transcript_overlap(
        "You fucking stupid Russian cockroach",
        "That's how it works, bro. You fucking stupid Russian cockroach.",
    ) == pytest.approx(1.0)


def test_overlap_rejects_a_hallucinated_line() -> None:
    assert transcript_overlap(
        "Nopim shinishapchuk",
        "Yeah bro, no. You fucking idiot!",
    ) == 0.0


def test_overlap_needs_more_than_one_common_word() -> None:
    assert transcript_overlap("yeah", "Yeah bro, no.") == 0.0


def test_hallucinated_sarcasm_is_not_trusted() -> None:
    chunk = _verdict_to_chunk(
        {
            "speech": "Nopim shinishapchuk",
            "tone": "sarcastic",
            "laughter": False,
            "shouting": False,
            "proof": "the voice",
        },
        0.0,
        5.0,
        "Yeah bro, no. You fucking idiot!",
        0.0,
    )
    assert chunk.trusted is False
    assert chunk.score < 0.2


def test_laughter_with_acoustic_energy_is_trusted_even_without_words() -> None:
    chunk = _verdict_to_chunk(
        {
            "speech": "",
            "tone": "playful",
            "laughter": True,
            "shouting": False,
            "proof": "laughter",
        },
        0.0,
        5.0,
        "",
        0.35,
    )
    assert chunk.trusted is True
    assert chunk.score >= 0.5


def test_untrusted_chunks_are_discounted() -> None:
    trusted = _chunk_score(
        {"tone": "sarcastic", "laughter": True, "shouting": False, "speech": "you idiot"},
        True,
    )
    untrusted = _chunk_score(
        {"tone": "sarcastic", "laughter": True, "shouting": False, "speech": "you idiot"},
        False,
    )
    assert trusted > untrusted
    assert untrusted <= trusted * 0.25 + 1e-9


def test_listen_clip_aggregates_chunks_and_finds_the_payoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF")
    bins = FFmpegBinaries(ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe"))

    replies = iter(
        [
            {"speech": "blah blah", "tone": "neutral", "laughter": False},
            {"speech": "you fucking idiot", "tone": "playful", "laughter": True},
            {"speech": "you fucking idiot", "tone": "sarcastic", "laughter": True},
            {"speech": "yeah probably not", "tone": "playful", "laughter": True},
            {"speech": "blah blah", "tone": "neutral", "laughter": False},
        ]
    )

    monkeypatch.setattr(ears, "omni_available", lambda _model: True)
    monkeypatch.setattr(ears, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        ears,
        "_slice_wav",
        lambda _wav, _start, _end, output, _bins: output.write_bytes(b"RIFF") or output,
    )
    monkeypatch.setattr(ears, "_ask_chunk", lambda *_args, **_kwargs: next(replies))

    reading = listen_clip(
        video,
        wav,
        0.0,
        12.0,
        [(4.0, 8.0, "You fucking idiot!")],
        audio=None,
        bins=bins,
    )

    assert reading is not None
    assert reading.trusted is True
    assert reading.laughter is True
    assert reading.score >= 0.5
    assert 4.0 <= reading.peak <= 10.0
    assert "idiot" in reading.transcript.lower()
    assert "heard" not in reading.reason


def test_audio_reading_is_none_without_the_omni_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF")
    bins = FFmpegBinaries(ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe"))
    monkeypatch.setattr(ears, "omni_available", lambda _model: False)
    assert (
        listen_clip(video, wav, 0.0, 10.0, [], audio=None, bins=bins) is None
    )
