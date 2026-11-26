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
