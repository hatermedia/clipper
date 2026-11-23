Clipper 0.3.2 - Windows x64 native
=================================

No Python. No FFmpeg. No browser. No console window.

QUICK START
-----------
Double-click Clipper.exe.

1. Choose a folder (or drag one onto the drop zone).
2. Review the detected highlights and preview frames.
3. Pick an output folder and export.

AI REVIEW (OPTIONAL)
--------------------
The local audio + motion detector works without any model. For a second opinion,
install Ollama from https://ollama.com and pull a vision model:

  ollama pull qwen2.5vl:7b

Then tick "AI review (local)" in the app and pick a game preset. Frames are
center-cropped, sent to the local model, and cached under
%LOCALAPPDATA%\Clipper\ai-cache. Nothing is uploaded.

The AI pass is a review layer, not a trained kill detector. It reliably rejects
black screens, desktops, menus, and loading screens, and it reads the top HUD
(kill feed, score, round text). It can still miss a quiet kill or accept a tense
standoff, so preview clips before exporting. qwen2.5vl:7b uses about 6 GB of
VRAM; qwen2.5vl:3b is smaller and less accurate.

PERFORMANCE
-----------
- GPU/NVENC is on by default when the real one-frame NVENC test passes. It is
  used for the analysis proxy, optional re-encode, and the local AI runtime.
- Decoding may still use the CPU depending on the source codec; OpenCV motion
  scoring and audio RMS remain CPU work.
- CPU threads: Balanced uses about half the cores. Low uses 2. Max lets FFmpeg
  decide.
- Low-power mode: 2 threads, 2fps/256px analysis proxy, below-normal process
  priority. This is the setting to use while gaming or on a laptop.

UPDATES
-------
The installed build (the per-user installer, not this portable zip) checks
GitHub Releases at launch, downloads the installer, verifies its SHA-256, and
installs silently. The portable build opens the release page instead of
replacing itself.

CLI (OPTIONAL)
--------------
The native portable build is GUI-only. For scripting, install the Python package:

  python -m pip install clipper-gg
  clipper --input "D:\Captures" --dry-run
  clipper --input "D:\Captures" --ai --ai-game Valorant --dry-run
  clipper update

NOTES
-----
- Footage never leaves this machine. AI runs locally through Ollama.
- Default export is FFmpeg stream copy (instant, lossless). Stream copy can
  start on an earlier keyframe; enable frame-accurate re-encode for exact edges.
- Windows SmartScreen may warn because the executable is unsigned. Source and
  build scripts: https://github.com/hatermedia/clipper/tree/main/packaging
- MIT licensed. You are responsible for the rights to footage you process.

LINKS
-----
https://github.com/hatermedia/clipper
https://hatermedia.github.io/clipper/
