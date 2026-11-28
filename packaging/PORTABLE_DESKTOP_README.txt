Clipper __CLIPPER_VERSION__ - Windows x64
=========================================

Clipper is a native Windows app that scans gameplay footage with a local AI
director and cuts highlights with FFmpeg. Everything runs on this PC. There are
no accounts, no uploads, and no browser.

This README is included with both the per-user installer and the portable zip.


WHAT IS INCLUDED
----------------
Bundled with Clipper:
- The Clipper desktop app and its Python/Qt runtime.
- FFmpeg and FFprobe.
- Whisper base.en for offline speech transcription.
- RapidOCR for HUD text.
- YAMNet for audio tagging.
- OpenCV, ONNX Runtime, CTranslate2, PyAV, and the other runtime libraries.
- The Microsoft Visual C++ runtime and Intel OpenMP DLLs used by the app.

Downloaded on demand when you set up the AI Director:
- The llama.cpp runtime (pinned release b12776, CUDA 12.4 build).
- The local AI model you choose.

Not included:
- Ollama. It is not required and Clipper does not install it.
- The AI models. They are several gigabytes and are downloaded only when you
  ask for them.
- NVIDIA drivers or the CUDA Toolkit. Clipper uses the driver already installed
  on Windows and downloads its own CUDA user-mode libraries.


INSTALL
-------
Installer:
1. Run ClipperSetup-__CLIPPER_VERSION__.exe.
2. Windows may show a SmartScreen warning because the build is unsigned.
   Choose "More info", then "Run anyway" only if you downloaded the file from
   the official Clipper release page.
3. The installer is per-user. It does not ask for administrator rights.
4. Clipper is installed in:
   %LOCALAPPDATA%\Programs\Clipper
5. Desktop and Start Menu shortcuts are created.
6. Launch Clipper from the shortcut or from Clipper.exe.

Running a newer installer over an existing install reuses the same folder and
replaces the app in place. It does not create a second copy.

Portable zip:
1. Extract the zip to a folder you can write to.
2. Run Clipper.exe.
3. No installer or administrator rights are needed.

The installer closes a running copy of Clipper before replacing files. If the
installer cannot close it, close Clipper from Task Manager and run the installer
again.


FIRST LAUNCH AND LOCAL AI
-------------------------
Every Clipper scan is reviewed by the local AI director. There is no
heuristic-only highlighting mode. The app opens without a model, but Detect
highlights stays disabled until a vision model is ready.

To set up the AI Director:
1. Open the "AI model" dropdown in the Local AI director panel.
2. Choose a bundled tier:
   - Lite: LFM3-Omni-2B
   - Standard: MiniCPM-o 4.5
   - Google: Gemma 4 12B
3. Click Download. Clipper downloads the llama.cpp runtime first, then the
   selected model. Progress is shown in the app.
4. When the model is ready, choose Detect highlights.

The picker shows the download size next to each tier. A model that is already
installed does not show a download tag.

Download locations:
- llama.cpp runtime:
  %LOCALAPPDATA%\Clipper\ai-runtime\llama-b12776
- AI models:
  %LOCALAPPDATA%\Clipper\ai-models\<model-id>
- Analysis cache:
  %LOCALAPPDATA%\Clipper\ai-cache

These folders are outside the install folder. They survive app upgrades and
are not removed by the uninstaller. Delete them manually only if you want to
reclaim the disk space or force a clean AI setup.

Audio ears:
The optional audio ears pass uses LFM3-Omni-2B. If the selected vision model is
LFM3, the same model handles vision and audio. If the vision model is MiniCPM or
Gemma, Clipper downloads LFM3 separately for the ears pass. Audio ears can be
turned off in the AI panel.

Local server:
The AI model dropdown also offers "Connect local server...". Enter an
OpenAI-compatible base URL, read its /v1/models list, and choose one model.
Only that model is added to the picker. The server must accept image input and
return JSON for the Director. No API key is sent. This is optional and is meant
for users who already run LM Studio, llama.cpp server, vLLM, Jan, or a similar
local endpoint.

