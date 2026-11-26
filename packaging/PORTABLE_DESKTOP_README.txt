Clipper 0.8.1 - Windows x64 native
=================================

No Python. No FFmpeg. No browser. No console window.

QUICK START
-----------
Double-click Clipper.exe.

1. Choose a folder (or drag one onto the drop zone).
2. Watch clips appear per file as the AI scan finishes.
3. Select a clip row to see its peak frame; press Play to watch it. Tick the clips you want.
4. Pick an output folder and choose Export selected or Export all.

LOCAL AI DIRECTOR (REQUIRED)
---------------------------
Every scan is reviewed by the local vision director. There is no heuristic-only
highlighting fallback.

Open Clipper's AI setup panel and click "Install Ollama". Clipper downloads the
official installer, verifies its SHA-256 and Authenticode signature, installs it
for the current user, and starts it. Then click "Install model" to download
gemma3:4b or qwen2.5vl:7b through Ollama.

You can also install Ollama manually from https://ollama.com and run:

  ollama pull qwen2.5vl:7b

The game is detected from the footage folder or file name. The director
transcribes the audio with local Whisper, reviews every 15-20s
window with frames + transcript + audio energy, and keeps funny interactions,
trolling, banter, reactions, goals, clutches, and round wins. A long interaction
can stay 30-90s; it does not force everything into a six-second peak.

Game profiles include Rocket League, Mimesis, Valorant, Apex Legends, CS2, and
Generic. The app picks a preset from the footage path. Rocket League looks for
goals, saves, passing plays, demos, overtime/0-second goals, and late-night
fakes. Mimesis prioritises screaming, trolling, betrayal, prop chases, and
friend banter.

Game Guard is on by default. It uses a large title map, Unreal Engine process
detection, and Steam/Epic/GOG/Riot/EA/Ubisoft/Xbox install paths. When a known
game is running, Clipper pauses the director and unloads the Ollama model so the
game gets the VRAM. It resumes when the game closes. You can add a missed title
in %LOCALAPPDATA%\Clipper\games.json.

On a 6 GB card use gemma3:4b (tested). On 8 GB+ use qwen2.5vl:7b. The Windows
installer and portable build include the Whisper base.en model, so speech
transcription works offline. Source installs
download it once (~145 MB) into %LOCALAPPDATA%\Clipper\models\huggingface.
Window verdicts are cached under %LOCALAPPDATA%\Clipper\ai-cache. Nothing is
uploaded.

Honest limits: game voice lines and human chat share one audio track, so the
director can mistake tactical callouts for banter. It requires a humour cue
before calling a conversation funny, but it still needs real labelled clips to
tune. Whisper runs on the CPU; the vision model runs on the GPU.

PERFORMANCE
-----------
- GPU/NVENC is on by default when the real one-frame NVENC test passes. It is
  used for the analysis proxy and the local AI runtime.
- Decoding may still use the CPU depending on the source codec; OpenCV motion
  scoring and audio RMS remain CPU work.
- CPU threads: Balanced uses about half the cores. Low uses 2. Max lets FFmpeg
  decide.
- Low-power mode: 2 threads, 2fps/256px analysis proxy, below-normal process
  priority. It is a performance preset; the local AI director still runs.

UPDATES
-------
The installed build (the per-user installer, not this portable zip) checks
GitHub Releases at launch, downloads the installer, verifies its SHA-256, and
installs silently. The portable build opens the release page instead of
replacing itself.

NOTES
-----
- Footage never leaves this machine. AI runs locally through Ollama.
- Exports use FFmpeg stream copy (instant, lossless); the original video and
  audio streams are kept.
- Windows SmartScreen may warn because the executable is unsigned. Source and
  build scripts: https://github.com/hatermedia/clipper/tree/main/packaging
- MIT licensed. You are responsible for the rights to footage you process.

LINKS
-----
https://github.com/hatermedia/clipper
https://hatermedia.github.io/clipper/
