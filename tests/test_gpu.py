from __future__ import annotations

import types

import pytest

from clipper import gpu
from clipper.detect.llama_runtime import (
    GEMMA_4_12B,
    LFM3_OMNI_2B,
    MINICPM_O_4_5,
    expected_runtime_mb,
)


def memory(
    *,
    index: int = 0,
    total: int = 10240,
    used: int = 0,
    free: int | None = None,
) -> gpu.GpuMemory:
    if free is None:
        free = total - used
    return gpu.GpuMemory(
        index=index,
        name="NVIDIA GeForce RTX 3080",
        uuid=f"GPU-{index}",
        total_mb=total,
        used_mb=used,
        free_mb=free,
    )


def test_model_runtime_allocations_are_measured_mib() -> None:
    assert expected_runtime_mb(LFM3_OMNI_2B) == 3000
    assert expected_runtime_mb(MINICPM_O_4_5) == 6600
    assert expected_runtime_mb(GEMMA_4_12B) == 8100


def test_selected_gpu_respects_cuda_visible_devices(monkeypatch) -> None:
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    assert gpu.selected_gpu_selector() == 0
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1,0")
    assert gpu.selected_gpu_selector() == 1
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "-1")
    assert gpu.selected_gpu_selector() is None
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-abc")
    assert gpu.selected_gpu_selector() == "GPU-abc"


def test_nvidia_query_selects_index_and_uuid(monkeypatch) -> None:
    output = (
        "0, NVIDIA GeForce RTX 3080, GPU-aaa, 10240, 1039, 9201\n"
        "1, NVIDIA GeForce RTX 4090, GPU-bbb, 24564, 1000, 23564\n"
    )
    monkeypatch.setattr(gpu.shutil, "which", lambda _name: "nvidia-smi")
    monkeypatch.setattr(
        gpu.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(
            returncode=0, stdout=output, stderr=""
        ),
    )
    first = gpu.query_nvidia_memory(selector=0)
    second = gpu.query_nvidia_memory(selector=1)
    by_uuid = gpu.query_nvidia_memory(selector="GPU-BBB")
    assert first is not None and first.index == 0 and first.free_mb == 9201
    assert second is not None and second.index == 1 and second.total_mb == 24564
    assert by_uuid is not None and by_uuid.index == 1
    assert gpu.query_nvidia_memory(selector=None) is None


def test_nvidia_query_handles_failures_and_invalid_rows(monkeypatch) -> None:
    monkeypatch.setattr(gpu.shutil, "which", lambda _name: "nvidia-smi")
    monkeypatch.setattr(
        gpu.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(
            returncode=1, stdout="", stderr="no devices"
        ),
    )
    assert gpu.query_nvidia_memory(selector=0) is None
    monkeypatch.setattr(
        gpu.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(
            returncode=0,
            stdout="0, GPU, uuid, [N/A], 100, 100\nbroken\n",
            stderr="",
        ),
    )
    assert gpu.query_nvidia_memory(selector=0) is None


def test_check_vram_accounts_for_free_memory_and_reserve() -> None:
    ten_gb_full = memory(total=10240, free=10240)
    both = gpu.check_vram(
        9600, label="vision and audio models", memory=ten_gb_full
    )
    assert both.known
    assert both.fits is False
    assert both.required_mb == 10624
    assert "10240 MiB free" in both.message
    assert "1024 MiB reserve" in both.message

    single = gpu.check_vram(3000, label="LFM3", memory=ten_gb_full)
    assert single.fits is True

    game = memory(total=10240, used=3500, free=6740)
    heavy = gpu.check_vram(6600, label="MiniCPM", memory=game)
    assert heavy.fits is False
    light = gpu.check_vram(3000, label="LFM3", memory=game)
    assert light.fits is True

    sixteen = memory(total=16384, free=15000)
    assert gpu.check_vram(9600, memory=sixteen).fits is True
    assert gpu.check_vram(4000, memory=sixteen).fits is True

    unknown = gpu.check_vram(3000, memory=None)
    assert unknown.known is False
    assert unknown.fits is None


def test_wait_for_vram_recovery_returns_when_memory_increases(monkeypatch) -> None:
    values = iter(
        [
            memory(total=10240, used=9000, free=1240),
            memory(total=10240, used=4000, free=6240),
        ]
    )
    monkeypatch.setattr(gpu, "query_nvidia_memory", lambda *a, **k: next(values))
    monkeypatch.setattr(gpu.time, "sleep", lambda _seconds: None)
    result = gpu.wait_for_vram_recovery(1240, timeout=1.0, interval=0.01)
    assert result is not None
    assert result.free_mb == 6240


def test_wait_for_vram_recovery_is_bounded_when_memory_does_not_return(
    monkeypatch,
) -> None:
    snapshot = memory(total=10240, used=9000, free=1240)
    monkeypatch.setattr(gpu, "query_nvidia_memory", lambda *a, **k: snapshot)
    monkeypatch.setattr(gpu.time, "sleep", lambda _seconds: None)
    result = gpu.wait_for_vram_recovery(1240, timeout=0.01, interval=0.001)
    assert result is not None
    assert result.free_mb == 1240


def test_wait_for_vram_recovery_handles_missing_telemetry(monkeypatch) -> None:
    monkeypatch.setattr(gpu, "query_nvidia_memory", lambda *a, **k: None)
    assert gpu.wait_for_vram_recovery(1240, timeout=0.01) is None


def test_oom_text_detection() -> None:
    assert gpu.is_oom_text("CUDA error: out of memory")
    assert gpu.is_oom_text("failed to allocate 2048 MiB")
    assert gpu.is_oom_text("cudaMalloc failed")
    assert not gpu.is_oom_text("model file not found")

def test_nvidia_memory_mb_uses_selected_snapshot(monkeypatch) -> None:
    from clipper import ffmpeg

    monkeypatch.setattr(gpu, "query_nvidia_memory", lambda: memory(total=24564))
    assert ffmpeg.nvidia_memory_mb() == 24564

def test_check_vram_16gb_external_workload_matrix() -> None:
    pair = 6600 + 3000
    assert gpu.check_vram(pair, memory=memory(total=16384, free=15000)).fits
    assert not gpu.check_vram(pair, memory=memory(total=16384, free=9000)).fits
    assert gpu.check_vram(6600, memory=memory(total=16384, free=9000)).fits
    assert not gpu.check_vram(6600, memory=memory(total=16384, free=6000)).fits


def test_check_vram_24gb_external_workload_matrix() -> None:
    pair = 6600 + 3000
    assert gpu.check_vram(pair, memory=memory(total=24564, free=20468)).fits
    assert not gpu.check_vram(pair, memory=memory(total=24564, free=8000)).fits
    assert gpu.check_vram(6600, memory=memory(total=24564, free=8000)).fits
    assert not gpu.check_vram(6600, memory=memory(total=24564, free=5000)).fits
