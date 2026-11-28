from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from clipper.config import FFmpegNotFound, find_ffmpeg
from clipper.reframe import (
    ReframeError,
    center_plan,
    crop_box,
    plan_reframe,
    track_from_centers,
)


def test_crop_box_vertical_and_square() -> None:
    width, height = crop_box(1920, 1080, 1080, 1920)
    assert width == 608
    assert height == 1080
    square_w, square_h = crop_box(1920, 1080, 1080, 1080)
    assert (square_w, square_h) == (1080, 1080)
    same_w, same_h = crop_box(1080, 1920, 1080, 1920)
    assert (same_w, same_h) == (1080, 1920)


def test_crop_box_rejects_bad_dimensions() -> None:
    with pytest.raises(ReframeError):
        crop_box(0, 0, 1080, 1920)
    with pytest.raises(ReframeError):
        crop_box(1920, 1080, 0, 0)


def test_track_is_smoothed_and_clamped() -> None:
    xs, ys, confidence = track_from_centers(
        [0.0, 0.5, 1.0, 1.5],
        [-500.0, 100.0, 500.0, 900.0],
        [180.0, 180.0, 180.0, 180.0],
        source_width=640,
        source_height=360,
        crop_width=202,
        crop_height=360,
    )
    assert len(xs) == 4
    assert all(0 <= value <= 438 for value in xs)
    assert all(value == 0 for value in ys)
    assert 0.0 <= confidence <= 1.0


def test_track_rejects_mismatched_samples() -> None:
    with pytest.raises(ReframeError):
        track_from_centers(
            [0.0, 1.0],
            [10.0],
            [20.0],
            source_width=640,
            source_height=360,
            crop_width=202,
            crop_height=360,
        )


def test_command_text_targets_named_crop_filter() -> None:
    from clipper.reframe import ReframePlan, ReframeSample

    plan = ReframePlan(
        source_width=1920,
        source_height=1080,
        crop_width=608,
        crop_height=1080,
        samples=(
            ReframeSample(0.0, 100, 0),
            ReframeSample(1.5, 200, 0),
        ),
        mode="action",
        confidence=0.7,
        reason="action tracking",
    )
    text = plan.command_text()
    assert "0.000 crop@reframe x 100;" in text
    assert "1.500 crop@reframe x 200;" in text
    assert "crop@reframe y 0;" in text
    assert plan.static_x == 150


def test_command_text_interpolates_for_smooth_export() -> None:
    from clipper.reframe import ReframePlan, ReframeSample

    plan = ReframePlan(
        source_width=1920,
        source_height=1080,
        crop_width=608,
        crop_height=1080,
        samples=(
            ReframeSample(0.0, 100, 0),
            ReframeSample(2.0, 200, 0),
        ),
        mode="action",
        confidence=0.7,
        reason="action tracking",
    )
    text = plan.command_text(fps=60.0)
    x_values = [
        int(match)
        for match in re.findall(r"crop@reframe x (\d+);", text)
    ]
    assert len(x_values) == 121
    assert x_values[0] == 100
    assert x_values[-1] == 200
    assert max(
        abs(x_values[index] - x_values[index - 1])
        for index in range(1, len(x_values))
    ) <= 2
    assert len(text.splitlines()) == 242


def test_plan_reframe_on_a_real_generated_clip(tmp_path: Path) -> None:
    try:
        bins = find_ffmpeg()
    except FFmpegNotFound:
        pytest.skip("ffmpeg is not available")
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            str(bins.ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=30:duration=3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
    )
    plan = plan_reframe(source, 0.2, 2.8, 540, 960, sample_fps=4.0)
    assert plan.crop_width == 202
    assert plan.crop_height == 360
    assert len(plan.samples) >= 4
    assert plan.source_width == 640
    assert plan.source_height == 360
    assert plan.command_text().count("crop@reframe x") == len(plan.samples)
    assert all(0 <= sample.x <= 438 for sample in plan.samples)
    assert all(sample.y == 0 for sample in plan.samples)

    center = center_plan(source, 540, 960)
    assert center.samples[0].x > 0
    assert center.reason == "center crop"


def test_plan_reframe_rejects_missing_video(tmp_path: Path) -> None:
    with pytest.raises(ReframeError):
        plan_reframe(tmp_path / "missing.mp4", 0, 2, 1080, 1920)
