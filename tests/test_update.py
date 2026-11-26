from __future__ import annotations

import hashlib
import io
import os
import tempfile
from pathlib import Path

import pytest

from clipper import update


class FakeResponse(io.BytesIO):
    def __init__(
        self,
        payload: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        super().__init__(payload)
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(payload)),
        }

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args) -> None:
        self.close()


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


def test_https_validation_rejects_local_and_plain_http() -> None:
    update._validate_https_url("https://example.test/ClipperSetup-0.7.0.exe")
    for value in (
        "http://example.test/file.exe",
        "file:///C:/temp/file.exe",
        r"\\server\share\file.exe",
        "https://127.0.0.1/file.exe",
        "https://localhost/file.exe",
        "https://user:pass@example.test/file.exe",
        "https://example.test:bad/file.exe",
        "https://example.test:8443/file.exe",
    ):
        with pytest.raises(update.UpdateError):
            update._validate_https_url(value)


def test_release_rejects_unsafe_installer_name_and_url() -> None:
    for name in (
        r"clippersetup-..\..\evil.exe",
        "clippersetup-/evil.exe",
        "clippersetup-C:/evil.exe",
        "ClipperSetup-.exe",
        "ClipperSetup-..exe",
    ):
        payload = {
            "tag_name": "v0.7.0",
            "assets": [
                {
                    "name": name,
                    "browser_download_url": "https://example.test/setup",
                },
                {
                    "name": "SHA256SUMS.txt",
                    "browser_download_url": "https://example.test/sums",
                },
            ],
        }
        with pytest.raises(update.UpdateError):
            update._release_from_payload(payload)

    bad_url = {
        "tag_name": "v0.7.0",
        "assets": [
            {
                "name": "ClipperSetup-0.7.0.exe",
                "browser_download_url": "http://example.test/setup",
            },
            {
                "name": "SHA256SUMS.txt",
                "browser_download_url": "https://example.test/sums",
            },
        ],
    }
    with pytest.raises(update.UpdateError):
        update._release_from_payload(bad_url)


def _release(payload: bytes, *, size: int | None = None) -> update.ReleaseInfo:
    return update.ReleaseInfo(
        version="9.9.9",
        tag="v9.9.9",
        name="v9.9.9",
        notes="",
        page_url="https://example.test",
        published_at="",
        installer_name="ClipperSetup-9.9.9.exe",
        installer_url="https://example.test/ClipperSetup-9.9.9.exe",
        installer_size=len(payload) if size is None else size,
        checksums_name="SHA256SUMS.txt",
        checksums_url="https://example.test/SHA256SUMS.txt",
    )


