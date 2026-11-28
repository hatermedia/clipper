from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from clipper.watch import (
    DONE,
    FAILED,
    QUEUED,
    RUNNING,
    ScanWorkflow,
    WorkflowError,
    fingerprint,
    is_system_idle,
    system_idle_seconds,
)


def touch(path: Path, content: bytes = b"video", age: float = 120.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))
    return path


def test_fingerprint_changes_when_file_changes(tmp_path: Path) -> None:
    video = touch(tmp_path / "a.mp4")
    first = fingerprint(video)
    video.write_bytes(b"different")
    os.utime(video, (time.time() - 30, time.time() - 30))
    assert fingerprint(video) != first


def test_watch_folder_baselines_existing_files(tmp_path: Path) -> None:
    touch(tmp_path / "old.mp4")
    workflow = ScanWorkflow(tmp_path / "workflow.json")
    workflow.add_folder(tmp_path, baseline=True)
    assert workflow.discover(settle=0) == []


def test_new_file_is_queued_after_it_settles(tmp_path: Path) -> None:
    workflow = ScanWorkflow(tmp_path / "workflow.json")
    workflow.add_folder(tmp_path)
    fresh = touch(tmp_path / "new.mp4", age=1.0)
    assert workflow.discover(now=time.time(), settle=60) == []
    old = touch(tmp_path / "new.mp4", age=120.0)
    jobs = workflow.discover(now=time.time(), settle=5)
    assert len(jobs) == 1
    assert jobs[0].path == str(old.resolve())
    assert jobs[0].manual is False
    assert workflow.pending_count() == 1


def test_discover_can_exclude_the_export_folder(tmp_path: Path) -> None:
    workflow = ScanWorkflow(tmp_path / "workflow.json")
    workflow.add_folder(tmp_path)
    touch(tmp_path / "source.mp4", age=120.0)
    output = tmp_path / "trimmed"
    touch(output / "export.mp4", age=120.0)
    jobs = workflow.discover(settle=0, exclude=[output])
    assert [Path(job.path).name for job in jobs] == ["source.mp4"]


def test_mark_seen_prevents_requeue(tmp_path: Path) -> None:
    workflow = ScanWorkflow(tmp_path / "workflow.json")
    workflow.add_folder(tmp_path)
    video = touch(tmp_path / "clip.mp4", age=120.0)
    workflow.mark_seen([video])
    assert workflow.discover(settle=0) == []


def test_active_folder_job_skips_children(tmp_path: Path) -> None:
    workflow = ScanWorkflow(tmp_path / "workflow.json")
    workflow.add_folder(tmp_path)
    video = touch(tmp_path / "clip.mp4", age=120.0)
    assert workflow.enqueue_path(tmp_path, recursive=True) is not None
    assert workflow.discover(settle=0) == []
    assert video.is_file()


def test_changed_file_can_be_queued_again(tmp_path: Path) -> None:
    workflow = ScanWorkflow(tmp_path / "workflow.json")
    workflow.add_folder(tmp_path)
    video = touch(tmp_path / "clip.mp4", age=120.0)
    job = workflow.discover(settle=0)[0]
    workflow.mark_running(job.id)
    workflow.finish(job.id, scan_id="scan_1", clips=2)
    assert workflow.job(job.id).status == DONE

    video.write_bytes(b"new recording")
    os.utime(video, (time.time() - 120, time.time() - 120))
    jobs = workflow.discover(settle=0)
    assert len(jobs) == 1
    assert jobs[0].id != job.id


def test_enqueue_path_dedupes_active_jobs(tmp_path: Path) -> None:
    video = touch(tmp_path / "clip.mp4")
    workflow = ScanWorkflow(tmp_path / "workflow.json")
    first = workflow.enqueue_path(video)
    assert first is not None
    assert first.manual is True
    assert workflow.enqueue_path(video) is None
    workflow.mark_running(first.id)
    assert workflow.enqueue_path(video) is None


def test_queue_lifecycle_and_clear(tmp_path: Path) -> None:
    video = touch(tmp_path / "clip.mp4")
    workflow = ScanWorkflow(tmp_path / "workflow.json")
    job = workflow.enqueue_path(video)
    assert job is not None
    assert workflow.next_job().id == job.id
    running = workflow.mark_running(job.id)
    assert running.status == RUNNING
    workflow.update_progress(job.id, 0.4, "Watching")
    assert workflow.job(job.id).progress == pytest.approx(0.4)
    workflow.finish(job.id, scan_id="scan_1", clips=3)
    assert workflow.job(job.id).status == DONE
    assert workflow.clear_finished() == 1
    assert workflow.job(job.id) is None


