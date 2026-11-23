from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..config import VIDEO_EXTENSIONS, Cancelled, ClipperError, DetectionSettings, find_ffmpeg
from ..ffmpeg import ffmpeg_version, has_encoder, make_thumbnail
from ..models import AnalysisSummary
from ..pipeline import analyze_target, export_analysis, scan_inputs

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"
THUMB_DIR = Path(tempfile.gettempdir()) / "clipper-thumbs"
ENCODERS = {"libx264", "h264_nvenc", "hevc_nvenc", "libx265"}


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"
    progress: float = 0.0
    message: str = "Queued"
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    cancel: threading.Event = field(default_factory=threading.Event)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "progress": round(float(self.progress), 4),
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "cancel_requested": self.cancel.is_set(),
        }


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.analyses: dict[str, tuple[AnalysisSummary, float]] = {}
        self.lock = threading.Lock()

    def _cleanup_locked(self) -> None:
        cutoff = time.time() - 2 * 60 * 60
        stale_jobs = [
            key
            for key, job in self.jobs.items()
            if job.created_at < cutoff and job.status in {"done", "error", "cancelled"}
        ]
        for key in stale_jobs:
            del self.jobs[key]
        stale_analyses = [key for key, (_, created) in self.analyses.items() if created < cutoff]
        for key in stale_analyses:
            del self.analyses[key]

    def create(self, kind: str) -> Job:
        with self.lock:
            self._cleanup_locked()
            job = Job(id=uuid.uuid4().hex[:12], kind=kind)
            self.jobs[job.id] = job
            return job

    def get(self, job_id: str) -> Job | None:
        with self.lock:
            return self.jobs.get(job_id)

    def store_analysis(self, summary: AnalysisSummary) -> str:
        analysis_id = uuid.uuid4().hex[:12]
        with self.lock:
            self.analyses[analysis_id] = (summary, time.time())
        return analysis_id

    def get_analysis(self, analysis_id: str) -> AnalysisSummary | None:
        with self.lock:
            item = self.analyses.get(analysis_id)
            return item[0] if item else None


manager = JobManager()


class ScanRequest(BaseModel):
    input: str = Field(min_length=1)
    recursive: bool = False


class AnalyzeRequest(ScanRequest):
    sensitivity: float = Field(0.5, ge=0.0, le=1.0)
    pre: float = Field(8.0, ge=0.0, le=120.0)
    post: float = Field(5.0, ge=0.0, le=120.0)
    min_clip: float = Field(3.0, ge=1.0, le=300.0)
    max_clips: int = Field(30, ge=1, le=200)
    audio_weight: float = Field(0.6, ge=0.0, le=1.0)
    visual_weight: float = Field(0.4, ge=0.0, le=1.0)
    sample_fps: float = Field(4.0, ge=1.0, le=15.0)
    merge_gap: float = Field(1.0, ge=0.0, le=10.0)
    threads: int = Field(0, ge=0, le=256)
    proxy_width: int = Field(320, ge=160, le=1280)
    gpu: bool = False
    low_power: bool = False

    def settings(self) -> DetectionSettings:
        settings = DetectionSettings(
            sensitivity=self.sensitivity,
            pre=self.pre,
            post=self.post,
            min_clip=self.min_clip,
            max_clips=self.max_clips,
            audio_weight=self.audio_weight,
            visual_weight=self.visual_weight,
            sample_fps=self.sample_fps,
            merge_gap=self.merge_gap,
            preview=False,
            threads=self.threads,
            proxy_width=self.proxy_width,
            gpu=self.gpu,
        )
        if self.low_power:
            settings.apply_low_power()
        return settings


class ExportRequest(BaseModel):
    analysis_id: str = Field(min_length=1)
    output: str = Field(default="./trimmed", min_length=1)
    reencode: bool = False
    encoder: str = "auto"
    crf: int = Field(20, ge=0, le=51)
    preset: str = "veryfast"
    threads: int = Field(0, ge=0, le=256)


def _run_analysis_job(job: Job, request: AnalyzeRequest) -> None:
    job.status = "running"
    job.message = "Starting analysis"

    def progress(fraction: float, message: str) -> None:
        if job.cancel.is_set():
            raise Cancelled("Cancelled by user")
        job.progress = max(0.0, min(1.0, fraction))
        job.message = message

    try:
        summary = analyze_target(
            request.input,
            request.settings(),
            recursive=request.recursive,
            progress=progress,
        )
        analysis_id = manager.store_analysis(summary)
        job.result = {"analysis_id": analysis_id, "summary": summary.to_dict()}
        job.progress = 1.0
        job.status = "done"
        job.message = f"Found {summary.total_clips} clip(s)"
    except Cancelled:
        job.status = "cancelled"
        job.message = "Cancelled"
    except Exception as exc:  # surface a clean error to the UI
        job.status = "error"
        job.error = str(exc)
        job.message = "Analysis failed"


def _run_export_job(job: Job, request: ExportRequest, summary: AnalysisSummary) -> None:
    job.status = "running"
    job.message = "Starting export"

    def progress(fraction: float, message: str) -> None:
        if job.cancel.is_set():
            raise Cancelled("Cancelled by user")
        job.progress = max(0.0, min(1.0, fraction))
        job.message = message

    try:
        result = export_analysis(
            summary,
            output_dir=request.output,
            reencode=request.reencode,
            encoder=request.encoder,
            crf=request.crf,
            preset=request.preset,
            progress=progress,
            threads=request.threads,
        )
        job.result = {"export": result.to_dict(), "output": str(Path(request.output).resolve())}
        job.progress = 1.0
        job.status = "done"
        job.message = f"Exported {len(result.outputs)} clip(s)"
    except Cancelled:
        job.status = "cancelled"
        job.message = "Cancelled"
    except Exception as exc:
        job.status = "error"
        job.error = str(exc)
        job.message = "Export failed"


