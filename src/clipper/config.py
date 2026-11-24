from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi"}


class ClipperError(RuntimeError):
    """Base exception for user-facing Clipper failures."""


class Cancelled(ClipperError):
    """Raised when a running web job is cancelled by the user."""


class FFmpegNotFound(ClipperError):
    """Raised when ffmpeg/ffprobe cannot be located."""


@dataclass(frozen=True)
class FFmpegBinaries:
    ffmpeg: Path
    ffprobe: Path


def default_threads() -> int:
    """A balanced default so a batch run does not pin every core."""

    cores = os.cpu_count() or 4
    return max(2, min(8, cores // 2))


def configure_cpu_limits(threads: int) -> None:
    """Set BLAS/OpenMP thread caps before heavy numeric work where possible."""

    if threads <= 0:
        return
    value = str(max(1, int(threads)))
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ.setdefault(name, value)


def set_low_priority() -> None:
    """Lower the current process priority. Child FFmpeg processes inherit it."""

    if os.name == "nt":
        try:
            import ctypes

            BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetPriorityClass(handle, BELOW_NORMAL_PRIORITY_CLASS)
        except Exception:
            pass
    else:
        try:
            os.nice(10)
        except Exception:
            pass


@dataclass
class DetectionSettings:
    """Tunables for the hybrid highlight detector."""

    sensitivity: float = 0.5
    pre: float = 8.0
    post: float = 5.0
    min_clip: float = 3.0
    max_clips: int = 30
    audio_weight: float = 0.6
    visual_weight: float = 0.4
    sample_fps: float = 4.0
    merge_gap: float = 1.0
    preview: bool = True
    threads: int = field(default_factory=default_threads)
    proxy_width: int = 320
    gpu: bool = False
    low_power: bool = False
    ai: bool = False
    ai_model: str = "qwen2.5vl:7b"
    ai_game: str = "generic"
    ai_mode: str = "director"
    ai_min_confidence: float = 0.55
    ai_max_candidates: int = 60
    game_guard: Callable[[], str | None] | None = field(
        default=None, repr=False, compare=False
    )

    def validate(self) -> None:
        if not 0.0 <= self.sensitivity <= 1.0:
            raise ValueError("sensitivity must be between 0 and 1")
        if self.pre < 0 or self.post < 0:
            raise ValueError("pre/post padding cannot be negative")
        if self.min_clip < 0.5:
            raise ValueError("min_clip must be at least 0.5 seconds")
        if self.max_clips < 1:
            raise ValueError("max_clips must be at least 1")
        if self.audio_weight < 0 or self.visual_weight < 0:
            raise ValueError("detector weights cannot be negative")
        if self.audio_weight + self.visual_weight <= 0:
            raise ValueError("at least one detector weight must be positive")
        if not 1.0 <= self.sample_fps <= 30.0:
            raise ValueError("sample_fps must be between 1 and 30")
        if self.threads < 0:
            raise ValueError("threads cannot be negative")
        if not 160 <= self.proxy_width <= 1280:
            raise ValueError("proxy_width must be between 160 and 1280")
        if not 0.0 <= self.ai_min_confidence <= 1.0:
            raise ValueError("ai_min_confidence must be between 0 and 1")
        if not 1 <= self.ai_max_candidates <= 200:
            raise ValueError("ai_max_candidates must be between 1 and 200")
        if self.ai_mode not in {"director", "review"}:
            raise ValueError("ai_mode must be 'director' or 'review'")
        self.min_clip = float(self.min_clip)
        self.max_clips = int(self.max_clips)
        self.sample_fps = float(self.sample_fps)
        self.threads = int(self.threads)
        self.proxy_width = int(self.proxy_width)

    def apply_low_power(self) -> "DetectionSettings":
        self.low_power = True
        self.threads = 2
        self.sample_fps = min(self.sample_fps, 2.0)
        self.proxy_width = min(self.proxy_width, 256)
        set_low_priority()
        configure_cpu_limits(self.threads)
        return self

    def normalized_weights(self) -> tuple[float, float]:
        total = self.audio_weight + self.visual_weight
        return self.audio_weight / total, self.visual_weight / total


def _env_binary(name: str) -> Path | None:
    raw = os.environ.get("CLIPPER_FFMPEG") or os.environ.get("FFMPEG_PATH")
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if candidate.is_dir():
        candidate = candidate / name
    if candidate.is_file():
        return candidate
    return None


def _candidate_dirs() -> list[Path]:
    dirs: list[Path] = []

    # Portable/frozen builds ship ffmpeg next to the executable.
    try:
        exe_dir = Path(sys.executable).resolve().parent
        bundle_dir = Path(getattr(sys, "_MEIPASS", exe_dir))
        dirs.extend(
            [
                exe_dir,
                exe_dir / "bin",
                exe_dir / "ffmpeg" / "bin",
                bundle_dir,
                bundle_dir / "bin",
            ]
        )
    except (OSError, RuntimeError):
        pass

    for raw in (
        os.environ.get("CLIPPER_FFMPEG_DIR"),
        os.environ.get("FFMPEG_DIR"),
    ):
        if raw:
            dirs.append(Path(raw).expanduser())

    home = Path.home()
    dirs.extend(
        [
            home / "tools" / "ffmpeg" / "bin",
            home / "ffmpeg" / "bin",
            Path("/usr/local/bin"),
            Path("/usr/bin"),
            Path("/opt/homebrew/bin"),
            Path("C:/ffmpeg/bin"),
            Path("C:/Program Files/ffmpeg/bin"),
        ]
    )
    return dirs


@lru_cache(maxsize=1)
def find_ffmpeg() -> FFmpegBinaries:
    """Locate ffmpeg and ffprobe from env vars, PATH, or common install dirs."""

    for name in ("ffmpeg", "ffmpeg.exe"):
        env_hit = _env_binary(name)
        if env_hit:
            probe = env_hit.with_name("ffprobe.exe" if env_hit.suffix == ".exe" else "ffprobe")
            if probe.is_file():
                return FFmpegBinaries(env_hit, probe)

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        return FFmpegBinaries(Path(ffmpeg), Path(ffprobe))

    for directory in _candidate_dirs():
        for exe in ("ffmpeg.exe", "ffmpeg"):
            ff = directory / exe
            if not ff.is_file():
                continue
            probe = directory / ("ffprobe.exe" if exe.endswith(".exe") else "ffprobe")
            if probe.is_file():
                return FFmpegBinaries(ff, probe)

    raise FFmpegNotFound(
        "ffmpeg/ffprobe not found. Install FFmpeg and add it to PATH, or set "
        "CLIPPER_FFMPEG to the full path of the ffmpeg executable.\n"
        "Windows: winget install Gyan.FFmpeg\n"
        "macOS:   brew install ffmpeg\n"
        "Linux:   sudo apt install ffmpeg"
    )
