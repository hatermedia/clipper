from __future__ import annotations

import hashlib
import io
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from clipper import ai_setup


class _InstallerHandler(BaseHTTPRequestHandler):
    payload = b""

    def do_GET(self) -> None:  # noqa: N802
        data = self.payload
        start = 0
        header = self.headers.get("Range")
        if header and header.startswith("bytes="):
            try:
                start = int(header.split("=", 1)[1].split("-", 1)[0])
            except ValueError:
                start = 0
        body = data[start:]
        self.send_response(206 if start else 200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        if start:
            self.send_header(
                "Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}"
            )
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture()
def installer_server():
    payload = (b"official-looking ollama installer " * 4096) + b"end"
    handler = type("Handler", (_InstallerHandler,), {"payload": payload})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, payload
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _release(server: ThreadingHTTPServer, payload: bytes, sha: str | None = None):
    host, port = server.server_address
    return ai_setup.OllamaRelease(
        version="test",
        url=f"http://{host}:{port}/OllamaSetup.exe",
        size=len(payload),
        sha256=sha if sha is not None else hashlib.sha256(payload).hexdigest(),
    )


def test_fetch_latest_release_reads_the_official_asset(monkeypatch) -> None:
    payload = {
        "tag_name": "v9.9.9",
        "assets": [
            {
                "name": "OllamaSetup.exe",
                "size": 123456,
                "digest": "sha256:" + "a" * 64,
                "browser_download_url": (
                    "https://github.com/ollama/ollama/releases/download/v9.9.9/"
                    "OllamaSetup.exe"
                ),
            }
        ],
    }
    monkeypatch.setattr(
        ai_setup.urllib.request,
        "urlopen",
        lambda *args, **kwargs: io.BytesIO(json.dumps(payload).encode()),
    )
    release = ai_setup.fetch_latest_release()
    assert release.version == "9.9.9"
    assert release.size == 123456
    assert release.sha256 == "a" * 64
    assert release.filename == "OllamaSetup.exe"


def test_fetch_latest_release_rejects_untrusted_asset_url(monkeypatch) -> None:
    payload = {
        "tag_name": "v9.9.9",
        "assets": [
            {
                "name": "OllamaSetup.exe",
                "size": 123456,
                "digest": "sha256:" + "a" * 64,
                "browser_download_url": "https://example.com/OllamaSetup.exe",
            }
        ],
    }
    monkeypatch.setattr(
        ai_setup.urllib.request,
        "urlopen",
        lambda *args, **kwargs: io.BytesIO(json.dumps(payload).encode()),
    )
    with pytest.raises(ai_setup.AISetupError, match="official GitHub"):
        ai_setup.fetch_latest_release()


def test_resolve_release_falls_back_to_the_official_latest_url(monkeypatch) -> None:
    def fail():
        raise ai_setup.AISetupError("rate limited")

    monkeypatch.setattr(ai_setup, "fetch_latest_release", fail)
    release = ai_setup.resolve_release()
    assert release.url == ai_setup.OLLAMA_DIRECT_URL
    assert release.sha256 is None


def test_download_resumes_and_verifies(installer_server, tmp_path, monkeypatch) -> None:
    server, payload = installer_server
    release = _release(server, payload)
    monkeypatch.setattr(ai_setup, "verify_authenticode", lambda _path: (True, "test"))
    partial = tmp_path / "OllamaSetup.exe.part"
    partial.write_bytes(payload[: len(payload) // 2])
    progress: list[tuple[int, int]] = []

    result = ai_setup.download_installer(
        release,
        destination=tmp_path,
        progress=lambda done, total: progress.append((done, total)),
    )

    assert result.read_bytes() == payload
    assert not partial.exists()
    assert progress[-1] == (len(payload), len(payload))


def test_download_deletes_a_checksum_mismatch(installer_server, tmp_path, monkeypatch) -> None:
    server, payload = installer_server
    release = _release(server, payload, sha="0" * 64)
    monkeypatch.setattr(ai_setup, "verify_authenticode", lambda _path: (True, "test"))

    with pytest.raises(ai_setup.AISetupError, match="checksum"):
        ai_setup.download_installer(release, destination=tmp_path)

    assert not (tmp_path / "OllamaSetup.exe").exists()
    assert not (tmp_path / "OllamaSetup.exe.part").exists()


def test_download_can_be_cancelled(installer_server, tmp_path, monkeypatch) -> None:
    server, payload = installer_server
    release = _release(server, payload)
    monkeypatch.setattr(ai_setup, "verify_authenticode", lambda _path: (True, "test"))

    with pytest.raises(ai_setup.AISetupCancelled):
        ai_setup.download_installer(
            release, destination=tmp_path, cancelled=lambda: True
        )

    assert not (tmp_path / "OllamaSetup.exe").exists()


def test_ollama_executable_uses_the_per_user_install(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ai_setup.shutil, "which", lambda _name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    executable = tmp_path / "Programs" / "Ollama" / "ollama.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"")
    assert ai_setup.ollama_executable() == executable


def test_install_prerequisite_removes_the_downloaded_installer(tmp_path, monkeypatch) -> None:
    installer = tmp_path / "OllamaSetup.exe"
    installer.write_bytes(b"setup")
    release = ai_setup.OllamaRelease("test", "https://github.com/x", 5, None)
    monkeypatch.setattr(ai_setup, "resolve_release", lambda: release)
    monkeypatch.setattr(
        ai_setup, "download_installer", lambda *_args, **_kwargs: installer
    )
    monkeypatch.setattr(ai_setup, "install_ollama", lambda _installer: Path("ollama.exe"))
    monkeypatch.setattr(ai_setup, "_kill_image", lambda _name: None)
    monkeypatch.setattr(
        ai_setup, "_mark_ollama_onboarding_complete", lambda: None
    )
    monkeypatch.setattr(ai_setup.time, "sleep", lambda _seconds: None)
    messages: list[str] = []

    result = ai_setup.install_prerequisite(status=messages.append)

    assert result == Path("ollama.exe")
    assert not installer.exists()
    assert any("starting" in message.lower() for message in messages)


@pytest.mark.skipif(os.name != "nt", reason="Windows installer behavior")
def test_install_ollama_uses_silent_per_user_flags(tmp_path, monkeypatch) -> None:
    installer = tmp_path / "OllamaSetup.exe"
    installer.write_bytes(b"setup")
    calls: list[list[str]] = []

    class Process:
        returncode = 0

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    def fake_popen(args, **_kwargs):
        calls.append(list(args))
        return Process()

    executable = tmp_path / "Programs" / "Ollama" / "ollama.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"")
    monkeypatch.setattr(ai_setup.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ai_setup, "_kill_image", lambda _name: None)
    monkeypatch.setattr(
        ai_setup, "_mark_ollama_onboarding_complete", lambda: None
    )
    monkeypatch.setattr(ai_setup, "ollama_executable", lambda: executable)
    monkeypatch.setattr(ai_setup.time, "sleep", lambda _seconds: None)

    result = ai_setup.install_ollama(installer)

    assert result == executable
    assert calls and calls[0][0] == str(installer)
    assert "/VERYSILENT" in calls[0]
    assert "/NORESTART" in calls[0]
    assert "/SP-" in calls[0]
