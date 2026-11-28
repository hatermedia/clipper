from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

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


def _run(
    cmd: Sequence[str],
    timeout: float | None = None,
    *,
    cwd: str | Path | None = None,
) -> subprocess.CompletedProcess[str]:
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
            cwd=str(cwd) if cwd is not None else None,
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
    """Total VRAM of the selected NVIDIA GPU, or None when unavailable."""

    from .gpu import query_nvidia_memory

    snapshot = query_nvidia_memory()
    return snapshot.total_mb if snapshot is not None else None


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


def _video_encode_args(
    encoder: str,
    crf: int,
    preset: str,
    *,
    pixel_format: str = "yuv420p",
) -> list[str]:
    if encoder in {"h264_nvenc", "hevc_nvenc"}:
        args = [
            "-c:v",
            encoder,
            "-preset",
            "p4",
            "-cq",
            str(crf),
            "-b:v",
            "0",
            "-pix_fmt",
            pixel_format,
        ]
        if encoder == "hevc_nvenc":
            args.extend(["-tag:v", "hvc1"])
        return args
    if encoder == "libx265":
        return [
            "-c:v",
            "libx265",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            pixel_format,
            "-tag:v",
            "hvc1",
        ]
    return [
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        pixel_format,
    ]


def _even(value: int) -> int:
    return max(2, int(value) // 2 * 2)


def _scale_filter(
    width: int,
    height: int,
    fit: str,
) -> str:
    width = _even(width)
    height = _even(height)
    if fit == "pad":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
        )
    if fit == "stretch":
        return f"scale={width}:{height},setsar=1"
    if fit == "crop":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1"
        )
    return f"scale={width}:{height}:force_original_aspect_ratio=decrease,setsar=1"


def _reframe_filter(plan: Any, target_width: int, target_height: int) -> str:
    if target_width < 2 or target_height < 2:
        raise FFmpegError("The reframe target size is invalid")
    crop_width = _even(int(getattr(plan, "crop_width", 0) or 0))
    crop_height = _even(int(getattr(plan, "crop_height", 0) or 0))
    if crop_width < 2 or crop_height < 2:
        raise FFmpegError("The reframe plan has an invalid crop size")
    static_x = max(0, int(getattr(plan, "static_x", 0) or 0))
    static_y = max(0, int(getattr(plan, "static_y", 0) or 0))
    filters = [
        f"crop@reframe={crop_width}:{crop_height}:{static_x}:{static_y}",
        _scale_filter(target_width, target_height, "stretch"),
    ]
    return ",".join(filters)


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
    *,
    target_width: int = 0,
    target_height: int = 0,
    fit: str = "source",
    fps: int = 0,
    audio_bitrate: str = "192k",
    reframe_plan: Any | None = None,
    fallback_encoder: str = "libx264",
) -> tuple[Path, bool]:
    """Render one clip. Returns (output_path, used_reencode).

    Stream copy is effectively instant but starts on a keyframe, so the first
    fraction of a second may include extra footage. Re-encoding is frame-accurate.
    A reframe plan adds a tracked crop with FFmpeg sendcmd commands; if the
    dynamic path fails, the renderer retries with a static crop and then with
    libx264 so a clip is never lost to a filter problem.
    """

    bins = _bins(bins)
    src = Path(input_path).expanduser().resolve()
    out = Path(output_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.05, clip.end - clip.start)
    resolved_encoder = resolve_encoder(encoder, bins)
    wants_filter = bool(
        (target_width and target_height)
        or fps
        or (reframe_plan is not None)
    )
    force_encode = bool(reencode or wants_filter)

    if wants_filter and not force_encode:
        force_encode = True

    def filters(use_reframe: bool) -> str:
        parts: list[str] = []
        if use_reframe and reframe_plan is not None:
            parts.append(_reframe_filter(reframe_plan, target_width, target_height))
        elif target_width and target_height:
            parts.append(_scale_filter(target_width, target_height, fit))
        if fps:
            parts.append(f"fps={max(1, int(fps))}")
        return ",".join(part for part in parts if part)

    def build(
        force_reencode: bool,
        video_encoder: str = resolved_encoder,
        *,
        use_reframe: bool = True,
        use_crop: bool = True,
    ) -> list[str]:
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
            cmd.extend(["-c:a", "aac", "-b:a", str(audio_bitrate)])
            cmd.extend(_thread_args(threads))
            active_filter = filters(use_reframe) if use_crop else ""
            if active_filter:
                cmd.extend(["-vf", active_filter])
        else:
            cmd.extend(["-c", "copy"])
        if out.suffix.lower() in {".mp4", ".mov", ".m4v"}:
            cmd.extend(["-movflags", "+faststart"])
        cmd.append(str(out))
        return cmd

    def run_attempt(
        force_reencode: bool,
        video_encoder: str = resolved_encoder,
        *,
        use_reframe: bool = True,
        use_crop: bool = True,
    ) -> tuple[subprocess.CompletedProcess[str], bool]:
        nonlocal used_reencode
        out.unlink(missing_ok=True)
        if use_reframe and reframe_plan is not None:
            with tempfile.TemporaryDirectory(prefix="clipper_reframe_") as raw:
                temp = Path(raw)
                command_writer = getattr(reframe_plan, "command_text", None)
                try:
                    command_text = (
                        command_writer(fps=60.0) if callable(command_writer) else ""
                    )
                except TypeError:
                    command_text = command_writer() if callable(command_writer) else ""
                (temp / "reframe.cmd").write_text(
                    str(command_text),
                    encoding="utf-8",
                )
                cmd = build(
                    force_reencode,
                    video_encoder,
                    use_reframe=True,
                    use_crop=use_crop,
                )
                # Insert sendcmd before the crop filter, using a relative file
                # name so Windows drive letters never need filter escaping.
                if use_crop and target_width and target_height:
                    filter_index = cmd.index("-vf") + 1
                    cmd[filter_index] = f"sendcmd=f=reframe.cmd,{cmd[filter_index]}"
                proc = _run(cmd, timeout=3600, cwd=temp)
        else:
            proc = _run(
                build(force_reencode, video_encoder, use_reframe=False, use_crop=use_crop),
                timeout=3600,
            )
        used_reencode = force_reencode
        failed = proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0
        return proc, failed

    used_reencode = force_encode
    proc = _run(
        build(force_encode, resolved_encoder, use_reframe=False, use_crop=False),
        timeout=3600,
    ) if not force_encode else None
    if proc is None:
        # The first render may be a dynamic reframe, a static target size, or a
        # plain frame-accurate encode. Try the richest path first.
        if reframe_plan is not None and target_width and target_height:
            proc, failed = run_attempt(True, resolved_encoder, use_reframe=True)
            if failed:
                proc, failed = run_attempt(True, resolved_encoder, use_reframe=False)
        else:
            proc, failed = run_attempt(True, resolved_encoder, use_reframe=False)
    else:
        failed = proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0

    if failed and (not force_encode or resolved_encoder in {"h264_nvenc", "hevc_nvenc"}):
        # Container/codec mismatch, or a GPU encoder that is listed but unusable
        # on this machine: retry with a clean software output.
        proc, failed = run_attempt(True, fallback_encoder, use_reframe=False)
    if proc is None or proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        raise FFmpegError(
            _tail((proc.stderr or proc.stdout) if proc is not None else "")
            or f"Failed to render {out.name}"
        )
    return out, used_reencode
