from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from clipper.detect import llama_runtime
from clipper.detect.llama_runtime import (
    LFM3_OMNI_2B,
    LlamaServer,
    ModelFile,
    model_ready,
    model_spec,
    openai_chat,
)


def test_model_aliases_resolve_to_the_registry_id() -> None:
    assert model_spec("lfm3-omni").id == "lfm3-omni-2b"
    assert model_spec("lfm3-omni:latest").id == "lfm3-omni-2b"
    assert model_spec("gemma4:12b").id == "gemma4-12b"
    assert model_spec("minicpm-o-4_5").id == "minicpm-o-4.5"


def test_model_ready_requires_every_file_and_a_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = replace(
        LFM3_OMNI_2B,
        id="test-model",
        files=(
            ModelFile("model", "model.gguf", "https://example/model", "", 4),
            ModelFile("mmproj", "mmproj.gguf", "https://example/mmproj", "", 5),
        ),
    )
    target = tmp_path / spec.id
    target.mkdir()
    monkeypatch.setattr(llama_runtime, "model_dir", lambda _spec: target)
    (target / "model.gguf").write_bytes(b"1234")
    (target / "mmproj.gguf").write_bytes(b"12345")
    assert model_ready(spec) is False
    (target / ".ready").write_text("ok", encoding="utf-8")
    assert model_ready(spec) is True
    (target / "mmproj.gguf").write_bytes(b"1234")
    assert model_ready(spec) is False


class _FakeProcess:
    def poll(self):
        return None


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, *args):
        return json.dumps(self.payload).encode("utf-8")


def test_openai_chat_sends_images_audio_and_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    def fake_urlopen(request, timeout=0):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(
            {"choices": [{"message": {"content": '{"ok": true}'}}]}
        )

    monkeypatch.setattr(llama_runtime.urllib.request, "urlopen", fake_urlopen)
    server = LlamaServer(
        spec=LFM3_OMNI_2B,
        port=12345,
        process=_FakeProcess(),  # type: ignore[arg-type]
        log_path=tmp_path / "server.log",
    )
    text = openai_chat(
        server,
        "watch this",
        images=[b"jpeg"],
        audio=b"wav",
        max_tokens=123,
        json_mode=True,
    )
    assert text == '{"ok": true}'
    payload = captured["payload"]
    assert payload["max_tokens"] == 123
    assert payload["response_format"] == {"type": "json_object"}
    content = payload["messages"][0]["content"]
    assert content[0]["type"] == "image_url"
    assert content[1]["type"] == "input_audio"
    assert content[2] == {"type": "text", "text": "watch this"}


def test_runtime_stages_msvc_runtime_beside_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "runtime"
    source.mkdir()
    target.mkdir()
    for name in llama_runtime.RUNTIME_DLLS:
        (source / name).write_bytes(b"dll")
    monkeypatch.setattr(
        llama_runtime, "_runtime_dll_sources", lambda: [source]
    )
    llama_runtime._stage_runtime_dlls(target)
    for name in llama_runtime.RUNTIME_DLLS:
        assert (target / name).read_bytes() == b"dll"

def test_download_failure_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llama_runtime.time, "sleep", lambda _seconds: None)
    with pytest.raises(RuntimeError, match="Download failed"):
        llama_runtime._download(
            "http://127.0.0.1:9/missing",
            tmp_path / "missing.bin",
            timeout=0.2,
        )

class _FakeProcess:
    def __init__(self, stdout=None, text: str = "") -> None:
        self._stdout = stdout
        self.terminated = False
        if stdout is not None and text:
            stdout.write(text)
            stdout.flush()

    def poll(self):
        return None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self) -> None:
        self.terminated = True


def _prepare_start_server(monkeypatch, tmp_path: Path):
    from clipper.gpu import GpuMemory, VramCheck

    snapshot = GpuMemory(
        index=0,
        name="RTX 3080",
        uuid="GPU-0",
        total_mb=10240,
        used_mb=1024,
        free_mb=9216,
    )
    monkeypatch.setattr(llama_runtime, "runtime_ready", lambda: True)
    monkeypatch.setattr(llama_runtime, "model_ready", lambda _spec: True)
    monkeypatch.setattr(llama_runtime, "runtime_server", lambda: tmp_path / "llama-server.exe")
    monkeypatch.setattr(llama_runtime, "_stage_runtime_dlls", lambda _root: None)
    monkeypatch.setattr(
        llama_runtime,
        "model_paths",
        lambda _spec: {"model": tmp_path / "model.gguf"},
    )
    monkeypatch.setattr(llama_runtime, "model_dir", lambda _spec: tmp_path)
    monkeypatch.setattr(llama_runtime, "_free_port", lambda: 12345)
    monkeypatch.setattr(
        llama_runtime,
        "check_vram",
        lambda expected_mb, **kwargs: VramCheck(
            memory=snapshot,
            expected_mb=expected_mb,
            reserve_mb=1024,
            label=kwargs.get("label", "model"),
        ),
    )
    monkeypatch.setattr(llama_runtime, "_SERVERS", {})
    return snapshot


