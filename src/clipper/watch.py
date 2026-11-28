"""Watch folders and a crash-safe local scan queue.

The workflow file is separate from the clip library so a long queue can be
paused, resumed, and recovered without rewriting scan decisions. Watch folders
baseline their existing files when added, then enqueue only new or changed
recordings after they have settled.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import VIDEO_EXTENSIONS
from .library import app_data_dir

SETTLE_SECONDS = 15.0
MAX_SEEN = 5000
MAX_JOBS = 250
MAX_ATTEMPTS = 3

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"


class WorkflowError(RuntimeError):
    """Raised when the watch/queue state cannot be read or written."""


def workflow_path() -> Path:
    override = os.environ.get("CLIPPER_WORKFLOW_PATH")
    return Path(override).expanduser() if override else app_data_dir() / "workflow.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def fingerprint(path: str | Path) -> str:
    stat = Path(path).stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise WorkflowError(f"Could not create the scan queue folder: {exc}") from exc
    temp = path.with_name(path.name + ".tmp")
    try:
        text = json.dumps(payload, indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise WorkflowError(f"Could not serialize the scan queue: {exc}") from exc
    try:
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, path)
    except OSError as exc:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise WorkflowError(f"Could not write the scan queue: {exc}") from exc


@dataclass
class WatchFolder:
    path: str
    recursive: bool = False
    enabled: bool = True
    added_at: str = ""

    @property
    def name(self) -> str:
        return Path(self.path).name or self.path

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "recursive": bool(self.recursive),
            "enabled": bool(self.enabled),
            "added_at": self.added_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WatchFolder":
        return cls(
            path=str(payload.get("path") or ""),
            recursive=bool(payload.get("recursive")),
            enabled=bool(payload.get("enabled", True)),
            added_at=str(payload.get("added_at") or ""),
        )


@dataclass
class QueueJob:
    id: str
    path: str
    recursive: bool = False
    status: str = QUEUED
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    progress: float = 0.0
    message: str = ""
    scan_id: str = ""
    error: str = ""
    attempts: int = 0
    clips: int = 0
    manual: bool = False

    @property
    def name(self) -> str:
        return Path(self.path).name or self.path

    @property
    def active(self) -> bool:
        return self.status in {QUEUED, RUNNING}

    @property
    def eta_label(self) -> str:
        if self.status != RUNNING or self.progress <= 0.02 or not self.started_at:
            return ""
        try:
            started = datetime.fromisoformat(self.started_at)
        except ValueError:
            return ""
        now = datetime.now(timezone.utc)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elapsed = max(0.0, (now - started).total_seconds())
        remaining = elapsed * (1.0 - self.progress) / max(0.01, self.progress)
        if remaining < 90:
            return f"~{max(5, int(round(remaining)))}s left"
        return f"~{max(2, int(round(remaining / 60)))}m left"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "recursive": bool(self.recursive),
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress": round(float(self.progress), 4),
            "message": self.message,
            "scan_id": self.scan_id,
            "error": self.error,
            "attempts": int(self.attempts),
            "clips": int(self.clips),
            "manual": bool(self.manual),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "QueueJob":
        status = str(payload.get("status") or QUEUED)
        if status not in {QUEUED, RUNNING, DONE, FAILED, CANCELLED}:
            status = FAILED
        return cls(
            id=str(payload.get("id") or ""),
            path=str(payload.get("path") or ""),
            recursive=bool(payload.get("recursive")),
            status=status,
            created_at=str(payload.get("created_at") or ""),
            started_at=str(payload.get("started_at") or ""),
            finished_at=str(payload.get("finished_at") or ""),
            progress=max(0.0, min(1.0, float(payload.get("progress") or 0.0))),
            message=str(payload.get("message") or ""),
            scan_id=str(payload.get("scan_id") or ""),
            error=str(payload.get("error") or ""),
            attempts=max(0, int(payload.get("attempts") or 0)),
            clips=max(0, int(payload.get("clips") or 0)),
            manual=bool(payload.get("manual")),
        )


def _job_id() -> str:
    return f"job_{int(time.time() * 1000)}_{os.urandom(3).hex()}"


class ScanWorkflow:
    """Persisted watch folders, discovered-file fingerprints, and queue jobs."""

    def __init__(self, path: str | Path | None = None, *, auto_save: bool = True) -> None:
        self.path = Path(path).expanduser() if path is not None else workflow_path()
        self.auto_save = auto_save
        self._lock = threading.RLock()
        self.folders: list[WatchFolder] = []
        self.jobs: list[QueueJob] = []
        self.seen: dict[str, str] = {}
        self.paused = False
        self.idle_only = True
        self.last_error = ""
        self._load()

    # -------------------------------------------------------------- storage
    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            backup = self.path.with_name(
                f"{self.path.name}.corrupt-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            )
            try:
                shutil.copy2(self.path, backup)
            except OSError:
                backup = None
            hint = f" A backup was kept at {backup}." if backup else ""
            raise WorkflowError(f"Could not read the scan queue: {exc}.{hint}") from exc
        if not isinstance(data, dict):
            raise WorkflowError("The scan queue has an unexpected format.")
        self.folders = [
            WatchFolder.from_dict(item)
            for item in data.get("folders", [])
            if isinstance(item, dict) and item.get("path")
        ]
        self.jobs = [
            QueueJob.from_dict(item)
            for item in data.get("jobs", [])
            if isinstance(item, dict) and item.get("id") and item.get("path")
        ]
        seen = data.get("seen")
        if isinstance(seen, dict):
            self.seen = {str(key): str(value) for key, value in seen.items()}
        self.paused = bool(data.get("paused"))
        self.idle_only = bool(data.get("idle_only", True))

    def save(self) -> None:
        with self._lock:
            payload = {
                "schema": 1,
                "paused": bool(self.paused),
                "idle_only": bool(self.idle_only),
                "folders": [folder.to_dict() for folder in self.folders],
                "jobs": [job.to_dict() for job in self.jobs[-MAX_JOBS:]],
                "seen": dict(list(self.seen.items())[-MAX_SEEN:]),
            }
            _atomic_write(self.path, payload)

    def _changed(self) -> None:
        if not self.auto_save:
            return
        try:
            self.save()
            self.last_error = ""
        except WorkflowError as exc:
            self.last_error = str(exc)

    def recover(self) -> int:
        """Requeue jobs that were running when the app last stopped."""

        with self._lock:
            recovered = 0
            for job in self.jobs:
                if job.status != RUNNING:
                    continue
                job.attempts += 1
                job.progress = 0.0
                job.started_at = ""
                if job.attempts >= MAX_ATTEMPTS:
                    job.status = FAILED
                    job.error = "Stopped repeatedly; retry it manually."
                    job.finished_at = _now()
                else:
                    job.status = QUEUED
                    job.message = "Resuming after restart"
                    recovered += 1
            if recovered or any(job.status == FAILED for job in self.jobs):
                self._changed()
            return recovered

    # --------------------------------------------------------------- folders
    def add_folder(
        self,
        path: str | Path,
        *,
        recursive: bool = False,
        baseline: bool = True,
    ) -> WatchFolder:
        target = Path(path).expanduser().resolve()
        if not target.is_dir():
            raise WorkflowError(f"Watch folder does not exist: {target}")
        with self._lock:
            for folder in self.folders:
                if _norm(folder.path) == _norm(target):
                    folder.recursive = bool(recursive)
                    folder.enabled = True
                    self._changed()
                    return folder
            folder = WatchFolder(
                path=str(target),
                recursive=bool(recursive),
                enabled=True,
                added_at=_now(),
            )
            self.folders.append(folder)
            if baseline:
                self._baseline(target, folder.recursive)
            self._changed()
            return folder

    def remove_folder(self, path: str | Path) -> bool:
        key = _norm(path)
        with self._lock:
            before = len(self.folders)
            self.folders = [folder for folder in self.folders if _norm(folder.path) != key]
            changed = len(self.folders) != before
            if changed:
                self._changed()
            return changed

    def set_folder_enabled(self, path: str | Path, enabled: bool) -> bool:
        key = _norm(path)
        with self._lock:
            for folder in self.folders:
                if _norm(folder.path) == key:
                    if folder.enabled != bool(enabled):
                        folder.enabled = bool(enabled)
                        self._changed()
                        return True
            return False

    def set_folder_recursive(self, path: str | Path, recursive: bool) -> bool:
        key = _norm(path)
        with self._lock:
            for folder in self.folders:
                if _norm(folder.path) == key:
                    if folder.recursive != bool(recursive):
                        folder.recursive = bool(recursive)
                        if folder.recursive:
                            self._baseline(Path(folder.path), True)
                        self._changed()
                        return True
            return False

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self.paused = bool(paused)
            self._changed()

    def set_idle_only(self, idle_only: bool) -> None:
        with self._lock:
            self.idle_only = bool(idle_only)
            self._changed()

    def _remember(self, key: str, stamp: str) -> None:
        self.seen.pop(key, None)
        self.seen[key] = stamp

    def _baseline(self, root: Path, recursive: bool) -> None:
        for file in _walk_videos(root, recursive):
            try:
                self._remember(_norm(file), fingerprint(file))
            except OSError:
                continue

    # ----------------------------------------------------------------- queue
    def enqueue_path(
        self,
        path: str | Path,
        *,
        recursive: bool = False,
        manual: bool = True,
    ) -> QueueJob | None:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            return None
        key = _norm(target)
        with self._lock:
            for job in self.jobs:
                if job.active and _norm(job.path) == key:
                    return None
            job = QueueJob(
                id=_job_id(),
                path=str(target),
                recursive=bool(recursive),
                status=QUEUED,
                created_at=_now(),
                message="Waiting",
                manual=bool(manual),
            )
            if target.is_file():
                try:
                    self._remember(key, fingerprint(target))
                except OSError:
                    pass
            self.jobs.append(job)
            self._trim_jobs()
            self._changed()
            return job

    def mark_seen(self, paths: Iterable[str | Path]) -> int:
        """Remember files that were just scanned so watch folders skip them."""

        marked = 0
        with self._lock:
            for item in paths:
                path = Path(item)
                try:
                    if not path.is_file():
                        continue
                    self._remember(_norm(path), fingerprint(path))
                    marked += 1
                except OSError:
                    continue
            if marked:
                self._changed()
        return marked

    def discover(
        self,
        *,
        now: float | None = None,
        settle: float = SETTLE_SECONDS,
        exclude: Iterable[str | Path] = (),
    ) -> list[QueueJob]:
        """Find new settled files in enabled watch folders."""

        with self._lock:
            if self.paused:
                return []
            current = time.time() if now is None else float(now)
            added: list[QueueJob] = []
            active_paths = {_norm(job.path) for job in self.jobs if job.active}
            active_dirs: list[Path] = []
            for job in self.jobs:
                if not job.active:
                    continue
                try:
                    candidate = Path(job.path)
                    if candidate.is_dir():
                        active_dirs.append(candidate.resolve())
                except OSError:
                    continue
            excluded: list[Path] = []
            for item in exclude:
                try:
                    resolved = Path(item).expanduser().resolve()
                except (OSError, RuntimeError):
                    continue
                if resolved:
                    excluded.append(resolved)
            for folder in self.folders:
                if not folder.enabled:
                    continue
                root = Path(folder.path)
                if not root.is_dir():
                    continue
                for file in _walk_videos(root, folder.recursive):
                    key = _norm(file)
                    if key in active_paths:
                        continue
                    try:
                        resolved_file = file.resolve()
                        if any(
                            resolved_file == folder_path
                            or folder_path in resolved_file.parents
                            for folder_path in (*excluded, *active_dirs)
                        ):
                            continue
                    except (OSError, RuntimeError):
                        pass
                    try:
                        stamp = fingerprint(file)
                        stat = file.stat()
                    except OSError:
                        continue
                    if self.seen.get(key) == stamp:
                        continue
                    if current - stat.st_mtime < settle:
                        continue
                    if stat.st_size <= 0:
                        continue
                    job = QueueJob(
                        id=_job_id(),
                        path=str(file.resolve()),
                        recursive=False,
                        status=QUEUED,
                        created_at=_now(),
                        message="New recording",
                    )
                    self.jobs.append(job)
                    self._remember(key, stamp)
                    active_paths.add(key)
                    added.append(job)
            if added:
                self._trim_jobs()
                self._changed()
            return added

    def _trim_jobs(self) -> None:
        if len(self.jobs) <= MAX_JOBS:
            return
        keep = self.jobs[-MAX_JOBS:]
        finished = [job for job in keep if job.status in {DONE, FAILED, CANCELLED}]
        active = [job for job in keep if job.active]
        self.jobs = (finished[: len(keep) - len(active)] + active)[-MAX_JOBS:]

    def next_job(self) -> QueueJob | None:
        with self._lock:
            if self.paused:
                return None
            for job in self.jobs:
                if job.status == QUEUED:
                    return job
            return None

    def job(self, job_id: str) -> QueueJob | None:
        with self._lock:
            for job in self.jobs:
                if job.id == job_id:
                    return job
            return None

    def mark_running(self, job_id: str) -> QueueJob | None:
        with self._lock:
            job = self.job(job_id)
            if job is None:
                return None
            job.status = RUNNING
            job.started_at = _now()
            job.progress = 0.0
            job.message = "Starting"
            job.error = ""
            self._changed()
            return job

    def update_progress(self, job_id: str, fraction: float, message: str = "") -> None:
        with self._lock:
            job = self.job(job_id)
            if job is None or job.status != RUNNING:
                return
            job.progress = max(0.0, min(1.0, float(fraction)))
            if message:
                job.message = message
            self._changed()

    def finish(self, job_id: str, *, scan_id: str, clips: int) -> QueueJob | None:
        with self._lock:
            job = self.job(job_id)
            if job is None or job.status == CANCELLED:
                return job
            job.status = DONE
            job.scan_id = scan_id
            job.clips = max(0, int(clips))
            job.progress = 1.0
            job.message = f"{job.clips} clip(s)"
            job.finished_at = _now()
            self._changed()
            return job

    def fail(self, job_id: str, message: str) -> QueueJob | None:
        with self._lock:
            job = self.job(job_id)
            if job is None:
                return None
            job.status = FAILED
            job.error = str(message).strip()[:500]
            job.message = "Failed"
            job.finished_at = _now()
            self._changed()
            return job

    def cancel(self, job_id: str) -> QueueJob | None:
        with self._lock:
            job = self.job(job_id)
            if job is None:
                return None
            job.status = CANCELLED
            job.message = "Cancelled"
            job.finished_at = _now()
            self._changed()
            return job

    def requeue(self, job_id: str) -> QueueJob | None:
        with self._lock:
            job = self.job(job_id)
            if job is None:
                return None
            job.status = QUEUED
            job.progress = 0.0
            job.error = ""
            job.message = "Resuming after restart"
            job.started_at = ""
            job.finished_at = ""
            self._changed()
            return job

    def retry(self, job_id: str) -> QueueJob | None:
        with self._lock:
            job = self.job(job_id)
            if job is None or job.status == RUNNING:
                return None
            job.status = QUEUED
            job.progress = 0.0
            job.error = ""
            job.message = "Waiting"
            job.started_at = ""
            job.finished_at = ""
            job.attempts = 0
            self._changed()
            return job

    def clear_finished(self) -> int:
        with self._lock:
            before = len(self.jobs)
            self.jobs = [job for job in self.jobs if job.active]
            removed = before - len(self.jobs)
            if removed:
                self._changed()
            return removed

    def pending_count(self) -> int:
        with self._lock:
            return sum(1 for job in self.jobs if job.status == QUEUED)

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for job in self.jobs if job.active)


def _walk_videos(root: Path, recursive: bool) -> Iterable[Path]:
    try:
        iterator = root.rglob("*") if recursive else root.iterdir()
    except OSError:
        return []
    result: list[Path] = []
    for candidate in iterator:
        try:
            if candidate.is_file() and candidate.suffix.lower() in VIDEO_EXTENSIONS:
                result.append(candidate)
        except OSError:
            continue
    result.sort(key=lambda item: str(item).lower())
    return result


def system_idle_seconds() -> float | None:
    """Seconds since the last keyboard/mouse input, or None if unknown."""

    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        tick = ctypes.windll.kernel32.GetTickCount()
        elapsed = (int(tick) - int(info.dwTime)) & 0xFFFFFFFF
        return elapsed / 1000.0
    except Exception:
        return None


def is_system_idle(seconds: float = 120.0) -> bool:
    idle = system_idle_seconds()
    if idle is None:
        return True
    return idle >= max(1.0, float(seconds))
