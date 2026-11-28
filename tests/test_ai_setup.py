from __future__ import annotations

import inspect

from clipper import ai_setup


def test_ollama_executable_uses_the_per_user_install(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ai_setup.shutil, "which", lambda _name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    executable = tmp_path / "Programs" / "Ollama" / "ollama.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"")
    assert ai_setup.ollama_executable() == executable


def test_clipper_never_downloads_installs_or_kills_ollama() -> None:
    source = inspect.getsource(ai_setup)
    assert "taskkill" not in source
    assert "OllamaSetup.exe" not in source
    assert "/VERYSILENT" not in source
    assert "urlopen" not in source


def test_stop_only_touches_the_server_clipper_started(monkeypatch) -> None:
    monkeypatch.setattr(ai_setup, "_SERVER_PROCESS", None)
    ai_setup.stop_ollama_server()  # no process started: must be a no-op
