from __future__ import annotations

import json
from pathlib import Path

import pytest

from clipper.library import ClipLibrary, LibraryError
from clipper.models import AnalysisSummary, ClipWindow, FileAnalysis, MediaInfo


def make_summary(source: Path, *, start: float = 1.0, end: float = 7.0) -> AnalysisSummary:
    clip = ClipWindow(
        start=start,
        end=end,
        peak=(start + end) / 2,
        score=0.81,
        reason="AI round (HUD): VICTORY",
        evidence={
            "model": "lfm3-omni",
            "kind": "round",
            "confidence": 0.81,
            "transcript": [{"start": 2.0, "end": 3.0, "text": "let's go"}],
        },
        tags=["clutch"],
        note="post this",
    )
    return AnalysisSummary(
        files=[
            FileAnalysis(
                path=str(source),
                name=source.name,
                info=MediaInfo(path=str(source), duration=20.0, width=1920, height=1080),
                clips=[clip],
                previews=[str(source.with_suffix(".jpg"))],
            )
        ],
        input_path=str(source.parent),
        setting_summary={"ai_game": "Valorant"},
    )


def test_save_load_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "match.mp4"
    source.write_bytes(b"video")
    library = ClipLibrary(tmp_path / "library.json")
    summary = library.save(make_summary(source))

    assert summary.scan_id.startswith("scan_")
    assert summary.files[0].clips[0].id
    loaded = library.load(summary.scan_id)
    assert loaded is not None
    clip = loaded.files[0].clips[0]
    assert clip.reason == "AI round (HUD): VICTORY"
    assert clip.evidence["kind"] == "round"
    assert clip.tags == ["clutch"]
    assert clip.note == "post this"
    assert loaded.setting_summary["ai_game"] == "Valorant"
    assert loaded.files[0].previews == [str(source.with_suffix(".jpg"))]

    scans = library.scans()
    assert len(scans) == 1
    assert scans[0].clips == 1
    assert scans[0].kept == 1


def test_rescan_preserves_decisions_by_clip_id(tmp_path: Path) -> None:
    source = tmp_path / "match.mp4"
    source.write_bytes(b"video")
    library = ClipLibrary(tmp_path / "library.json")
    first = library.save(make_summary(source))
    clip_id = first.files[0].clips[0].id
    library.set_clip(
        first.scan_id,
        clip_id,
        keep=False,
        note="too long",
        tags=["boring"],
    )

    second = library.save(make_summary(source))
    assert second.scan_id != first.scan_id
    clip = second.files[0].clips[0]
    assert clip.keep is False
    assert clip.note == "too long"
    assert clip.tags == ["boring"]


def test_saving_the_same_scan_updates_in_place(tmp_path: Path) -> None:
    source = tmp_path / "match.mp4"
    source.write_bytes(b"video")
    library = ClipLibrary(tmp_path / "library.json")
    first = library.save(make_summary(source))
    created = first.created_at
    first.files[0].clips[0].note = "updated"
    library.save(first)
    scans = library.scans()
    assert len(scans) == 1
    assert scans[0].created_at == created
    loaded = library.load(first.scan_id)
    assert loaded.files[0].clips[0].note == "updated"


def test_changed_clip_boundaries_get_a_new_decision_key(tmp_path: Path) -> None:
    source = tmp_path / "match.mp4"
    source.write_bytes(b"video")
    library = ClipLibrary(tmp_path / "library.json")
    first = library.save(make_summary(source, start=1.0, end=7.0))
    library.set_clip(first.scan_id, first.files[0].clips[0].id, note="old")
    second = library.save(make_summary(source, start=2.0, end=8.0))
    clip = second.files[0].clips[0]
    assert clip.note != "old"
    assert clip.keep is True


def test_set_all_keep_and_record_exports(tmp_path: Path) -> None:
    source = tmp_path / "match.mp4"
    source.write_bytes(b"video")
    library = ClipLibrary(tmp_path / "library.json")
    summary = library.save(make_summary(source))
    clip_id = summary.files[0].clips[0].id

    assert library.set_all_keep(summary.scan_id, False) == 1
    loaded = library.load(summary.scan_id)
    assert loaded is not None
    assert loaded.files[0].clips[0].keep is False

    recorded = library.record_exports(
        summary.scan_id,
        [
            {
                "clip_id": clip_id,
                "path": str(tmp_path / "out.mp4"),
                "preset": "shorts",
                "at": "2026-11-28T12:00:00+00:00",
            }
        ],
    )
    assert recorded == 1
    loaded = library.load(summary.scan_id)
    assert loaded is not None
    assert loaded.files[0].clips[0].exports[0]["preset"] == "shorts"


def test_delete_and_prune(tmp_path: Path) -> None:
    source = tmp_path / "match.mp4"
    source.write_bytes(b"video")
    library = ClipLibrary(tmp_path / "library.json", max_scans=2)
    first = library.save(make_summary(source, start=1.0, end=2.0))
    second = library.save(make_summary(source, start=3.0, end=4.0))
    third = library.save(make_summary(source, start=5.0, end=6.0))
    assert len(library.scans()) == 2
    assert library.load(first.scan_id) is None
    assert library.load(third.scan_id) is not None
    assert library.delete(second.scan_id) is True
    assert library.delete(second.scan_id) is False
    assert len(library.scans()) == 1


def test_corrupt_library_is_backed_up(tmp_path: Path) -> None:
    path = tmp_path / "library.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(LibraryError):
        ClipLibrary(path)
    assert list(tmp_path.glob("library.json.corrupt-*"))


def test_library_file_has_no_footage_payload(tmp_path: Path) -> None:
    source = tmp_path / "match.mp4"
    source.write_bytes(b"video")
    library = ClipLibrary(tmp_path / "library.json")
    summary = library.save(make_summary(source))
    payload = json.loads((tmp_path / "library.json").read_text(encoding="utf-8"))
    assert payload["schema"] == 1
    assert payload["scans"][0]["scan_id"] == summary.scan_id
    assert "video" not in json.dumps(payload["scans"][0]["files"][0]["clips"])
