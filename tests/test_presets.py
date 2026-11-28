from __future__ import annotations

from pathlib import Path

import pytest

from clipper.models import ClipWindow
from clipper.presets import (
    DEFAULT_TEMPLATE,
    LOSSLESS,
    output_suffix,
    preset_choices,
    preset_for,
    render_filename,
    safe_stem,
)


def clip() -> ClipWindow:
    return ClipWindow(start=61.0, end=95.0, peak=70.0, score=0.87)


def test_preset_registry_has_creator_targets() -> None:
    ids = {preset.id for preset in preset_choices()}
    assert {"lossless", "shorts", "tiktok", "reels", "square", "landscape"} <= ids
    assert preset_for("shorts").width == 1080
    assert preset_for("shorts").height == 1920
    assert preset_for("square").width == 1080
    assert preset_for("square").height == 1080
    assert preset_for("shorts").reframe == "auto"
    assert preset_for("landscape").reframe == "none"
    assert preset_for(None) is LOSSLESS
    assert preset_for("YouTube Shorts") is preset_for("shorts")
    with pytest.raises(KeyError):
        preset_for("does-not-exist")


def test_lossless_and_creator_output_suffixes() -> None:
    assert output_suffix(LOSSLESS, "source.mkv") == ".mkv"
    assert output_suffix(LOSSLESS, "source.unknown") == ".mp4"
    assert output_suffix(preset_for("shorts"), "source.mkv") == ".mp4"


def test_filename_template_tokens_and_suffix() -> None:
    name = render_filename(
        "{source}_{index:02d}_{start}_{end}_{score}_{preset}",
        source="My Match.mkv",
        clip=clip(),
        index=3,
        preset=preset_for("shorts"),
        created_at="2026-11-28T12:00:00+00:00",
    )
    assert name.startswith("My_Match_03_01m01s_01m35s_87_shorts")
    assert name.count("_shorts") == 1


def test_default_filename_gets_preset_suffix_and_drops_extension() -> None:
    name = render_filename(
        "{source}_clip_{index:02d}.mp4",
        source="My Match.mkv",
        clip=clip(),
        index=1,
        preset=preset_for("shorts"),
    )
    assert name == "My_Match_clip_01_shorts"


def test_invalid_template_falls_back_to_default() -> None:
    name = render_filename(
        "{unknown_token}",
        source="match.mkv",
        clip=clip(),
        index=2,
        preset=LOSSLESS,
    )
    assert "match_clip_02" in name


def test_filename_cannot_escape_the_output_folder() -> None:
    name = render_filename(
        "../../evil/{source}",
        source="match.mkv",
        clip=clip(),
        index=1,
        preset=LOSSLESS,
    )
    assert "/" not in name
    assert "\\" not in name
    assert ".." not in name
    assert name.startswith("evil_match")


def test_safe_stem_keeps_useful_characters() -> None:
    assert safe_stem("  hello world!  ") == "hello_world"
    assert safe_stem("") == "clip"
    assert len(safe_stem("x" * 200)) == 70
    assert safe_stem("a/b\\c") == "a_b_c"


def test_default_template_is_stable() -> None:
    assert DEFAULT_TEMPLATE == "{source}_clip_{index:02d}_{start}-{end}"
