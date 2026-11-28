"""Generate the PyInstaller Windows version resource for Clipper."""

from __future__ import annotations

import argparse
from pathlib import Path


def _version_tuple(version: str) -> tuple[int, int, int, int]:
    parts = []
    for piece in version.split("."):
        try:
            parts.append(max(0, int(piece)))
        except ValueError:
            parts.append(0)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])  # type: ignore[return-value]


def render(version: str) -> str:
    filevers = _version_tuple(version)
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={filevers},
    prodvers={filevers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'hatermedia'),
        StringStruct('FileDescription', 'Clipper native gameplay highlight trimmer'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'Clipper'),
        StringStruct('LegalCopyright', 'MIT licensed'),
        StringStruct('OriginalFilename', 'Clipper.exe'),
        StringStruct('ProductName', 'Clipper'),
        StringStruct('ProductVersion', '{version}'),
        StringStruct('Comments', 'https://github.com/hatermedia/clipper')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(args.version), encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
