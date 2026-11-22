from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from clipper.config import DetectionSettings
from clipper.ffmpeg import probe_media
from clipper.pipeline import analyze_target, export_analysis

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_demo_video.py"

pytestmark = pytest.mark.skipif(
    os.environ.get("CLIPPER_E2E") != "1",
    reason="set CLIPPER_E2E=1 to run the FFmpeg end-to-end test",
)


@pytest.fixture(scope="module")
def demo_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("demo")
    output = folder / "demo_gameplay.mp4"
    subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(output)],
        check=True,
        cwd=ROOT,
    )
    assert output.is_file() and output.stat().st_size > 100_000
    return output


def test_full_detect_and_export(demo_video: Path, tmp_path: Path) -> None:
    settings = DetectionSettings(
        sensitivity=0.55,
        pre=2,
        post=2,
        min_clip=2,
        max_clips=10,
        sample_fps=4,
        merge_gap=1.0,
        preview=False,
    )
    summary = analyze_target(demo_video, settings)
    assert summary.total_clips >= 2, [clip.to_dict() for clip in summary.files[0].clips]

    clips = summary.files[0].clips
    assert any(clip.start < 20 and clip.end > 12 for clip in clips)
    assert any(clip.start < 38 and clip.end > 30 for clip in clips)

    output = tmp_path / "trimmed"
    result = export_analysis(summary, output_dir=output, reencode=True)
    assert result.ok
    assert len(result.outputs) == len(clips)
    for rendered in result.outputs:
        assert rendered.is_file() and rendered.stat().st_size > 10_000
        info = probe_media(rendered)
        assert info.duration > 1.0