def test_running_job_has_an_eta(tmp_path: Path) -> None:
    video = touch(tmp_path / "clip.mp4")
    workflow = ScanWorkflow(tmp_path / "workflow.json")
    job = workflow.enqueue_path(video)
    workflow.mark_running(job.id)
    running = workflow.job(job.id)
    running.started_at = (
        datetime.now(timezone.utc) - timedelta(seconds=60)
    ).isoformat()
    workflow.update_progress(job.id, 0.5, "Watching")
    assert "left" in workflow.job(job.id).eta_label


def test_pause_stops_new_jobs(tmp_path: Path) -> None:
    video = touch(tmp_path / "clip.mp4")
    workflow = ScanWorkflow(tmp_path / "workflow.json")
    workflow.add_folder(tmp_path)
    workflow.set_paused(True)
    assert workflow.discover(settle=0) == []
    workflow.enqueue_path(video)
    assert workflow.next_job() is None
    workflow.set_paused(False)
    assert workflow.next_job() is not None


def test_running_job_is_recovered_after_restart(tmp_path: Path) -> None:
    video = touch(tmp_path / "clip.mp4")
    path = tmp_path / "workflow.json"
    workflow = ScanWorkflow(path)
    job = workflow.enqueue_path(video)
    workflow.mark_running(job.id)
    workflow.save()

    restored = ScanWorkflow(path)
    assert restored.job(job.id).status == RUNNING
    assert restored.recover() == 1
    recovered = restored.job(job.id)
    assert recovered.status == QUEUED
    assert recovered.attempts == 1
    assert "Resuming" in recovered.message


def test_repeated_crashes_fail_the_job(tmp_path: Path) -> None:
    video = touch(tmp_path / "clip.mp4")
    path = tmp_path / "workflow.json"
    workflow = ScanWorkflow(path)
    job = workflow.enqueue_path(video)
    workflow.mark_running(job.id)
    workflow.job(job.id).attempts = 2
    workflow.save()
    restored = ScanWorkflow(path)
    assert restored.recover() == 0
    failed = restored.job(job.id)
    assert failed.status == FAILED
    assert "repeatedly" in failed.error


def test_folder_recursive_toggle_persists_and_baselines(tmp_path: Path) -> None:
    workflow = ScanWorkflow(tmp_path / "workflow.json")
    workflow.add_folder(tmp_path, recursive=False)
    touch(tmp_path / "sub" / "old.mp4", age=120.0)
    assert workflow.set_folder_recursive(tmp_path, True) is True
    assert workflow.discover(settle=0) == []
    restored = ScanWorkflow(tmp_path / "workflow.json")
    assert restored.folders[0].recursive is True


def test_settings_and_pause_persist(tmp_path: Path) -> None:
    path = tmp_path / "workflow.json"
    workflow = ScanWorkflow(path)
    workflow.set_paused(True)
    workflow.set_idle_only(False)
    restored = ScanWorkflow(path)
    assert restored.paused is True
    assert restored.idle_only is False


def test_failed_job_can_be_retried(tmp_path: Path) -> None:
    video = touch(tmp_path / "clip.mp4")
    workflow = ScanWorkflow(tmp_path / "workflow.json")
    job = workflow.enqueue_path(video)
    workflow.mark_running(job.id)
    workflow.fail(job.id, "ffmpeg failed")
    assert workflow.job(job.id).status == FAILED
    workflow.retry(job.id)
    retried = workflow.job(job.id)
    assert retried.status == QUEUED
    assert retried.error == ""


def test_corrupt_workflow_is_backed_up(tmp_path: Path) -> None:
    path = tmp_path / "workflow.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(WorkflowError):
        ScanWorkflow(path)
    assert list(tmp_path.glob("workflow.json.corrupt-*"))


def test_idle_helpers_do_not_raise() -> None:
    idle = system_idle_seconds()
    assert idle is None or idle >= 0
    assert isinstance(is_system_idle(1.0), bool)
