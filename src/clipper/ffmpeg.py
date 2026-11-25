from __future__ import annotations

import json
import os
import subprocess
import threading
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from .config import (
    ClipperError,
    FFmpegBinaries,
    FFmpegNotFound,
    find_ffmpeg,
)
from .models import ClipWindow, MediaInfo


class FFmpegError(ClipperError):
    """Raised when an ffmpeg/ffprobe command fails."""


_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_LAST_PROXY_BACKEND = ""
_ACTIVE_PROCS: set[subprocess.Popen] = set()
_ACTIVE_LOCK = threading.Lock()


def terminate_active_processes() -> None:
    """Best-effort shutdown for ffmpeg children owned by the current app."""

    with _ACTIVE_LOCK:
        active = list(_ACTIVE_PROCS)
    for proc in active:
        try:
            proc.terminate()
        except OSError:
            pass
    for proc in active:
        try:
            proc.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
    with _ACTIVE_LOCK:
        _ACTIVE_PROCS.clear()


def active_process_count() -> int:
    with _ACTIVE_LOCK:
        return len(_ACTIVE_PROCS)


def last_proxy_backend() -> str:
    """The backend that produced the most recent analysis proxy."""

    return _LAST_PROXY_BACKEND


def _run(cmd: Sequence[str], timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    args = [str(part) for part in cmd]
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise FFmpegNotFound(f"Could not execute {cmd[0]!r}") from exc
    with _ACTIVE_LOCK:
        _ACTIVE_PROCS.add(proc)
    try:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
            stdout, stderr = proc.communicate()
            raise FFmpegError(f"Command timed out after {timeout}s: {cmd[0]}")
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE_PROCS.discard(proc)
    return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)


def _tail(text: str, lines: int = 6) -> str:
    cleaned = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return " | ".join(cleaned[-lines:])