Ollama:
Ollama is not required for the bundled setup. The app does not install it. It
remains an optional alternative backend for the CLI and existing
configurations, and for models that need Ollama-specific audio support. The
normal first-run path is the bundled llama.cpp runtime and one of the three
bundled model tiers.


CLIP WORKFLOW
-------------
Clipper 0.9 adds the post-detection workflow:

- Clip library: every scan is saved under %LOCALAPPDATA%\Clipper\library with
  keep/reject decisions, notes, tags, evidence, and export history. Reopen it
  from the Library button. A rescan inherits decisions for matching clips.
- Creator presets: lossless, YouTube Shorts, TikTok, Instagram Reels, square,
  landscape, Shorts HEVC, and frame-accurate H.264. Batch export is available.
- Filename templates: use tokens such as {source}, {index:02d}, {start}, {end},
  {score}, {preset}, {game}, and {date}.
- Automatic vertical reframe: follows action or a facecam and produces a
  smoothed 9:16 crop. Center crop is available as a predictable fallback.
- Why this clip?: shows the transcript, HUD proof, audio signals, reviewed
  windows, confidence, notes, tags, and previous exports for the selected clip.
- Watch folders and queue: add a folder, queue new recordings after they settle,
  wait for idle time and Game Guard clearance, pause, retry, and recover queue
  jobs after a restart. Queue state is stored in
  %LOCALAPPDATA%\Clipper\workflow.json.

The library and queue are local-only. They store paths, notes, tags, evidence
text, and preview JPGs, not copies of the source footage.


AI MODEL SIZES AND DISK SPACE
-----------------------------
These are verified file sizes. Download size is the compressed/network size
reported by the model manifest. Installed size is the size on disk after all
model files are present.

Model downloads:
- Lite: LFM3-Omni-2B
  Download/installed: 2,049,471,328 bytes (2.05 GB, 1.91 GiB)
- Standard: MiniCPM-o 4.5
  Download/installed: 6,121,827,584 bytes (6.12 GB, 5.70 GiB)
- Google: Gemma 4 12B
  Download/installed: 7,556,499,296 bytes (7.56 GB, 7.04 GiB)

The llama.cpp runtime:
- Download: 749,426,307 bytes (749 MB, 715 MiB)
- Installed: about 1.41 GB (1.31 GiB)

The Clipper application:
- Installer download: about 380 MiB
- Installed app: about 1.05 GB (1.0 GiB)

Approximate total disk use after setup:
- Lite only: about 4.5 GB (4.2 GiB)
- Standard plus LFM3 audio ears: about 10.6 GB (9.9 GiB)
- Google plus LFM3 audio ears: about 12.1 GB (11.2 GiB)

Leave extra free space for the analysis proxy, temporary audio, preview frames,
and exported clips. A long source video can need several gigabytes of working
space even when the models are already installed.

Windows and apps may display disk sizes in GiB while labeling them GB. The byte
counts above are the source of truth.


HARDWARE AND SOFTWARE REQUIREMENTS
----------------------------------
Required:
- Windows 10 or Windows 11, 64-bit.
- A 64-bit x64 processor.
- About 1 GB free disk for the app before AI setup.
- Internet access for the first AI runtime/model download and for update
  checks. Once the runtime and models are installed, analysis and export can run
  offline.
- No administrator rights. The installer is per-user.

Not required:
- Python.
- FFmpeg or FFprobe.
- Ollama.
- Microsoft Visual C++ Redistributable. The needed DLLs are bundled, and the
  llama.cpp runtime gets its own copy beside llama-server.exe.
- CUDA Toolkit, cuDNN, or a compiler.
- A browser, .NET, or WebView2.

NVIDIA GPU, optional but recommended:
- The bundled llama.cpp runtime is built with CUDA 12.4.
- Use an NVIDIA Windows driver version 551.61 or newer. Current NVIDIA drivers
  are recommended.
- No CUDA Toolkit install is needed. The runtime includes its own CUDA
  user-mode DLLs.
