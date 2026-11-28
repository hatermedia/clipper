from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_installer_never_wipes_the_install_directory() -> None:
    nsi = _read(PACKAGING / "clipper.nsi")
    assert not re.search(r'RMDir\s+/r\s+"\$INSTDIR"\s*$', nsi, re.IGNORECASE | re.MULTILINE)
    assert 'RMDir /r "$INSTDIR\\_internal"' in nsi
    assert 'RMDir /r "$INSTDIR\\bin"' in nsi
    assert 'RMDir "$INSTDIR"' in nsi
    assert 'ReadRegStr $0 HKCU "Software\\Clipper" "InstallDir"' in nsi


def test_installer_upgrades_in_place_and_extracts_fast() -> None:
    nsi = _read(PACKAGING / "clipper.nsi")
    assert "SetCompressor /SOLID lzma" not in nsi
    assert "SetCompressor lzma" in nsi
    assert "!insertmacro MUI_PAGE_DIRECTORY" not in nsi
    assert "InstallDirRegKey HKCU \"Software\\Clipper\" \"InstallDir\"" in nsi
    assert "CurrentVersion\\Uninstall\\Clipper\" \"InstallLocation\"" in nsi
    assert "Function .onInit" in nsi
    assert "StrCpy $INSTDIR $0" in nsi
    assert "SetOverwrite on" in nsi


def test_installer_closes_running_app_and_removes_settings() -> None:
    nsi = _read(PACKAGING / "clipper.nsi")
    close_script = _read(PACKAGING / "close_clipper.ps1")
    assert "close_clipper.ps1" in nsi
    assert "Call CloseClipper" in nsi
    assert "Call un.CloseClipper" in nsi
    assert 'DeleteRegKey HKCU "Software\\hatermedia\\Clipper"' in nsi
    assert 'DeleteRegKey /ifempty HKCU "Software\\hatermedia"' in nsi
    # The installer is 32-bit and cannot always read a 64-bit process Path.
    assert "Get-CimInstance Win32_Process" in close_script
    assert "CloseMainWindow" in close_script
    assert "/F /PID" in close_script


def test_installer_bundles_notices_and_ffmpeg_license() -> None:
    nsi = _read(PACKAGING / "clipper.nsi")
    for name in ("THIRD_PARTY_NOTICES.txt", "FFMPEG_NOTICE.txt", "COPYING.GPLv3.txt"):
        assert name in nsi
    assert "$INSTDIR\\licenses" in nsi
    assert (ROOT / "THIRD_PARTY_NOTICES.txt").is_file()
    assert (PACKAGING / "COPYING.GPLv3.txt").is_file()
    licenses = PACKAGING / "licenses"
    for name in (
        "Apache-2.0.txt",
        "BSD-3-Clause.txt",
        "CC-BY-SA-4.0.txt",
        "LGPL-3.0.txt",
        "MIT.txt",
        "MPL-2.0.txt",
    ):
        assert (licenses / name).is_file(), name


def test_portable_build_collects_ai_and_ocr_dependencies() -> None:
    script = _read(PACKAGING / "build_windows.ps1")
    for package in (
        "faster_whisper",
        "ctranslate2",
        "tokenizers",
        "onnxruntime",
        "rapidocr_onnxruntime",
        "pyclipper",
        "shapely",
        "av",
    ):
        assert f"--collect-all {package}" in script
    assert "bundle_runtime.ps1" in script
    assert "prepare_whisper_model.py" in script


def test_runtime_bundle_targets_internal_and_checks_required_dlls() -> None:
    script = _read(PACKAGING / "bundle_runtime.ps1")
    assert 'Join-Path $Dist "_internal"' in script
    assert "libiomp5md.dll" in script
    assert "msvcp140.dll" in script and "vcruntime140.dll" in script
    assert "PySide6" in script and "ctranslate2" in script
    assert "models\\base.en" in script
    assert "licenses" in script


def test_installer_build_verifies_payload_and_checksums() -> None:
    script = _read(PACKAGING / "build_installer.ps1")
    for name in (
        "THIRD_PARTY_NOTICES.txt",
        "FFMPEG_NOTICE.txt",
        "COPYING.GPLv3.txt",
        "models\\base.en\\model.bin",
        "bin\\ffmpeg.exe",
        "licenses\\Apache-2.0.txt",
        "licenses\\MPL-2.0.txt",
    ):
        assert name in script
    assert "SHA256SUMS.txt" in script
    assert "Get-FileHash" in script


