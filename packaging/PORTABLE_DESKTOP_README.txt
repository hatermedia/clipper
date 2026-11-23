Clipper 0.2.1 - Windows x64 native
=================================

No Python. No FFmpeg. No browser. No console window.

QUICK START
-----------
Double-click Clipper.exe.

1. Choose a folder (or drag one onto the drop zone).
2. Review the detected highlights and preview frames.
3. Pick an output folder and export.

PERFORMANCE
-----------
- GPU: enable "Use NVIDIA GPU (NVENC)" to use hardware encoding. Decoding may
  still use the CPU depending on the source codec.
- CPU threads: Balanced uses about half the cores. Low uses 2. Max lets FFmpeg
  decide.
- Low-power mode: 2 threads, 2fps/256px analysis proxy, below-normal process
  priority. This is the setting to use while gaming or on a laptop.
- The default is a balanced thread cap, not every core.

CLI (OPTIONAL)
--------------
The native portable build is GUI-only. For scripting, install the Python package:

  python -m pip install clipper-gg
  clipper --input "D:\Captures" --dry-run
  clipper --input "D:\Captures" --low-power --gpu

NOTES
-----
- Footage never leaves this machine.
- Default export is FFmpeg stream copy (instant, lossless). Stream copy can
  start on an earlier keyframe; enable frame-accurate re-encode for exact edges.
- Windows SmartScreen may warn because the executable is unsigned. Source and
  build script: https://github.com/hatermedia/clipper/tree/main/packaging
- MIT licensed. You are responsible for the rights to footage you process.

LINKS
-----
https://github.com/hatermedia/clipper
https://hatermedia.github.io/clipper/