- NVENC/NVDEC hardware encode and decode are used when the NVIDIA driver and
  GPU support them. FFmpeg falls back to CPU encoding when they do not.
- AMD and Intel GPUs can run the app, but the bundled llama.cpp AI runtime
  and Clipper's GPU/NVENC path are NVIDIA/CUDA-focused.

CPU-only AI:
- The llama.cpp runtime can run without a CUDA device. It uses the CPU and is
  much slower. This is a fallback, not the recommended configuration.
- OpenCV motion scoring and audio analysis already run on the CPU. The GPU is
  used for decode/encode and the AI models.

VRAM guidance:
The model picker shows conservative targets:
- Lite LFM3: about 4 GB VRAM.
- Standard MiniCPM: about 8.5 GB VRAM.
- Google Gemma: about 10.5 GB VRAM.

These are planning targets, not exact consumption. Actual usage depends on
context size, the vision projector, driver, desktop composition, and other GPU
apps. On the Clipper test machine (RTX 3080 10 GB, driver 610.88, Windows,
8192 context for LFM3 and 4096 for the larger models), measured model load was
approximately:
- LFM3: 2.9 GiB above idle.
- MiniCPM: 6.4 GiB above idle.
- Gemma: 7.8 GiB above idle.

If the LFM3 audio ears run at the same time as a different vision model, add
about 2.9 GiB. Direct dual residency on the 10 GB test card peaked at 9,733 MiB
of 10,240 MiB, leaving only about 0.5 GiB. Clipper therefore serializes the two
models when they do not fit with 1 GB of headroom, so a 10 GB card loads vision,
unloads it for the ears pass, then reloads it for the final edit. With the
guard, a real 35-second scan peaked at 7,396 MiB and only one model was
resident. This is slower but keeps a safe margin. Low-power mode forces the same
swap and also lowers threads and proxy resolution.

Clipper does not use total capacity alone. Immediately before each model start,
and again between the vision, ears, and final-edit stages, it queries the
selected NVIDIA GPU for total, used, and free VRAM. It respects
CUDA_VISIBLE_DEVICES and uses measured model allocations (LFM3 3,000 MiB,
MiniCPM 6,600 MiB, Gemma 8,100 MiB) plus a 1,024 MiB reserve. Games, OBS,
browsers, and other GPU workloads therefore reduce the available budget.

On a clean 10 GB desktop, about 9,140 MiB was free; both models needed
9,600 MiB plus the reserve, so Clipper serialized. With a 3,072 MiB external
CUDA allocation, 6,037 MiB was free: MiniCPM alone did not fit and was refused
with a clear message, while LFM3 alone loaded and completed the scan. If GPU
memory telemetry is unavailable, Clipper uses sequential inference and
conservative checks rather than assuming the memory is free. If a start still
hits CUDA out-of-memory, it stops the failed process, waits for the allocation
to be released, retries once, and then reports the error.

If VRAM is still tight, use Lite, lower the analysis settings, close games and
browser hardware acceleration, or use Low-power mode.


PERFORMANCE NOTES
-----------------
- GPU/NVENC is used when the one-frame NVENC test passes. It is used for the
  analysis proxy and optional re-encode.
- Decoding may use the CPU depending on the source codec.
- OpenCV motion scoring and audio RMS stay on the CPU. GPU motion scoring is
  not implemented.
- Low-power mode uses 2 CPU threads, a 256 px wide 2 fps analysis proxy, and
  below-normal process priority. It also forces one model at a time. The AI
  director still runs. Tight-VRAM cards may serialize automatically even when
  Low-power mode is off.
- Game Guard pauses AI work and releases model VRAM while a known game is
  running. It resumes when the game closes.
- Long interactions can stay 30-90 seconds. Clipper does not force every
  highlight into a six-second peak.


TROUBLESHOOTING
---------------
Installer or SmartScreen:
- The build is unsigned, so Windows may warn. Use "More info" then "Run anyway"
  only for a file downloaded from the official release page.
- If installation fails because Clipper is running, close it from Task Manager
  and retry.
