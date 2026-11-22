from __future__ import annotations

from pathlib import Path

import pytest

from clipper.config import ClipperError
from clipper.pipeline import scan_inputs


def touch(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_scan_filters_and_sorts(tmp_path) -> None:
    touch(tmp_path / "b.mp4")
    touch(tmp_path / "A.MKV")
    touch(tmp_path / "notes.txt")
    touch(tmp_path / "sub" / "c.mov")
    files = scan_inputs(tmp_path)
    assert [item.name for item in files] == ["A.MKV", "b.mp4"]


def test_scan_recursive(tmp_path) -> None:
    touch(tmp_path / "a.mp4")
    touch(tmp_path / "sub" / "b.avi")
    files = scan_inputs(tmp_path, recursive=True)
    assert {item.name for item in files} == {"a.mp4", "b.avi"}


def test_scan_excludes_output_folder(tmp_path) -> None:
    touch(tmp_path / "raw.mp4")
    output = tmp_path / "trimmed"
    touch(output / "old_clip.mp4")
    files = scan_inputs(tmp_path, recursive=True, exclude=output)
    assert [item.name for item in files] == ["raw.mp4"]


def test_scan_single_file(tmp_path) -> None:
    video = touch(tmp_path / "one.mp4")
    assert scan_inputs(video) == [video.resolve()]


def test_scan_rejects_missing_folder(tmp_path) -> None:
    with pytest.raises(ClipperError):
        scan_inputs(tmp_path / "nope")