def test_whisper_model_pin_is_explicit() -> None:
    script = _read(PACKAGING / "prepare_whisper_model.py")
    assert "Systran/faster-whisper-base.en" in script
    assert "3d3d5dee26484f91867d81cb899cfcf72b96be6c" in script
    for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"):
        assert name in script


def test_notices_are_copied_into_package_assets() -> None:
    assert (ROOT / "THIRD_PARTY_NOTICES.txt").read_bytes() == (
        ROOT / "src" / "clipper" / "assets" / "THIRD_PARTY_NOTICES.txt"
    ).read_bytes()
    assert (PACKAGING / "FFMPEG_NOTICE.txt").read_bytes() == (
        ROOT / "src" / "clipper" / "assets" / "FFMPEG_NOTICE.txt"
    ).read_bytes()
    assert (PACKAGING / "COPYING.GPLv3.txt").read_bytes() == (
        ROOT / "src" / "clipper" / "assets" / "COPYING.GPLv3.txt"
    ).read_bytes()
    assert (PACKAGING / "licenses" / "Apache-2.0.txt").read_bytes() == (
        ROOT / "src" / "clipper" / "assets" / "licenses" / "Apache-2.0.txt"
    ).read_bytes()


def test_ffmpeg_source_manifest_matches_fetch_script() -> None:
    manifest = _read(PACKAGING / "FFMPEG_SOURCE_MANIFEST.txt")
    script = _read(PACKAGING / "fetch_ffmpeg_source.ps1")
    for value in (
        "74e4393595",
        "4ae3618b0d38a14bb8f86a6b90de63c4b6b55d4de8e812a4900d07d2188b54de",
        "0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee",
        "d0967a1348c85dfde363bb52610403be898171493100561efa0dd05d5fd1ae50",
        "0aa4121746654e88564d0dfa16143f60ad6eabff",
        "9cedb0f96543d44857e9a92a221fc8906b9cc8a335a19d7eb19d5127993c78ac",
    ):
        assert value in manifest, value
        assert value in script, value
    assert "x264" in manifest and "x265" in manifest


def test_game_title_map_is_large_and_has_core_titles() -> None:
    import json

    payload = json.loads(
        (ROOT / "src" / "clipper" / "assets" / "game_titles.json").read_text(
            encoding="utf-8"
        )
    )
    games = payload["processes"]
    assert len(games) >= 150
    for exe in (
        "rocketleague.exe",
        "valorant.exe",
        "cs2.exe",
        "mimesis.exe",
        "league of legends.exe",
        "r5apex.exe",
    ):
        assert exe in games


def test_notices_name_bundled_models_and_runtime() -> None:
    notices = _read(ROOT / "THIRD_PARTY_NOTICES.txt")
    for token in ("YAMNet", "faster-whisper", "PySide6", "FFmpeg", "ONNX Runtime"):
        assert token in notices
    ffmpeg = _read(PACKAGING / "FFMPEG_NOTICE.txt")
    assert "74e4393595" in ffmpeg
    assert "GNU GPL version 3" in ffmpeg


def test_desktop_build_requires_clean_tree_and_sanitizes_payload() -> None:
    script = _read(PACKAGING / "build_desktop.ps1")
    assert "git -C $Root status --porcelain" in script
    assert "git -C $Root rev-parse HEAD" in script
    assert "make_version_info.py" in script
    assert "--version-file $VersionFile" in script
    assert "sanitize_payload.py" in script
    assert "--commit $Commit" in script
    sanitizer = _read(PACKAGING / "sanitize_payload.py")
    assert "BUILD_INFO.txt" in sanitizer
    assert "direct_url.json" in sanitizer
    assert "clipper_gg-" in sanitizer


def test_installer_requires_and_removes_build_info() -> None:
    installer = _read(PACKAGING / "build_installer.ps1")
    nsi = _read(PACKAGING / "clipper.nsi")
    assert '"BUILD_INFO.txt"' in installer
    assert 'Delete "$INSTDIR\\BUILD_INFO.txt"' in nsi
    assert "sanitize_payload.py" in installer
    assert "--check" in installer
    assert "FileVersion" in installer
    assert "ProductVersion" in installer
    assert "hatermedia" in installer
    assert 'SHA256SUMS-$Version.txt' in installer


