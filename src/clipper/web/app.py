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

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..config import (
    VIDEO_EXTENSIONS,
    Cancelled,
    ClipperError,
    DetectionSettings,
    ai_confidence_for_sensitivity,
    find_ffmpeg,
    normalize_server_url,
)
from ..ffmpeg import ffmpeg_version, make_thumbnail, nvenc_available
from ..models import AnalysisSummary
from ..pipeline import analyze_target, export_analysis, scan_inputs

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"
THUMB_DIR = Path(tempfile.gettempdir()) / "clipper-thumbs"
ENCODERS = {"auto", "libx264", "h264_nvenc", "hevc_nvenc", "libx265"}
X264_PRESETS = {
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow",
}
DEFAULT_AI_MODEL = "qwen2.5vl:7b"
# Host names the UI answers to. Anything else is refused, which defeats DNS
# rebinding: a hostile page that re-points its own domain at 127.0.0.1 still
# sends its own Host header. Add LAN names with CLIPPER_ALLOWED_HOSTS.
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'self'"
)


def _host_name(value: str) -> str:
    value = (value or "").strip().lower()
    if value.startswith("["):
        return value[1 : value.find("]")] if "]" in value else value
    if value.count(":") == 1:
        value = value.split(":", 1)[0]
    return value.strip(".")


def allowed_hosts() -> set[str]:
    extra = os.environ.get("CLIPPER_ALLOWED_HOSTS", "")
    return LOCAL_HOSTS | {_host_name(item) for item in extra.split(",") if item.strip()}


def allowed_roots() -> list[Path] | None:
    """Folders the API may read or write, from CLIPPER_ROOTS (os.pathsep list)."""

    raw = os.environ.get("CLIPPER_ROOTS", "")
    roots: list[Path] = []
    for item in raw.split(os.pathsep):
        if item.strip():
            try:
                roots.append(Path(item.strip()).expanduser().resolve())
            except (OSError, RuntimeError):
                continue
    return roots or None


def confine(path: str | Path, label: str = "Path") -> Path:
    """Resolve *path* and refuse it when it is outside CLIPPER_ROOTS."""

    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, RuntimeError):
        raise HTTPException(400, f"{label} is not a valid path") from None
    roots = allowed_roots()
    if roots is None:
        return resolved
    for root in roots:
        if resolved == root or resolved.is_relative_to(root):
            return resolved
    raise HTTPException(403, f"{label} is outside the folders this server may use")


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
    ai_model: str = Field(DEFAULT_AI_MODEL, min_length=1, max_length=200)
    ai_game: str = Field("auto", max_length=80)
    ai_server_url: str = Field("", max_length=500)
    ai_ears: bool = False

    def settings(self) -> DetectionSettings:
        server_url = ""
        model = self.ai_model.strip() or DEFAULT_AI_MODEL
        if self.ai_server_url.strip():
            server_url = normalize_server_url(self.ai_server_url)
            if not model.startswith("server:"):
                model = f"server:{model}"
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
            ai=True,
            ai_mode="director",
            ai_model=model,
            ai_server_url=server_url,
            ai_game=self.ai_game.strip() or "auto",
            ai_ears=self.ai_ears,
            ai_min_confidence=ai_confidence_for_sensitivity(self.sensitivity),
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


@app.middleware("http")
async def local_only_guard(request: Request, call_next):
    """Refuse foreign Host headers and cross-site API calls; add safe headers."""

    hosts = allowed_hosts()
    if _host_name(request.headers.get("host", "")) not in hosts:
        return PlainTextResponse("Host not allowed", status_code=421)
    if request.url.path.startswith("/api/"):
        site = request.headers.get("sec-fetch-site", "").lower()
        if site == "cross-site":
            return PlainTextResponse("Cross-site requests are not allowed", status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != "null":
            from urllib.parse import urlsplit

            if _host_name(urlsplit(origin).netloc) not in hosts:
                return PlainTextResponse("Origin not allowed", status_code=403)
        elif origin == "null" and request.method not in {"GET", "HEAD"}:
            return PlainTextResponse("Origin not allowed", status_code=403)
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    return response


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
        nvenc = nvenc_available(bins)
        return {
            "ok": True,
            "version": __version__,
            "ffmpeg": version,
            "nvenc": nvenc,
            "platform": sys.platform,
            "ai_default_model": DEFAULT_AI_MODEL,
            "restricted": allowed_roots() is not None,
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
    confined = allowed_roots()
    if not path.strip():
        roots: list[str] = []
        if confined is not None:
            return {
                "path": "",
                "parent": None,
                "roots": [str(root) for root in confined],
                "dirs": [],
                "files": [],
            }
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
    target = confine(target, "Folder")

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
    if confined is not None and parent is not None:
        try:
            confine(parent)
        except HTTPException:
            parent = None
    return {
        "path": str(target),
        "parent": parent,
        "roots": [],
        "dirs": dirs[:400],
        "files": files[:400],
    }


@app.post("/api/scan")
def scan(request: ScanRequest) -> dict[str, Any]:
    confine(request.input, "Input")
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
    confine(request.input, "Input")
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
    if request.preset not in X264_PRESETS:
        raise HTTPException(400, f"Unknown x264 preset: {request.preset}")
    confine(request.output, "Output folder")

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
    source = confine(file, "Video")
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
            headers={"Cache-Control": "private, max-age=3600"},
        )
    except Exception as exc:
        raise HTTPException(404, f"Could not create preview: {exc}") from None