- If an upgrade does not appear, check that you ran the new installer and that
  the shortcut points to %LOCALAPPDATA%\Programs\Clipper\Clipper.exe.

AI runtime or model download fails:
- Check the internet connection, VPN/proxy, and firewall. Clipper downloads from
  GitHub Releases, the Ollama registry, and Hugging Face.
- Check free disk space. The runtime needs about 1.4 GB installed and a model
  needs 2-8 GB.
- Retry the download. Partial downloads are kept as .part files and resume when
  possible. Runtime and model archives are checked against pinned SHA-256
  hashes.
- If a download is repeatedly corrupted, delete the matching .part file or the
  incomplete model folder and retry.
- Antivirus or a download accelerator can interrupt large files. Add an
  exception for %LOCALAPPDATA%\Clipper if needed.

Model does not start or analysis fails:
- Open the model's server log:
  %LOCALAPPDATA%\Clipper\ai-models\<model-id>\server.log
- Update the NVIDIA driver to 551.61 or newer.
- Close games and other GPU-heavy apps, then retry. Clipper serializes models
  automatically when live free VRAM is insufficient. Use Lite or Low-power mode
  if memory remains tight.
- If the error says insufficient free VRAM, close GPU-heavy applications or
  turn off Audio ears before retrying.
- Check that Windows has enough free RAM and disk space for the model and the
  analysis proxy.
- Try the Lite model to confirm the runtime works. If Lite works and a larger
  model does not, the larger model is probably running out of VRAM.
- If the runtime folder was partially deleted, remove
  %LOCALAPPDATA%\Clipper\ai-runtime\llama-b12776 and download it again.

"No supported vision model installed":
- Choose a bundled model and click Download, or use Connect local server.
- If a model was deleted manually, download it again.

Local server connection fails:
- Use the base URL, for example http://127.0.0.1:1234. Clipper appends
  /v1/models and /v1/chat/completions.
- Make sure the server is running and exposes /v1/models.
- The selected model must accept image input and return JSON. Text-only models
  will not work with the Director.
- Clipper does not send an API key. Use a local endpoint that does not require
  one.

Ollama:
- Ollama is optional. If you use an existing Ollama setup, start it yourself and
  make sure a supported vision model is installed. The bundled llama.cpp path
  does not need it and does not install it.

Settings and reset:
- Clipper settings are stored in the Windows registry under
  HKCU\Software\hatermedia\Clipper. Back up the key before deleting it.
- The installer keeps footage, models, and caches. The uninstaller removes the
  app and its settings but not your footage or the AI model/runtime folders.
- To reclaim model disk space, delete %LOCALAPPDATA%\Clipper\ai-models and
  %LOCALAPPDATA%\Clipper\ai-runtime after closing Clipper.


UPDATES AND UNINSTALL
---------------------
The installed build checks GitHub Releases at launch. When an update is
available, Clipper downloads the installer, verifies its SHA-256, and installs
it silently when you choose to install. The portable build opens the release
page instead of replacing itself.

Uninstall from Windows Settings > Apps > Clipper, or run Uninstall.exe in the
install folder. The uninstaller removes the app and its settings. It does not
remove your footage, exports, AI models, the llama.cpp runtime, or analysis
caches.

Running a newer installer over an older install keeps the per-user models and
runtime. They are not downloaded again unless a file is missing or fails its
size/hash check.


PRIVACY
-------
Footage never leaves this machine. Analysis, OCR, transcription, and export are
local. Clipper has no accounts and no telemetry. Network access is used for:
- The optional GitHub update check.
- The AI runtime and model downloads when you request them.
- The local server URL you configure. That server is expected to be on your
  machine or local network. Clipper does not send an API key.

Release downloads use HTTPS and are checked against SHA-256 hashes.


LICENSE AND LINKS
-----------------
Clipper is MIT licensed. See LICENSE. You are responsible for the rights to the
footage you process.

Project: https://github.com/hatermedia/clipper
Website: https://hatermedia.github.io/clipper/
Issues:  https://github.com/hatermedia/clipper/issues