def test_payload_sanitizer_removes_editable_metadata_and_local_paths(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    internal = dist / "_internal"
    internal.mkdir(parents=True)
    (dist / "Clipper.exe").write_bytes(b"exe")
    (dist / "README.txt").write_text("Clipper 0.9.0\n", encoding="utf-8")
    stale = internal / "clipper_gg-0.7.0.dist-info"
    stale.mkdir()
    (stale / "direct_url.json").write_text(
        json.dumps(
            {
                "dir_info": {"editable": True},
                "url": "file:///C:/Users/Example/clipper",
            }
        ),
        encoding="utf-8",
    )
    third_party = internal / "thirdparty-1.0.dist-info"
    third_party.mkdir()
    (third_party / "direct_url.json").write_text(
        json.dumps({"url": "https://example.invalid/package.whl"}),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(PACKAGING / "sanitize_payload.py"),
            "--dist",
            str(dist),
            "--version",
            "0.9.0",
            "--commit",
            "abc123",
            "--build-date",
            "2026-11-28T00:00:00+00:00",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert not stale.exists()
    clean = internal / "clipper_gg-0.9.0.dist-info"
    assert clean.is_dir()
    assert "Version: 0.9.0" in (clean / "METADATA").read_text(encoding="utf-8")
    assert "Commit: abc123" in (dist / "BUILD_INFO.txt").read_text(encoding="utf-8")
    assert (third_party / "direct_url.json").is_file()
    assert not (clean / "direct_url.json").exists()


def test_payload_sanitizer_check_mode_enforces_provenance(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "_internal").mkdir(parents=True)
    (dist / "Clipper.exe").write_bytes(b"exe")
    common = [
        sys.executable,
        str(PACKAGING / "sanitize_payload.py"),
        "--dist",
        str(dist),
        "--version",
        "0.9.0",
    ]
    missing = subprocess.run(
        [*common, "--commit", "abc123", "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode != 0
    assert "BUILD_INFO.txt is missing" in missing.stderr

    sanitized = subprocess.run(
        [*common, "--commit", "abc123"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert sanitized.returncode == 0, sanitized.stderr
    verified = subprocess.run(
        [*common, "--commit", "abc123", "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr
    wrong_commit = subprocess.run(
        [*common, "--commit", "def456", "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert wrong_commit.returncode != 0
    assert "wrong commit" in wrong_commit.stderr


def test_payload_sanitizer_fails_on_local_path(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "_internal").mkdir(parents=True)
    (dist / "Clipper.exe").write_bytes(b"exe")
    (dist / "README.txt").write_text(
        "local path C:/Users/Example/secret\n", encoding="utf-8"
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(PACKAGING / "sanitize_payload.py"),
            "--dist",
            str(dist),
            "--version",
            "0.9.0",
            "--commit",
            "abc123",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "local filesystem path" in proc.stderr


def test_payload_sanitizer_scans_binary_files_for_local_paths(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    internal = dist / "_internal"
    internal.mkdir(parents=True)
    (dist / "Clipper.exe").write_bytes(b"exe")
    (internal / "leak.bin").write_bytes(b"\x00\x01C:\\Users\\Example\\clipper\x00")
    proc = subprocess.run(
        [
            sys.executable,
            str(PACKAGING / "sanitize_payload.py"),
            "--dist",
            str(dist),
            "--version",
            "0.9.0",
            "--commit",
            "abc123",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "local filesystem path" in proc.stderr
    assert "leak.bin" in proc.stderr


def test_version_resource_generator_uses_requested_version(tmp_path: Path) -> None:
    output = tmp_path / "version.txt"
    proc = subprocess.run(
        [
            sys.executable,
            str(PACKAGING / "make_version_info.py"),
            "--version",
            "0.9.0",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    text = output.read_text(encoding="utf-8")
    assert "filevers=(0, 9, 0, 0)" in text
    assert "StringStruct('FileVersion', '0.9.0')" in text
    assert "StringStruct('ProductName', 'Clipper')" in text
