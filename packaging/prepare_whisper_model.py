"""Stage the pinned faster-whisper base.en model for an offline Lite build.

The model is intentionally kept out of the Python wheel (it is larger than the
PyPI artifact limit) and copied into the frozen app by the build scripts.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

MODEL_REPO = "Systran/faster-whisper-base.en"
MODEL_REVISION = "3d3d5dee26484f91867d81cb899cfcf72b96be6c"
REQUIRED_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
MIN_BYTES = {
    "config.json": 500,
    "model.bin": 100 * 1024 * 1024,
    "tokenizer.json": 100_000,
    "vocabulary.txt": 100_000,
}


def _valid(directory: Path) -> bool:
    return all(
        (directory / name).is_file()
        and (directory / name).stat().st_size >= MIN_BYTES[name]
        for name in REQUIRED_FILES
    )


def _cached_snapshot(cache_dir: Path) -> Path | None:
    """Find a usable local snapshot without asking Hugging Face for a manifest."""

    snapshots = (
        cache_dir
        / "hub"
        / "models--Systran--faster-whisper-base.en"
        / "snapshots"
    )
    if not snapshots.is_dir():
        return None
    candidates = [path for path in snapshots.iterdir() if path.is_dir()]
    candidates.sort(key=lambda path: path.name != MODEL_REVISION)
    for candidate in candidates:
        if _valid(candidate):
            return candidate
    return None


def stage(output: Path) -> None:
    if _valid(output):
        print(f"Whisper model already staged: {output}")
        return

    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
    cache_dir = base / "Clipper" / "models" / "huggingface"
    snapshot = _cached_snapshot(cache_dir)
    if snapshot is None:
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise SystemExit(
                "huggingface_hub is required to stage the Whisper model."
            ) from exc

        try:
            snapshot = Path(
                snapshot_download(
                    MODEL_REPO,
                    revision=MODEL_REVISION,
                    cache_dir=str(cache_dir),
                    local_files_only=True,
                )
            )
        except Exception:
            try:
                snapshot = Path(
                    snapshot_download(
                        MODEL_REPO,
                        revision=MODEL_REVISION,
                        cache_dir=str(cache_dir),
                    )
                )
            except Exception as exc:
                raise SystemExit(
                    "Could not obtain the pinned Whisper base.en model. "
                    "Connect to Hugging Face once or pre-populate the HF cache."
                ) from exc

    if not _valid(snapshot):
        raise SystemExit(f"Whisper model snapshot is incomplete: {snapshot}")

    output.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_FILES:
        source = snapshot / name
        shutil.copy2(source, output / name)
    if not _valid(output):
        raise SystemExit(f"Staged Whisper model is incomplete: {output}")
    print(f"Staged Whisper base.en model: {output}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", nargs="?", default="packaging/models/base.en")
    args = parser.parse_args(argv)
    stage(Path(args.output).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
