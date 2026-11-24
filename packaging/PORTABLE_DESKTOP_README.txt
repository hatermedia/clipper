Clipper 0.5.0 - Windows x64 native
=================================

No Python. No FFmpeg. No browser. No console window.

QUICK START
-----------
Double-click Clipper.exe.

1. Choose a folder (or drag one onto the drop zone).
2. Review the detected highlights and preview frames.
3. Pick an output folder and export.

AI DIRECTOR (OPTIONAL)
----------------------
The local audio + motion detector works without any model. For whole-clip story
detection, install Ollama from https://ollama.com and pull a vision model:

  ollama pull qwen2.5vl:7b

Then tick "AI director (local)" in the app, pick Director mode and a game preset.
The director transcribes the audio with local Whisper, reviews every 15-20s
window with frames + transcript + audio energy, and keeps funny interactions,
trolling, banter, reactions, goals, clutches, and round wins. A long interaction
can stay 30-90s; it does not force everything into a six-second peak.

Game profiles include Rocket League, Mimesis, Valorant, Apex Legends, CS2, and
Generic. The app picks a preset from the footage path. Rocket League looks for
goals, saves, passing plays, demos, overtime/0-second goals, and late-night
fakes. Mimesis prioritises screaming, trolling, betrayal, prop chases, and
friend banter.

Game Guard is on by default. When Rocket League, Mimesis, Valorant, Apex, CS2,
or another known game is running, Clipper pauses the director and unloads the
Ollama model so the game gets the VRAM. It resumes when the game closes. Discord
does not expose other apps' Rich Presence, so this uses the local process list.

On a 6 GB card use qwen2.5vl:3b; the app selects it automatically when it is
installed on a <=7 GB GPU. 7B is noticeably better and recommended on 8 GB+.
The first run downloads the Whisper base.en model once (~145 MB) into
%LOCALAPPDATA%\Clipper\models\huggingface. Window verdicts are cached under
%LOCALAPPDATA%\Clipper\ai-cache. Nothing is uploaded.

Honest limits: game voice lines and human chat share one audio track, so the
director can mistake tactical callouts for banter. It requires a humour cue
before calling a conversation funny, but it still needs real labelled clips to
tune. Whisper runs on the CPU; the vision model runs on the GPU.

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