def test_start_server_retries_once_after_cuda_oom(monkeypatch, tmp_path: Path) -> None:
    snapshot = _prepare_start_server(monkeypatch, tmp_path)
    health = iter([False, True])
    calls = []

    def fake_popen(_command, **kwargs):
        text = "CUDA error: out of memory\n" if not calls else "ready\n"
        calls.append(True)
        return _FakeProcess(kwargs.get("stdout"), text)

    monkeypatch.setattr(llama_runtime.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(llama_runtime, "_health", lambda *a, **k: next(health))
    monkeypatch.setattr(
        llama_runtime, "wait_for_vram_recovery", lambda *a, **k: snapshot
    )
    try:
        server = llama_runtime.start_server(LFM3_OMNI_2B)
        assert server.spec.id == LFM3_OMNI_2B.id
        assert len(calls) == 2
        assert llama_runtime.active_server(LFM3_OMNI_2B.id) is server
    finally:
        llama_runtime.stop_server()


def test_start_server_reports_oom_after_one_retry(monkeypatch, tmp_path: Path) -> None:
    from clipper.gpu import VramError

    _prepare_start_server(monkeypatch, tmp_path)
    calls = []

    def fake_popen(_command, **kwargs):
        calls.append(True)
        return _FakeProcess(kwargs.get("stdout"), "CUDA error: out of memory\n")

    monkeypatch.setattr(llama_runtime.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(llama_runtime, "_health", lambda *a, **k: False)
    monkeypatch.setattr(
        llama_runtime, "wait_for_vram_recovery", lambda *a, **k: None
    )
    with pytest.raises(VramError, match="out of GPU memory"):
        llama_runtime.start_server(LFM3_OMNI_2B)
    assert len(calls) == 2
    assert llama_runtime.active_server(LFM3_OMNI_2B.id) is None


def test_start_server_rejects_insufficient_free_vram(monkeypatch, tmp_path: Path) -> None:
    from clipper.gpu import GpuMemory, VramCheck, VramError

    monkeypatch.setattr(llama_runtime, "runtime_ready", lambda: True)
    monkeypatch.setattr(llama_runtime, "model_ready", lambda _spec: True)
    monkeypatch.setattr(llama_runtime, "runtime_server", lambda: tmp_path / "llama-server.exe")
    monkeypatch.setattr(llama_runtime, "_stage_runtime_dlls", lambda _root: None)
    monkeypatch.setattr(
        llama_runtime,
        "model_paths",
        lambda _spec: {"model": tmp_path / "model.gguf"},
    )
    snapshot = GpuMemory(
        index=0,
        name="RTX 3080",
        uuid="GPU-0",
        total_mb=10240,
        used_mb=7000,
        free_mb=3240,
    )
    monkeypatch.setattr(
        llama_runtime,
        "check_vram",
        lambda expected_mb, **kwargs: VramCheck(
            memory=snapshot,
            expected_mb=expected_mb,
            reserve_mb=1024,
            label=kwargs.get("label", "model"),
        ),
    )
    monkeypatch.setattr(llama_runtime, "_SERVERS", {})
    with pytest.raises(VramError, match="Insufficient free VRAM"):
        llama_runtime.start_server(LFM3_OMNI_2B)
    assert llama_runtime.active_server(LFM3_OMNI_2B.id) is None


def test_start_server_reuses_an_active_server(monkeypatch, tmp_path: Path) -> None:
    _prepare_start_server(monkeypatch, tmp_path)
    calls = []

    def fake_popen(_command, **kwargs):
        calls.append(True)
        return _FakeProcess(kwargs.get("stdout"), "ready\n")

    monkeypatch.setattr(llama_runtime.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(llama_runtime, "_health", lambda *a, **k: True)
    try:
        first = llama_runtime.start_server(LFM3_OMNI_2B)
        second = llama_runtime.start_server(LFM3_OMNI_2B)
        assert first is second
        assert len(calls) == 1
    finally:
        llama_runtime.stop_server()


def test_start_server_requires_a_random_api_key(monkeypatch, tmp_path: Path) -> None:
    _prepare_start_server(monkeypatch, tmp_path)
    commands = []

    def fake_popen(command, **kwargs):
        commands.append(command)
        return _FakeProcess()

    monkeypatch.setattr(llama_runtime.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(llama_runtime, "_health", lambda *a, **k: True)
    server = llama_runtime.start_server(LFM3_OMNI_2B)
    command = commands[0]
    assert command[command.index("--host") + 1] == "127.0.0.1"
    key = command[command.index("--api-key") + 1]
    assert key == server.api_key and len(key) >= 32
    llama_runtime._SERVERS.clear()


def test_openai_chat_sends_the_server_api_key(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout=0):
        captured["auth"] = request.get_header("Authorization")
        return _FakeResponse({"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr(llama_runtime.urllib.request, "urlopen", fake_urlopen)
    server = LlamaServer(
        spec=LFM3_OMNI_2B,
        port=1,
        process=_FakeProcess(),  # type: ignore[arg-type]
        log_path=tmp_path / "server.log",
        api_key="secret-key",
    )
    openai_chat(server, "hi")
    assert captured["auth"] == "Bearer secret-key"