def _spawn(target, *args) -> None:
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()


app = FastAPI(
    title="Clipper",
    version=__version__,
    description="Local gaming highlight trimmer",
    docs_url="/api/docs",
    redoc_url=None,
)
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    if not INDEX_FILE.is_file():
        raise HTTPException(500, "UI assets are missing from this install")
    return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict[str, Any]:
    try:
        bins = find_ffmpeg()
        version = ffmpeg_version(bins)
        nvenc = has_encoder("h264_nvenc", bins)
        return {
            "ok": True,
            "version": __version__,
            "ffmpeg": version,
            "ffmpeg_path": str(bins.ffmpeg),
            "nvenc": nvenc,
            "platform": sys.platform,
            "cwd": os.getcwd(),
        }
    except Exception as exc:
        return {
            "ok": False,
            "version": __version__,
            "error": str(exc),
            "platform": sys.platform,
        }


@app.get("/api/browse")
def browse(path: str = Query(default="")) -> dict[str, Any]:
    if not path.strip():
        roots: list[str] = []
        if os.name == "nt":
            for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
                drive = Path(f"{letter}:\\")
                try:
                    if drive.exists():
                        roots.append(str(drive))
                except OSError:
                    continue
        else:
            roots.append("/")
        home = str(Path.home())
        if home not in roots:
            roots.append(home)
        return {"path": "", "parent": None, "roots": roots, "dirs": [], "files": []}

    target = Path(path).expanduser()
    if target.is_file():
        target = target.parent
    try:
        target = target.resolve(strict=True)
    except (OSError, RuntimeError):
        raise HTTPException(404, f"Folder not found: {path}") from None
    if not target.is_dir():
        raise HTTPException(400, f"Not a folder: {target}")

    dirs: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    try:
        with os.scandir(target) as entries:
            for entry in entries:
                try:
                    if entry.name.startswith((".", "$")):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        dirs.append({"name": entry.name, "path": str(Path(entry.path))})
                    elif entry.is_file(follow_symlinks=False):
                        suffix = Path(entry.name).suffix.lower()
                        if suffix in VIDEO_EXTENSIONS:
                            files.append(
                                {
                                    "name": entry.name,
                                    "path": str(Path(entry.path)),
                                    "size": entry.stat().st_size,
                                }
                            )
                except OSError:
                    continue
    except PermissionError:
        raise HTTPException(403, f"Permission denied: {target}") from None

    dirs.sort(key=lambda item: item["name"].lower())
    files.sort(key=lambda item: item["name"].lower())
    parent = str(target.parent) if target.parent != target else None
    return {
        "path": str(target),
        "parent": parent,
        "roots": [],
        "dirs": dirs[:400],
        "files": files[:400],
    }


@app.post("/api/scan")
def scan(request: ScanRequest) -> dict[str, Any]:
    try:
        files = scan_inputs(request.input, recursive=request.recursive)
    except ClipperError as exc:
        raise HTTPException(400, str(exc)) from None
    return {
        "input": str(Path(request.input).expanduser().resolve()),
        "count": len(files),
        "files": [
            {"path": str(path), "name": path.name, "size": path.stat().st_size}
            for path in files
        ],
    }


@app.post("/api/analyze")
def analyze(request: AnalyzeRequest) -> dict[str, str]:
    try:
        found = scan_inputs(request.input, recursive=request.recursive)
    except ClipperError as exc:
        raise HTTPException(400, str(exc)) from None
    if not found:
        raise HTTPException(400, "No supported video files found in that folder")
    try:
        request.settings().validate()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None

    job = manager.create("analyze")
    _spawn(_run_analysis_job, job, request)
    return {"job_id": job.id}


@app.post("/api/export")
def export(request: ExportRequest) -> dict[str, str]:
    summary = manager.get_analysis(request.analysis_id)
    if summary is None:
        raise HTTPException(404, "Analysis expired or not found. Run detection again.")
    if request.encoder not in ENCODERS:
        raise HTTPException(400, f"Unknown encoder: {request.encoder}")
    if not request.output.strip():
        raise HTTPException(400, "Output folder is required")

    job = manager.create("export")
    _spawn(_run_export_job, job, request, summary)
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job.to_dict()


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    job.cancel.set()
    job.message = "Cancelling..."
    return {"id": job.id, "cancel_requested": True}


@app.get("/api/thumb")
def thumb(
    file: str = Query(min_length=1),
    t: float = Query(ge=0.0),
    w: int = Query(default=480, ge=120, le=1280),
) -> FileResponse:
    source = Path(file).expanduser()
    if source.suffix.lower() not in VIDEO_EXTENSIONS or not source.is_file():
        raise HTTPException(404, "Video not found")
    try:
        mtime = source.stat().st_mtime
        key = hashlib.sha1(f"{source.resolve()}|{mtime}|{t:.3f}|{w}".encode()).hexdigest()[:20]
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        target = THUMB_DIR / f"{key}.jpg"
        if not target.is_file():
            make_thumbnail(source, t, target, width=w)
        return FileResponse(
            target,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except Exception as exc:
        raise HTTPException(404, f"Could not create preview: {exc}") from None
