Clipper __CLIPPER_VERSION__ - Windows x64 CLI portable
=====================================================

No Python install. No FFmpeg install. Everything is in this folder.

QUICK START
-----------
1. Double-click "Clipper UI.cmd".
2. Your browser opens http://127.0.0.1:8765
3. Pick a folder of gameplay clips, scan, detect, review previews, export.

CLI
---
Open "Clipper CLI.cmd", or run clipper.exe directly:

  clipper.exe --input "D:\Captures" --dry-run
  clipper.exe --input "D:\Captures" --output "D:\Highlights"
  clipper.exe --input "D:\Captures" --reencode --encoder h264_nvenc

The bundled ffmpeg/ffprobe live in the bin folder.

LOCAL AI
--------
Whisper transcription, RapidOCR HUD reading, and YAMNet audio tagging are
bundled, so OCR and transcription work offline after install.

The AI Director still needs a local vision model. This CLI portable does not
include the multi-gigabyte model or the llama.cpp runtime. The desktop app is
the recommended first-run experience because it downloads and manages the
bundled llama.cpp runtime and model tiers.

The CLI currently defaults to an Ollama vision model. If you use that path,
install Ollama yourself and install a supported vision model, for example:

  ollama pull qwen2.5vl:7b

Ollama is optional for the desktop app and is not installed by Clipper.

NOTES
-----
- Footage never leaves this machine. The UI binds to 127.0.0.1.
- Default export uses FFmpeg stream copy (instant, lossless). Stream copy can
  start on an earlier keyframe; use --reencode for exact edges.
- Windows SmartScreen may warn about an unsigned executable. The source is at
  https://github.com/hatermedia/clipper and the build is reproducible with
  packaging/build_windows.ps1.
- MIT licensed. You are responsible for the rights to footage you process.

LINKS
-----
https://github.com/hatermedia/clipper
https://hatermedia.github.io/clipper/