def _checksum(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_download_verifies_checksum_and_cleans_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"MZ" + b"installer" * 4096
    sums = f"{_checksum(payload)}  ClipperSetup-9.9.9.exe\n"
    monkeypatch.setattr(update, "_fetch_text", lambda *args, **kwargs: sums)
    monkeypatch.setattr(
        update,
        "_open_url",
        lambda *args, **kwargs: FakeResponse(payload),
    )

    target = tmp_path / "download" / "ClipperSetup-9.9.9.exe"
    result = update.download_installer(_release(payload), target)
    assert result.read_bytes() == payload
    assert not target.with_suffix(".exe.part").exists()


def test_download_rejects_bad_checksum(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"MZ" + b"installer" * 4096
    monkeypatch.setattr(
        update,
        "_fetch_text",
        lambda *args, **kwargs: f"{'0' * 64}  ClipperSetup-9.9.9.exe\n",
    )
    monkeypatch.setattr(update, "_open_url", lambda *args, **kwargs: FakeResponse(payload))
    target = tmp_path / "ClipperSetup-9.9.9.exe"
    with pytest.raises(update.UpdateError, match="SHA-256"):
        update.download_installer(_release(payload), target)
    assert not target.with_suffix(".exe.part").exists()


def test_download_rejects_html_and_oversized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"MZ" + b"x" * 128
    sums = f"{_checksum(payload)}  ClipperSetup-9.9.9.exe\n"
    monkeypatch.setattr(update, "_fetch_text", lambda *args, **kwargs: sums)
    monkeypatch.setattr(
        update,
        "_open_url",
        lambda *args, **kwargs: FakeResponse(payload, content_type="text/html"),
    )
    with pytest.raises(update.UpdateError, match="web page"):
        update.download_installer(_release(payload), tmp_path / "a" / "ClipperSetup-9.9.9.exe")

    monkeypatch.setattr(
        update,
        "_open_url",
        lambda *args, **kwargs: FakeResponse(payload),
    )
    with pytest.raises(update.UpdateError, match="size limit"):
        update.download_installer(
            _release(payload, size=update.MAX_INSTALLER_BYTES + 1),
            tmp_path / "b" / "ClipperSetup-9.9.9.exe",
        )


def test_download_rejects_truncated_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"MZ" + b"x" * 128
    sums = f"{_checksum(payload)}  ClipperSetup-9.9.9.exe\n"
    monkeypatch.setattr(update, "_fetch_text", lambda *args, **kwargs: sums)
    monkeypatch.setattr(update, "_open_url", lambda *args, **kwargs: FakeResponse(payload))
    with pytest.raises(update.UpdateError, match="truncated"):
        update.download_installer(
            _release(payload, size=len(payload) + 10),
            tmp_path / "c" / "ClipperSetup-9.9.9.exe",
        )


def test_download_rejects_unsafe_name_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = False

    def fail(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("network should not run")

    monkeypatch.setattr(update, "_fetch_text", fail)
    release = update.ReleaseInfo(
        version="9.9.9",
        tag="v9.9.9",
        name="v9.9.9",
        notes="",
        page_url="https://example.test",
        published_at="",
        installer_name=r"clippersetup-..\..\evil.exe",
        installer_url="https://example.test/setup",
        checksums_name="SHA256SUMS.txt",
        checksums_url="https://example.test/sums",
    )
    with pytest.raises(update.UpdateError, match="Unsafe installer"):
        update.download_installer(release, tmp_path / "evil.exe")
    assert not called


def test_helper_script_enforces_exit_codes_and_unique_dirs() -> None:
    installer = Path(tempfile.gettempdir()) / "clipper-update-abc" / "ClipperSetup-9.9.9.exe"
    helper = update._helper_script(
        installer,
        Path(r"C:\Users\me\AppData\Local\Programs\Clipper\Clipper.exe"),
        Path(r"C:\Users\me\AppData\Local\Clipper\update.log"),
        relaunch=True,
        wait_pid=1234,
    )
    script = "\n".join(helper)
    assert "$proc.ExitCode -ne 0" in script
    assert "exit 91" in script
    assert "exit 92" in script
    assert "WaitForExit($installerTimeoutMs)" in script
    assert "exit 93" in script
    assert "Remove-InstallerDir" in script
    assert "Remove-HelperDir" in script
    assert "$env:TEMP\\clipper-update-*" in script
    assert "Start-Process -FilePath $exe" in script


def test_helper_script_is_valid_powershell(tmp_path: Path) -> None:
    import os
    import subprocess

    if os.name != "nt":
        pytest.skip("PowerShell validation runs on Windows")
    installer = Path(tempfile.gettempdir()) / "clipper-update-abc" / "ClipperSetup-9.9.9.exe"
    script_path = tmp_path / "install.ps1"
    script_path.write_text(
        "\r\n".join(
            update._helper_script(
                installer,
                Path(r"C:\Program Files\Clipper\Clipper.exe"),
                Path(r"C:\Users\me\AppData\Local\Clipper\update.log"),
                relaunch=True,
                wait_pid=1,
            )
        )
        + "\r\n",
        encoding="utf-8",
    )
    validator = tmp_path / "validate.ps1"
    validator.write_text(
        "param([string]$Path)\r\n"
        "$tokens = $null\r\n"
        "$errors = $null\r\n"
        "[System.Management.Automation.Language.Parser]::ParseFile("
        "$Path, [ref]$tokens, [ref]$errors) | Out-Null\r\n"
        "Write-Output $errors.Count\r\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(validator),
            str(script_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0", result.stdout


@pytest.mark.skipif(os.name != "nt", reason="Windows installer path behavior")
def test_launch_installer_rejects_untrusted_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(update.os, "name", "nt")
    fake_temp = tmp_path / "temp"
    fake_temp.mkdir()
    installer = tmp_path / "elsewhere" / "ClipperSetup-9.9.9.exe"
    installer.parent.mkdir()
    installer.write_bytes(b"MZ")
    monkeypatch.setattr(update.tempfile, "gettempdir", lambda: str(fake_temp))
    with pytest.raises(update.UpdateError, match="outside the update temp"):
        update.launch_installer(installer)


@pytest.mark.skipif(os.name != "nt", reason="Windows installer path behavior")
def test_pending_update_round_trip(tmp_path, monkeypatch) -> None:
    state = tmp_path / "update-state.json"
    installer = tmp_path / "ClipperSetup-9.9.9.exe"
    installer.write_bytes(b"MZ installer")
    monkeypatch.setattr(update, "_state_file", lambda: state)
    release = update.ReleaseInfo(
        version="9.9.9",
        tag="v9.9.9",
        name="v9.9.9",
        notes="",
        page_url="https://github.com/hatermedia/clipper/releases/tag/v9.9.9",
        published_at="",
        installer_name="ClipperSetup-9.9.9.exe",
        installer_url="https://github.com/hatermedia/clipper/releases/download/v9.9.9/ClipperSetup-9.9.9.exe",
        installer_size=installer.stat().st_size,
        checksums_name="SHA256SUMS.txt",
        checksums_url="https://github.com/hatermedia/clipper/releases/download/v9.9.9/SHA256SUMS.txt",
    )
    update.save_pending_update(release, installer)
    loaded = update.load_pending_update()
    assert loaded is not None
    assert loaded[0].version == "9.9.9"
    assert loaded[1] == installer
    update.clear_pending_update()
    assert update.load_pending_update() is None


@pytest.mark.skipif(os.name != "nt", reason="Windows installer path behavior")
def test_launch_installer_rejects_non_update_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(update.os, "name", "nt")
    installer = tmp_path / "downloads" / "ClipperSetup-9.9.9.exe"
    installer.parent.mkdir()
    installer.write_bytes(b"MZ")
    monkeypatch.setattr(update.tempfile, "gettempdir", lambda: str(tmp_path))
    with pytest.raises(update.UpdateError, match="outside the update"):
        update.launch_installer(installer)


@pytest.mark.skipif(os.name != "nt", reason="Windows installed-build detection")
def test_installed_build_requires_exact_registered_exe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exe = Path(r"C:\Apps\Clipper\Clipper.exe")
    monkeypatch.setattr(update.os, "name", "nt")
    monkeypatch.setattr(update.sys, "frozen", True, raising=False)
    monkeypatch.setattr(update.sys, "executable", str(exe))
    monkeypatch.setattr(update, "_registered_install_exe", lambda: exe)
    assert update.is_installed_build()

    monkeypatch.setattr(
        update, "_registered_install_exe", lambda: Path(r"C:\Other\Clipper.exe")
    )
    assert not update.is_installed_build()

    monkeypatch.setattr(update, "_registered_install_exe", lambda: None)
    assert not update.is_installed_build()


def test_cleanup_download_only_removes_update_temp_dir() -> None:
    update_dir = Path(tempfile.mkdtemp(prefix="clipper-update-"))
    installer = update_dir / "ClipperSetup-9.9.9.exe"
    installer.write_bytes(b"MZ")
    update.cleanup_download(installer)
    assert not update_dir.exists()

    keep = Path(tempfile.mkdtemp(prefix="clipper-keep-"))
    try:
        kept_file = keep / "keep.txt"
        kept_file.write_text("keep", encoding="utf-8")
        update.cleanup_download(kept_file)
        assert kept_file.exists()
    finally:
        for child in keep.iterdir():
            child.unlink()
        keep.rmdir()


def test_release_rejects_malformed_asset_size() -> None:
    release = update._release_from_payload(
        {
            "tag_name": "v0.7.0",
            "assets": [
                {
                    "name": "ClipperSetup-0.7.0.exe",
                    "browser_download_url": "https://example.test/setup",
                    "size": "not-a-number",
                },
                {
                    "name": "SHA256SUMS.txt",
                    "browser_download_url": "https://example.test/sums",
                },
            ],
        }
    )
    assert release.installer_size == 0
