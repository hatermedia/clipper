"""Sanitize the PyInstaller payload before packaging.

The developer virtual environment may contain editable-install metadata from an
older Clipper version. PyInstaller can copy that metadata into ``_internal``.
This step removes stale Clipper metadata, writes a clean versioned dist-info,
adds build provenance, and fails if local paths or unwanted files remain.
"""

from __future__ import annotations

import argparse
import platform
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".avi"}
TEMP_SUFFIXES = {".log", ".tmp", ".part", ".bak"}
LOCAL_PATH_BYTES = (
    re.compile(rb"[A-Za-z]:[\\/]Users[\\/]", re.IGNORECASE),
    re.compile(rb"file:///[A-Za-z]:/Users/", re.IGNORECASE),
)


def _tool_versions() -> dict[str, str]:
    versions = {"Python": sys.version.split()[0]}
    try:
        import PyInstaller

        versions["PyInstaller"] = PyInstaller.__version__
    except Exception:
        versions["PyInstaller"] = "unknown"
    try:
        import PySide6

        versions["PySide6"] = PySide6.__version__
    except Exception:
        versions["PySide6"] = "unknown"
    return versions


def _clean_metadata(dist: Path, version: str) -> list[str]:
    removed: list[str] = []
    roots = (dist, dist / "_internal")
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in ("clipper_gg-*.dist-info", "clipper-*.egg-info"):
            for path in root.glob(pattern):
                if path.is_dir():
                    shutil.rmtree(path)
                    removed.append(str(path.relative_to(dist)))
    for path in (dist / "_internal").rglob("direct_url.json"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "file:" in text.lower() or re.search(
            r"(?<![A-Za-z])[A-Za-z]:[\\/]", text
        ):
            path.unlink()
            removed.append(str(path.relative_to(dist)))

    meta = dist / "_internal" / f"clipper_gg-{version}.dist-info"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "METADATA").write_text(
        "Metadata-Version: 2.1\n"
        "Name: clipper-gg\n"
        f"Version: {version}\n"
        "Summary: Native Windows local-AI gameplay highlight trimmer\n"
        "Author: hatermedia\n"
        "License: MIT\n"
        "Requires-Python: >=3.10\n"
        "Project-URL: Homepage, https://github.com/hatermedia/clipper\n"
        "Project-URL: Repository, https://github.com/hatermedia/clipper\n",
        encoding="utf-8",
    )
    (meta / "WHEEL").write_text(
        "Wheel-Version: 1.0\n"
        "Generator: clipper-build\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n",
        encoding="utf-8",
    )
    (meta / "top_level.txt").write_text("clipper\n", encoding="utf-8")
    (meta / "INSTALLER").write_text("clipper-build\n", encoding="utf-8")
    (meta / "REQUESTED").write_text("", encoding="utf-8")
    (meta / "RECORD").write_text(
        "METADATA,,\nWHEEL,,\ntop_level.txt,,\nINSTALLER,,\nREQUESTED,,\nRECORD,,\n",
        encoding="utf-8",
    )
    return removed


def _build_info(
    version: str,
    commit: str,
    build_date: str,
    build_type: str,
) -> str:
    tools = _tool_versions()
    lines = [
        f"Clipper {version}",
        f"Commit: {commit}",
        f"Build date: {build_date}",
        f"Build platform: {platform.platform()}",
        f"Build type: {build_type}",
        f"Python: {tools['Python']}",
        f"PyInstaller: {tools['PyInstaller']}",
        f"PySide6: {tools['PySide6']}",
    ]
    return "\n".join(lines) + "\n"


def assert_clean(dist: Path, version: str, commit: str = "") -> None:
    errors: list[str] = []
    build_info = dist / "BUILD_INFO.txt"
    if not build_info.is_file():
        errors.append("BUILD_INFO.txt is missing")
    else:
        text = build_info.read_text(encoding="utf-8", errors="replace")
        if f"Clipper {version}" not in text:
            errors.append("BUILD_INFO.txt has the wrong version")
        if commit and f"Commit: {commit}" not in text:
            errors.append("BUILD_INFO.txt has the wrong commit")
    expected_meta = f"clipper_gg-{version}.dist-info"
    for path in dist.rglob("*"):
        if (
            path.is_dir()
            and path.name.startswith("clipper_gg-")
            and path.name != expected_meta
        ):
            errors.append(f"stale Clipper metadata: {path.relative_to(dist)}")
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in VIDEO_SUFFIXES:
            errors.append(f"video file: {path.relative_to(dist)}")
        if suffix == ".gguf":
            errors.append(f"LLM model weight: {path.relative_to(dist)}")
        if suffix in TEMP_SUFFIXES:
            errors.append(f"temporary file: {path.relative_to(dist)}")
        try:
            data = path.read_bytes()
        except OSError:
            continue
        for pattern in LOCAL_PATH_BYTES:
            if pattern.search(data):
                errors.append(f"local filesystem path in {path.relative_to(dist)}")
                break
        if path.name == "direct_url.json":
            text = data.decode("utf-8", errors="replace")
            if "file:" in text.lower() or re.search(
                r"(?<![A-Za-z])[A-Za-z]:[\\/]", text
            ):
                errors.append(f"local direct_url metadata: {path.relative_to(dist)}")
    if errors:
        raise SystemExit("Payload integrity check failed:\n- " + "\n- ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--build-date", default="")
    parser.add_argument(
        "--build-type",
        default="PyInstaller onedir, Windows x64 native",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify an already-sanitized payload without modifying it.",
    )
    args = parser.parse_args()
    dist = Path(args.dist).resolve()
    if not (dist / "Clipper.exe").is_file():
        raise SystemExit(f"Clipper.exe not found under {dist}")
    if args.check:
        assert_clean(dist, args.version, args.commit)
        print(f"payload verified: {dist}")
        return 0
    removed = _clean_metadata(dist, args.version)
    build_date = args.build_date or datetime.now(timezone.utc).replace(
        microsecond=0
    ).isoformat()
    (dist / "BUILD_INFO.txt").write_text(
        _build_info(args.version, args.commit, build_date, args.build_type),
        encoding="utf-8",
    )
    assert_clean(dist, args.version, args.commit)
    print(f"sanitized {dist}")
    for item in removed:
        print(f"removed {item}")
    print(f"BUILD_INFO commit {args.commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