def _checked(cmd: Sequence[str], timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    proc = _run(cmd, timeout=timeout)
    if proc.returncode != 0:
        raise FFmpegError(_tail(proc.stderr or proc.stdout) or f"Command failed: {cmd[0]}")
    return proc


def _bins(binaries: FFmpegBinaries | None) -> FFmpegBinaries:
    return binaries or find_ffmpeg()


def nvidia_memory_mb() -> int | None:
    """Total VRAM reported by nvidia-smi, or None when unavailable."""

    import shutil

    smi = shutil.which("nvidia-smi")
    if not smi:
        return None
    try:
        proc = subprocess.run(
            [
                smi,
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        line = line.strip().split(",")[0].strip()
        if line.isdigit():
            return int(line)
    return None


def ffmpeg_version(binaries: FFmpegBinaries | None = None) -> str:
    bins = _bins(binaries)
    proc = _run([bins.ffmpeg, "-version"])
    if proc.returncode != 0:
        return "unknown"
    return (proc.stdout or "").splitlines()[0].strip()


@lru_cache(maxsize=32)
def has_encoder(name: str, binaries: FFmpegBinaries | None = None) -> bool:
    bins = _bins(binaries)
    proc = _run([bins.ffmpeg, "-hide_banner", "-encoders"])
    return name in (proc.stdout or "")


@lru_cache(maxsize=8)
def _nvenc_probe(ffmpeg_path: str) -> bool:
    """Actually try a one-frame NVENC encode; listed != usable."""

    proc = _run(
        [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=256x144:d=0.2",
            "-frames:v",
            "1",
            "-c:v",
            "h264_nvenc",
            "-f",
            "null",
            "-",
        ],
        timeout=30,
    )
    return proc.returncode == 0


def nvenc_available(binaries: FFmpegBinaries | None = None) -> bool:
    """Return True only when the H.264 NVENC encoder can actually encode."""

    bins = _bins(binaries)
    if not has_encoder("h264_nvenc", bins):
        return False
    return _nvenc_probe(str(bins.ffmpeg))


def resolve_encoder(encoder: str, binaries: FFmpegBinaries | None = None) -> str:
    """Resolve 'auto' to NVENC when it actually works, otherwise libx264."""

    if encoder in {"auto", "gpu"}:
        return "h264_nvenc" if nvenc_available(binaries) else "libx264"
    return encoder


def _thread_args(threads: int) -> list[str]:
    if threads <= 0:
        return []
    return ["-threads", str(max(1, int(threads)))]


def _filter_thread_args(threads: int) -> list[str]:
    if threads <= 0:
        return []
    return ["-filter_threads", str(max(1, int(threads)))]


def _parse_fps(value: str | None) -> float:
    if not value or value in {"0/0", "N/A"}:
        return 0.0
    if "/" in value:
        num, den = value.split("/", 1)
        try:
            return float(num) / float(den) if float(den) else 0.0
        except ValueError:
            return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def probe_media(path: Path | str, binaries: FFmpegBinaries | None = None) -> MediaInfo:
    bins = _bins(binaries)
    target = Path(path)
    proc = _checked(
        [
            bins.ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(target),
        ],
        timeout=120,
    )
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise FFmpegError(f"ffprobe returned invalid JSON for {target.name}") from exc

    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise FFmpegError(f"No video stream found in {target.name}")

    duration = 0.0
    for candidate in (fmt.get("duration"), video.get("duration")):
        try:
            duration = float(candidate)
            break
        except (TypeError, ValueError):
            continue

    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    # Respect phone/ShadowPlay rotation metadata when present.
    try:
        rotation = int(float((video.get("tags") or {}).get("rotate", 0)))
    except (TypeError, ValueError):
        rotation = 0
    if abs(rotation) % 180 == 90:
        width, height = height, width

    try:
        size_bytes = int(fmt.get("size") or target.stat().st_size)
    except (TypeError, ValueError, OSError):
        size_bytes = 0

    return MediaInfo(
        path=str(target.resolve()),
        duration=max(0.0, duration),
        width=width,
        height=height,
        fps=_parse_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        has_audio=audio is not None,
        video_codec=str(video.get("codec_name") or ""),
        audio_codec=str((audio or {}).get("codec_name") or ""),
        size_bytes=size_bytes,
    )


def extract_audio(
    path: Path | str,
    output_wav: Path | str,
    bins: FFmpegBinaries | None = None,
    threads: int = 0,
) -> Path:
    """Extract mono 16 kHz PCM audio for lightweight RMS analysis."""

    bins = _bins(bins)
    out = Path(output_wav)
    out.parent.mkdir(parents=True, exist_ok=True)
    _checked(
        [
            bins.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *_thread_args(threads),
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            *_thread_args(threads),
            str(out),
        ],
        timeout=900,
    )
    if not out.is_file() or out.stat().st_size <= 44:
        raise FFmpegError("ffmpeg produced an empty audio track")
    return out


def make_proxy(
    path: Path | str,
    output_mp4: Path | str,
    fps: float = 4.0,
    width: int = 320,
    bins: FFmpegBinaries | None = None,
    threads: int = 0,
    gpu: bool = False,
) -> Path:
    """Create a tiny low-fps proxy so OpenCV can scan long footage quickly.

    With ``gpu=True`` this tries a hardware decode + NVENC proxy, then falls
    back to NVENC without hardware decode, then CPU libx264, then mjpeg.
    """

    bins = _bins(bins)
    out = Path(output_mp4)
    out.parent.mkdir(parents=True, exist_ok=True)
    nvenc = gpu and nvenc_available(bins)

    def command(use_hwaccel: bool, use_nvenc: bool, codec: str) -> list[str]:
        cmd = [bins.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
        if use_hwaccel:
            cmd.extend(["-hwaccel", "auto"])
        cmd.extend(_thread_args(threads))
        cmd.extend(_filter_thread_args(threads))
        cmd.extend(["-i", str(path), "-an", "-vf", f"fps={fps},scale={width}:-2"])
        if use_nvenc:
            cmd.extend(["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "30"])
        elif codec == "libx264":
            cmd.extend(["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30"])
        else:
            cmd.extend(["-c:v", "mjpeg", "-q:v", "6"])
        cmd.extend(["-pix_fmt", "yuv420p", *_thread_args(threads), str(out)])
        return cmd

    attempts: list[tuple[str, list[str]]] = []
    if nvenc:
        attempts.append(("NVENC + hardware decode", command(use_hwaccel=True, use_nvenc=True, codec="h264_nvenc")))
        attempts.append(("NVENC", command(use_hwaccel=False, use_nvenc=True, codec="h264_nvenc")))
    attempts.append(("libx264 (CPU)", command(use_hwaccel=False, use_nvenc=False, codec="libx264")))
    attempts.append(("mjpeg (CPU)", command(use_hwaccel=False, use_nvenc=False, codec="mjpeg")))

    global _LAST_PROXY_BACKEND
    last_error = ""
    for label, cmd in attempts:
        out.unlink(missing_ok=True)
        proc = _run(cmd, timeout=3600)
        if proc.returncode == 0 and out.is_file() and out.stat().st_size > 0:
            _LAST_PROXY_BACKEND = label
            return out
        last_error = _tail(proc.stderr or proc.stdout)
    _LAST_PROXY_BACKEND = "failed"
    raise FFmpegError(last_error or "Could not build the analysis proxy")


def make_thumbnail(
    path: Path | str,
    timestamp: float,
    output_jpg: Path | str,
    width: int = 480,
    bins: FFmpegBinaries | None = None,
    crop: tuple[float, float, float, float] | None = None,
) -> Path:
    bins = _bins(bins)
    out = Path(output_jpg)
    out.parent.mkdir(parents=True, exist_ok=True)
    if crop is not None:
        x, y, w, h = crop
        video_filter = f"crop=iw*{w:.4f}:ih*{h:.4f}:iw*{x:.4f}:ih*{y:.4f},scale={width}:-2"
    else:
        video_filter = f"scale={width}:-2"
    _checked(
        [
            bins.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-threads",
            "1",
            "-ss",
            f"{max(0.0, timestamp):.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            video_filter,
            "-q:v",
            "3",
            str(out),
        ],
        timeout=120,
    )
    return out


def _video_encode_args(encoder: str, crf: int, preset: str) -> list[str]:
    if encoder in {"h264_nvenc", "hevc_nvenc"}:
        return ["-c:v", encoder, "-preset", "p4", "-cq", str(crf), "-b:v", "0"]
    if encoder == "libx265":
        return ["-c:v", "libx265", "-preset", preset, "-crf", str(crf)]
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p"]


def render_clip(
    input_path: Path | str,
    clip: ClipWindow,
    output_path: Path | str,
    reencode: bool = False,
    encoder: str = "libx264",
    crf: int = 20,
    preset: str = "veryfast",
    bins: FFmpegBinaries | None = None,
    threads: int = 0,
) -> tuple[Path, bool]:
    """Render one clip. Returns (output_path, used_reencode).

    Stream copy is effectively instant but starts on a keyframe, so the first
    fraction of a second may include extra footage. Re-encoding is frame-accurate.
    """

    bins = _bins(bins)
    src = Path(input_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.05, clip.end - clip.start)
    resolved_encoder = resolve_encoder(encoder, bins)

    def build(force_reencode: bool, video_encoder: str = resolved_encoder) -> list[str]:
        cmd = [
            bins.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *_thread_args(threads),
            "-ss",
            f"{clip.start:.3f}",
            "-i",
            str(src),
            "-t",
            f"{duration:.3f}",
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-map_metadata",
            "0",
        ]
        if force_reencode:
            cmd.extend(_video_encode_args(video_encoder, crf, preset))
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
            cmd.extend(_thread_args(threads))
        else:
            cmd.extend(["-c", "copy"])
        if out.suffix.lower() in {".mp4", ".mov", ".m4v"}:
            cmd.extend(["-movflags", "+faststart"])
        cmd.append(str(out))
        return cmd

    proc = _run(build(reencode), timeout=3600)
    used_reencode = reencode
    failed = proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0
    if failed and (not reencode or resolved_encoder in {"h264_nvenc", "hevc_nvenc"}):
        # Container/codec mismatch, or a GPU encoder that is listed but unusable
        # on this machine: retry with a clean libx264/AAC output.
        out.unlink(missing_ok=True)
        proc = _run(build(True, "libx264"), timeout=3600)
        used_reencode = True
        failed = proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        raise FFmpegError(_tail(proc.stderr or proc.stdout) or f"Failed to render {out.name}")
    return out, used_reencode
