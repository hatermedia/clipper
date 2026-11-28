"""NVIDIA GPU memory telemetry and VRAM headroom decisions.

All values are MiB. This module deliberately uses nvidia-smi rather than a
large GPU dependency. It respects CUDA_VISIBLE_DEVICES so the check follows the
same GPU that a llama.cpp child process will use.
"""

from __future__ import annotations

import csv
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

RESERVE_MB = 1024
_RECOVERY_STEP_MB = 128
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_UNSET = object()


class VramError(RuntimeError):
    """Raised when a model cannot safely start because GPU memory is low."""


@dataclass(frozen=True)
class GpuMemory:
    index: int
    name: str
    uuid: str
    total_mb: int
    used_mb: int
    free_mb: int


@dataclass(frozen=True)
class VramCheck:
    memory: GpuMemory | None
    expected_mb: int
    reserve_mb: int = RESERVE_MB
    label: str = "model"

    @property
    def known(self) -> bool:
        return self.memory is not None

    @property
    def total_mb(self) -> int | None:
        return self.memory.total_mb if self.memory is not None else None

    @property
    def used_mb(self) -> int | None:
        return self.memory.used_mb if self.memory is not None else None

    @property
    def free_mb(self) -> int | None:
        return self.memory.free_mb if self.memory is not None else None

    @property
    def required_mb(self) -> int:
        return max(0, int(self.expected_mb)) + max(0, int(self.reserve_mb))

    @property
    def fits(self) -> bool | None:
        if self.memory is None:
            return None
        return (
            self.memory.total_mb >= self.required_mb
            and self.memory.free_mb >= self.required_mb
        )

    @property
    def message(self) -> str:
        if self.memory is None:
            return (
                f"GPU memory availability could not be verified for "
                f"{self.label}."
            )
        state = (
            f"GPU {self.memory.index} ({self.memory.name}) has "
            f"{self.memory.free_mb} MiB free; {self.label} needs about "
            f"{self.expected_mb} MiB plus a {self.reserve_mb} MiB reserve."
        )
        if self.fits:
            return state + " Enough memory is available."
        return state + " Not enough free VRAM."


def selected_gpu_selector() -> int | str | None:
    """Return the GPU index, UUID, or None for CPU selected by CUDA_VISIBLE_DEVICES.

    llama.cpp uses the first visible CUDA device. An unset or empty variable
    means the default GPU 0. A value of -1 means no CUDA device.
    """

    raw = os.environ.get("CUDA_VISIBLE_DEVICES")
    if raw is None or not raw.strip():
        return 0
    first = raw.split(",")[0].strip()
    if not first:
        return 0
    if first.lower() in {"-1", "none", "nodevfiles"}:
        return None
    if first.isdigit():
        return int(first)
    return first


def _parse_nvidia_memory_output(text: str) -> list[GpuMemory]:
    devices: list[GpuMemory] = []
    for row in csv.reader(text.splitlines()):
        if len(row) < 6:
            continue
        index, name, uuid, total, used, free = [
            value.strip() for value in row[:6]
        ]
        if not index.isdigit():
            continue
        if not (total.isdigit() and used.isdigit() and free.isdigit()):
            continue
        devices.append(
            GpuMemory(
                index=int(index),
                name=name,
                uuid=uuid,
                total_mb=int(total),
                used_mb=int(used),
                free_mb=int(free),
            )
        )
    return devices


def nvidia_smi_path() -> str | None:
    """Locate nvidia-smi, preferring the driver's System32 copy over PATH."""

    if os.name == "nt":
        system_root = os.environ.get("SystemRoot") or r"C:\Windows"
        candidate = Path(system_root) / "System32" / "nvidia-smi.exe"
        if candidate.is_file():
            return str(candidate)
    return shutil.which("nvidia-smi")


def query_nvidia_memory(
    selector: int | str | None | object = _UNSET,
) -> GpuMemory | None:
    """Query live memory for the selected NVIDIA GPU, or None if unavailable."""

    chosen = selected_gpu_selector() if selector is _UNSET else selector
    if chosen is None:
        return None
    smi = nvidia_smi_path()
    if not smi:
        return None
    try:
        proc = subprocess.run(
            [
                smi,
                "--query-gpu=index,name,uuid,memory.total,memory.used,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    devices = _parse_nvidia_memory_output(proc.stdout or "")
    for device in devices:
        if isinstance(chosen, int) and device.index == chosen:
            return device
        if isinstance(chosen, str) and device.uuid.lower() == chosen.lower():
            return device
    return None


def check_vram(
    expected_mb: int,
    *,
    label: str = "model",
    reserve_mb: int = RESERVE_MB,
    memory: GpuMemory | None | object = _UNSET,
) -> VramCheck:
    """Build a headroom check from a snapshot or a fresh telemetry query."""

    snapshot = query_nvidia_memory() if memory is _UNSET else memory
    return VramCheck(
        memory=snapshot,
        expected_mb=int(expected_mb),
        reserve_mb=int(reserve_mb),
        label=label,
    )


def wait_for_vram_recovery(
    previous_free_mb: int | None,
    *,
    timeout: float = 8.0,
    interval: float = 0.25,
    selector: int | str | None | object = _UNSET,
) -> GpuMemory | None:
    """Wait for freed GPU memory to become visible.

    Returns the latest snapshot, or None when telemetry is unavailable. The
    wait is bounded so a stuck driver or another process cannot block a scan.
    """

    deadline = time.monotonic() + max(0.0, timeout)
    last: GpuMemory | None = None
    while True:
        last = query_nvidia_memory(selector)
        if last is None:
            return None
        if previous_free_mb is None:
            return last
        if last.free_mb >= previous_free_mb + _RECOVERY_STEP_MB:
            return last
        if time.monotonic() >= deadline:
            return last
        time.sleep(max(0.01, interval))


def is_oom_text(text: str) -> bool:
    lowered = (text or "").lower()
    return any(
        marker in lowered
        for marker in (
            "out of memory",
            "failed to allocate",
            "unable to allocate",
            "cudamalloc failed",
            "cuda_error_out_of_memory",
        )
    )
