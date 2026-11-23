"""PyInstaller entry point for the native windowed Clipper app."""

from clipper.desktop import main

if __name__ == "__main__":
    raise SystemExit(main())
