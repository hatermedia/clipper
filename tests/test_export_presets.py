from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from clipper.config import FFmpegNotFound, find_ffmpeg
from clipper.models import AnalysisSummary, ClipWindow, FileAnalysis, MediaInfo, clip_key
from clipper.pipeline import export_analysis
from clipper.presets import LOSSLESS, ExportPreset, preset_for


def make_source(path: Path) -> None:
    bins = find_ffmpeg()
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
            "testsrc2=size=320x180:rate=30:duration=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )


def summary_for(source: Path) -> AnalysisSummary:
    clip = ClipWindow(start=0.4, end=2.4, peak=1.2, score=0.8, reason="test")
    clip.id = clip_key(str(source), clip.start, clip.end)
    return AnalysisSummary(
        files=[
            FileAnalysis(
                path=str(source),
                name=source.name,
                info=MediaInfo(
                    path=str(source),
                    duration=3.0,
                    width=320,
                    height=180,
                    fps=30.0,
                    has_audio=True,
                ),
                clips=[clip],
            )
        ],
        input_path=str(source.parent),
        created_at="2026-11-28T12:00:00+00:00",
    )


def probe_size(path: Path) -> tuple[int, int]:
    bins = find_ffmpeg()
    proc = subprocess.run(
        [
            str(bins.ffprobe),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(proc.stdout)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def test_export_lossless_and_vertical_preset(tmp_path: Path) -> None:
    try:
        find_ffmpeg()
    except FFmpegNotFound:
        pytest.skip("ffmpeg is not available")
    source = tmp_path / "source.mp4"
    make_source(source)
    summary = summary_for(source)

    lossless = export_analysis(summary, tmp_path / "lossless", export_preset=LOSSLESS)
    assert not lossless.errors
    assert len(lossless.outputs) == 1
    assert lossless.reencoded == []
    assert lossless.items[0].preset == "lossless"
    assert lossless.items[0].clip_id == summary.files[0].clips[0].id
    assert lossless.outputs[0].suffix == ".mp4"

    vertical = ExportPreset(
        id="test_vertical",
        label="Test vertical",
        description="Test only.",
        width=180,
        height=320,
        fit="crop",
        codec="h264",
        quality=28,
        reframe="auto",
        suffix="_vertical",
    )
    result = export_analysis(
        summary,
        tmp_path / "vertical",
        export_preset=vertical,
        filename_template="{source}_{index:02d}_{preset}",
        reframe_mode="auto",
    )
    assert not result.errors
    assert len(result.outputs) == 1
    assert result.outputs[0].name.startswith("source_01_test_vertical")
    assert probe_size(result.outputs[0]) == (180, 320)
    assert result.items[0].preset == "test_vertical"
    assert result.items[0].path == str(result.outputs[0])

    center = export_analysis(
        summary,
        tmp_path / "center",
        export_preset=vertical,
        filename_template="center_{index:02d}",
        reframe_mode="center",
    )
    assert not center.errors
    assert probe_size(center.outputs[0]) == (180, 320)


def test_preset_labels_are_stable() -> None:
    assert preset_for("shorts").label == "YouTube Shorts"
    assert preset_for("reels").label == "Instagram Reels"
    assert preset_for("tiktok").label == "TikTok"
