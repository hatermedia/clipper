from __future__ import annotations

import re
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
