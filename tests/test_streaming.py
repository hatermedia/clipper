from __future__ import annotations

from pathlib import Path

import clipper.pipeline as pipeline
from clipper.config import DetectionSettings
from clipper.models import FileAnalysis, MediaInfo


def test_on_file_done_streams_each_result(monkeypatch, tmp_path: Path) -> None:
    files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    for file in files:
        file.write_bytes(b"x")
    seen: list[str] = []

    def fake_analyze(file, settings, bins, preview_dir=None, progress=None):
        return FileAnalysis(
            path=str(file),
            name=file.name,
            info=MediaInfo(path=str(file), duration=10.0),
        )

    monkeypatch.setattr(pipeline, "scan_inputs", lambda *args, **kwargs: files)
    monkeypatch.setattr(pipeline, "find_ffmpeg", lambda: object())
    monkeypatch.setattr(pipeline, "analyze_file", fake_analyze)
    monkeypatch.setattr(pipeline, "configure_cpu_limits", lambda _threads: None)

    summary = pipeline.analyze_target(
        tmp_path,
        DetectionSettings(),
        on_file_done=lambda analysis: seen.append(analysis.name),
    )
    assert seen == ["a.mp4", "b.mp4"]
    assert [item.name for item in summary.files] == ["a.mp4", "b.mp4"]
