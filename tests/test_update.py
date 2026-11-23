from __future__ import annotations

import hashlib
import http.server
import threading
from pathlib import Path

import pytest

from clipper import update


def test_version_compare() -> None:
    assert update.version_is_newer("0.3.0", "0.2.1")
    assert update.version_is_newer("v0.3", "0.2.9")
    assert not update.version_is_newer("0.3.0", "0.3.0")
    assert not update.version_is_newer("0.2", "0.2.0")
    assert update.parse_version("v1.2.3-beta") == (1, 2, 3)


def test_parse_checksums() -> None:
    digest = "a" * 64
    parsed = update.parse_checksums(
        f"{digest}  ClipperSetup-0.3.0.exe\r\n{'b' * 64} *other.zip\nnot a line"
    )
    assert parsed["clippersetup-0.3.0.exe"] == digest
    assert parsed["other.zip"] == "b" * 64
    assert len(parsed) == 2


def test_release_payload_selects_installer_and_checksums() -> None:
    payload = {
        "tag_name": "v0.3.0",
        "name": "v0.3.0",
        "html_url": "https://example.test/release",
        "published_at": "2026-11-24T00:00:00Z",
        "assets": [
            {"name": "notes.txt", "browser_download_url": "https://example.test/notes"},
            {
                "name": "ClipperSetup-0.3.0.exe",
                "browser_download_url": "https://example.test/setup",
                "size": 1234,
            },
            {
                "name": "SHA256SUMS.txt",
                "browser_download_url": "https://example.test/sums",
                "size": 200,
            },
        ],
    }
    release = update._release_from_payload(payload)
    assert release.version == "0.3.0"
    assert release.has_installer
    assert release.has_checksums
    assert release.installer_size == 1234


def test_release_without_installer_has_no_download() -> None:
    release = update._release_from_payload(
        {"tag_name": "v0.4.0", "assets": [{"name": "source.tar.gz"}]}
    )
    assert not release.has_installer


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(kwargs.pop("directory")), **kwargs)

    def log_message(self, *args):
        pass


def test_download_verifies_checksum(tmp_path: Path) -> None:
    payload = b"installer" * 4096
    installer = tmp_path / "ClipperSetup-9.9.9.exe"
    installer.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (tmp_path / "SHA256SUMS.txt").write_text(
        f"{digest}  {installer.name}\n", encoding="ascii"
    )

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        lambda *args, **kwargs: _Handler(
            *args, directory=str(tmp_path), **kwargs
        ),
    )
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        release = update.ReleaseInfo(
            version="9.9.9",
            tag="v9.9.9",
            name="v9.9.9",
            notes="",
            page_url="https://example.test",
            published_at="",
            installer_name=installer.name,
            installer_url=f"http://127.0.0.1:{port}/{installer.name}",
            installer_size=len(payload),
            checksums_name="SHA256SUMS.txt",
            checksums_url=f"http://127.0.0.1:{port}/SHA256SUMS.txt",
        )
        target = tmp_path / "download" / installer.name
        result = update.download_installer(release, target)
        assert result.read_bytes() == payload

        (tmp_path / "SHA256SUMS.txt").write_text(
            f"{'0' * 64}  {installer.name}\n", encoding="ascii"
        )
        with pytest.raises(update.UpdateError, match="SHA-256"):
            update.download_installer(release, tmp_path / "bad" / installer.name)
    finally:
        server.shutdown()
        server.server_close()
