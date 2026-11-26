from __future__ import annotations

from pathlib import Path

EM_DASH = chr(0x2014)
PATTERNS = (
    EM_DASH,
    "&" + "mdash;",
    "&" + "MDASH;",
    "&#" + "8212;",
    "&#" + "x2014;",
    "&#" + "X2014;",
    "\\" + "u2014",
    "\\" + "U00002014",
    "\\" + "N{EM DASH}",
)

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".git",
    ".venv",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "dist",
}
SKIP_PARTS = {
    ("packaging", "build"),
    ("packaging", "desktop-build"),
    ("packaging", "desktop-dist"),
    ("packaging", "dist"),
}
BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".onnx",
    ".dll",
    ".exe",
    ".zip",
    ".whl",
    ".gguf",
    ".mp4",
    ".pyc",
}


def test_first_party_sources_contain_no_em_dash() -> None:
    offenders: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if any(rel.parts[: len(parts)] == parts for parts in SKIP_PARTS):
            continue
        if path.suffix.lower() in BINARY_SUFFIXES or path.suffix.lower() == ".log":
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in PATTERNS:
            if pattern in text:
                offenders.append(f"{rel} ({pattern!r})")
                break
    assert not offenders, "Remove em dash representations from:\n" + "\n".join(
        offenders
    )
