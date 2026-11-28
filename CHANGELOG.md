# Changelog

All notable changes to Clipper are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/).

## [Unreleased]

Security and consistency fixes from a full code audit.

### Security

- Updater: optional Ed25519 signature over the release `SHA256SUMS` file
  (stdlib-only verifier, `packaging/sign_release.py` for keys and signing).
  Once `UPDATE_PUBLIC_KEYS` is set, unsigned or wrongly signed releases are
  refused. Installers with a broken or untrusted Authenticode signature are
  always refused; `UPDATE_PUBLISHER` can require a specific publisher.
- Updater: a downloaded update is no longer installed silently on the next
  launch; the user must click **Restart and install**.
- Updater and installer only stop `Clipper.exe` processes running from the
  install folder. The `taskkill /IM Clipper.exe` fallbacks are gone.
- Web UI: refuses foreign `Host` headers (DNS rebinding), cross-site and
  foreign-origin API calls; adds CSP and related headers; no longer reports
  the working directory or FFmpeg path; validates the x264 preset.
- Web UI: optional `CLIPPER_ROOTS` confines browse, scan, analyze, thumbnail,
  and export paths. The Docker image sets it to `/footage:/out`.
- Web UI: Alpine.js and a compiled Tailwind stylesheet are vendored; the page
  no longer loads scripts from CDNs.
- Local server URL must be `http(s)://`; the desktop app warns before sending
  footage to a server outside the local network, and flags plain HTTP.
- The bundled llama.cpp server now requires a random per-launch API key.
- Transcript, OCR, and earlier model text are fenced as untrusted data in
  director prompts (prompt version `director-v16`).
- Frozen builds use their bundled FFmpeg before anything on `PATH`;
  `nvidia-smi` is resolved from System32 first.

### Changed

- The web UI and Docker image now use the AI director, like the desktop app
  and CLI, instead of the old audio/motion peak picker.
- Removed the hidden Ollama download/silent-install path. Clipper no longer
  downloads, installs, or force-closes Ollama; an Ollama you install yourself
  still works as an optional backend.
- Removed the unused legacy single-peak AI reviewer.
- Only one desktop instance can run at a time, so the library and queue are
  never edited by two copies.
- Model downloads show the model licence once before the first download.
- Export filenames keep letters and digits from any script (for example
  Japanese or accented names); oversized format widths in name templates are
  refused.
- The AI path no longer computes the unused fused audio/motion score.
- CI runs the test suite and a desktop smoke test on Windows and builds and
  probes the Docker image.

## [0.9.0] - 2026-11-28

Local test build. Not published.

### Added

- **Clip library.** Previous scans are saved locally with clip decisions,
  notes, tags, evidence, and export history. A rescan inherits decisions for
  clips whose boundaries still match.
- **Creator export presets.** YouTube Shorts, TikTok, Instagram Reels, square,
  landscape, Shorts HEVC, and frame-accurate H.264 outputs. The desktop and CLI
  share one preset registry.
- **Automatic vertical reframe.** Action and facecam tracking produce a smoothed
  FFmpeg crop path for 9:16 and 1:1 exports, with center-crop fallback.
- **Filename templates.** `{source}`, `{index}`, `{start}`, `{end}`, `{duration}`,
  `{score}`, `{peak}`, `{preset}`, `{game}`, and `{date}` are available in the
  desktop and CLI.
- **Why this clip?** panel. Shows the transcript, HUD proof, audio and motion
  signals, reviewed windows, final-edit proof, confidence, notes, tags, and past
  exports for the selected clip.
- **Watch folders and scan queue.** New recordings are queued after they settle,
  scanned when the PC is idle and no known game is running, and recovered after
  a restart. The queue supports pause, retry, clear-finished, progress, and ETA.
- CLI flags: `--export-preset` (alias `--format`), `--reframe`, and
  `--name-template`.

### Changed

- Export results now include per-clip items and warnings, so the library can
  attach output history and the UI can report a reframe fallback.
- Clip metadata now survives scan JSON round-trips, including evidence, keep
  state, notes, tags, and exports.

### Fixed

- Final evidence now discards schema placeholders that a small model sometimes
  echoes from the prompt instead of displaying them as proof.
- Vertical reframe commands are interpolated at 60 Hz, removing the visible
  0.5-second crop steps from the first tracking implementation.
- Bundled llama.cpp servers now stop on process exit, including the hidden
  story-test path. The frozen AI check previously left `llama-server` running.
- Detect now checks the selected bundled model or local server instead of
  requiring an Ollama process.
- Desktop scans and the watch queue exclude the export folder, so Clipper does
  not analyze its own output.
- The watch queue remembers manual scans and active folder jobs, preventing
  duplicate work.

## [0.8.4] - 2026-11-27

### Changed

- **Bundled AI setup documentation.** The installer README, website, main
  README, AI model guide, CLI portable README, and third-party notices now
  describe the bundled llama.cpp runtime and model tiers. Ollama is optional.
- **Live VRAM guard.** Clipper checks the selected GPU's total, used, and free
  memory immediately before each model start, and again between stages. It uses
  measured model allocations plus a 1 GiB reserve, so games and other GPU
  workloads change the decision. The default 10 GB Standard plus LFM3
  configuration loads one model at a time. Telemetry failure uses sequential
  inference, and a CUDA out-of-memory startup gets one clean retry before a
  clear error.
- **Low-power clarification.** Low-power mode still forces one model at a time
  and lowers threads, proxy resolution, and process priority.
- **Current media.** Replaced stale screenshots and added a workflow demo for
  footage selection, detection, preview, and export.

### Fixed

- Removed automatic Ollama startup and stale Ollama setup status from the
  desktop app. The picker uses bundled models and explicit local servers.
- Fixed the AI model Download button label clipping.
- Corrected CLI help text that still described hybrid audio and motion
  detection.

## [0.8.3] - 2026-11-26

### Fixed

- **Update downloads are cached.** A verified installer is reused from
  `%LOCALAPPDATA%\Clipper\updates` instead of downloading the full app again.
- **Later installs on next launch.** The pending installer is persisted and
  applied silently on the next Clipper start.
- **Restart and install no longer silently fails.** Removed the confirmation
  step and made the updater wait for the helper to confirm startup; failures
  keep Clipper open and show an error.
- Pending installers are cleared after the new version launches.

## [0.8.2] - 2026-11-26

### Changed

- **Faster installer extraction.** Switched from solid LZMA to per-file LZMA so
  the bundled Whisper model no longer waits behind the whole payload.
- **In-place upgrades.** Removed the install-directory page and added an
  uninstall-registry fallback, so a newer installer overwrites the existing
  install instead of creating a second copy.
- **More game-aware direction.** Added NVIDIA-library game aliases and Director
  guidance for Arc Raiders, Chained Together, Destiny 2, Forza Horizon 5,
  Garry's Mod, PEAK, Satisfactory, Muck, FiveM, and Warframe.
- **Social/Desktop clips.** Desktop and Omegle-style footage is detected as
  Social, with guidance that ignores game HUD and prioritises jokes, trolling,
  reactions, and banter.
- **Silent Ollama setup.** No tray/onboarding/IDE window; Clipper starts a
  headless server it can stop. Install model now offers a supported-model
  choice, and progress streams through Ollama's API.
- **Memory cleanup.** Closing Clipper unloads the model and stops its Ollama
  server; cancelling a job unloads the model too.
- Fixed the Advanced toggle width/scroll jump.

## [0.8.1] - 2026-11-26

### Fixed

- **Game Guard no longer treats launchers as games.** Riot Client components,
  League Client, Steam, Epic, Battle.net, EA Desktop, Ubisoft Connect, GOG
  Galaxy, Xbox app, Playnite, Rockstar, Bethesda, Paradox, Wargaming, Minecraft
  Launcher, and itch are excluded by process family and install path.
- **Only supported vision models are listed.** The picker now contains
  `gemma3`, `qwen2.5vl`, and `qwen3-vl` models only. Text models, the “Other
  local models” group, and custom tags were removed.
- Added launcher regression tests and model-family tests.

## [0.8.0] - 2026-11-26

### Changed

- **AI-only highlighting.** Removed Lite mode, the AI toggle, and the
  heuristic-only fallback. Detect stays disabled until a local model is ready,
  and director failures are reported instead of replaced with non-AI peaks.
- **Grouped model picker.** Local vision models, other installed Ollama models,
  and a custom model tag option. Custom tags are saved.
- **Corner caption buttons.** Edge-style minimize/maximize/close buttons fill the
  top-right corner with no gaps.
- **Drop zone wording.** “Drop a video here” with “or click to choose a video
  file” underneath; Browse opens the native folder picker.
- Removed stale Lite and heuristic wording, including the low-power tooltip.
- Added a full-clip coverage test for the director.

## [0.7.5] - 2026-11-26

### Changed

- **Native input pickers.** Browse opens the Windows folder picker directly;
  clicking the drop zone opens the Windows video-file picker. Dragging still
  accepts folders and files.
- **Automatic game presets.** Removed the Game dropdown. The game is inferred
  from the footage folder or file name.
- **Lossless exports only.** Removed the frame-accurate re-encode toggle,
  encoder selector, and CRF control from the desktop app. Exports always use
  stream copy.
- **Edge-style caption buttons.** Thin line icons, zero gaps, and a matching
  close-button hover.
- Removed the legacy Fast review mode; Director and Lite are the only AI modes.
- Removed 3B-model mentions from public copy and the Discord-presence sentence
  from the Game Guard help.

## [0.7.4] - 2026-11-26

### Added

- **One-click Ollama setup.** The AI panel downloads the official Windows
  installer, verifies GitHub's SHA-256 and Ollama's Authenticode signature,
  installs it per-user, and starts the local server. Progress, cancel, and
  resume are included.
- **Model download after setup.** `gemma3:4b` for 6 GB cards and
  `qwen2.5vl:7b` for 8 GB+ are offered by the existing in-app model action.
- **Safe fallback.** If GitHub's release API is rate-limited, Clipper uses the
  official latest download URL and still verifies the signer.

### Changed

- The AI setup panel no longer opens a browser for Ollama.
- Privacy copy now distinguishes the update check, Ollama prerequisite
  download, and model download from local analysis.

## [0.6.0] - 2026-11-24

### Added

- **In-app clip preview.** Click any clip row (or double-click it) to open a
  local video player for that exact segment, with play/pause, -5s/+5s, a seek
  bar, segment time, and an Open button for the source file.
- **Live batch results.** Each file appears in the results table as soon as its
  AI scan finishes, with its clips and previews. You can review and preview
  earlier files while the rest of the batch is still running.
- **Export selected or all.** Every clip row has a checkbox. Select all/None,
  see `N of M selected`, and choose Export selected or Export all. Clicking the
  row outside the checkbox opens the preview.
- **Auto game detection.** The Game selector defaults to Auto and reads the game
  per file from the folder/name, so one NVIDIA parent folder can contain Rocket
  League, Mimesis, Valorant, etc. without changing a setting.
- **Help tooltips.** Question-mark icons next to AI model, game, mode, Game
  Guard, sensitivity, pre/post-roll, GPU, and advanced tuning explain what each
  option does on hover.

### Fixed

- The encoder dropdown no longer looks disabled when re-encode is off. It opens
  normally; choosing a concrete encoder automatically turns re-encode on, and
  switching re-encode off resets it to Auto.

## [0.5.0] - 2026-11-24

### Added

- **Rocket League and Mimesis game profiles**, plus automatic preset selection
  from the footage path. The director now looks for Rocket League goals, saves,
  passing plays, demos, overtime/0-second goals and late-night fakes, and for
  Mimesis screaming, trolling, betrayal, prop chases, and friend banter.
- **Game Guard.** Clipper detects known running games from the local process
  list, pauses AI work, and unloads the Ollama model so the game keeps the VRAM.
  It checks before analysis and between every director window, and resumes when
  the game closes. Available in the native app and as `--game-guard`.
- **6 GB GPU support.** On cards with <=7 GB VRAM the app selects
  `qwen2.5vl:3b` when installed and the director uses a 4k context; 7B remains
  the recommendation for 8 GB+. The 3B model is less accurate, but playable on
  a 6 GB card.
- Larger window controls (42x30) with larger glyphs.

### Changed

- Game-specific guidance is included in every window prompt and cached per
  game.
- `Pause AI while gaming` is on by default and shows the detected game in the
  control panel.
- Discord does not expose other games' Rich Presence to third-party apps, so
  Game Guard uses the local process list rather than pretending to read Discord.

## [0.4.0] - 2026-11-24

### Added

- **Whole-clip AI director.** With AI enabled, Clipper now transcribes the audio
  locally with Whisper, samples every 15-20s window with four frames plus the
  transcript and audio energy, and keeps the actual story beats: funny
  interactions, trolling, banter, rage, reactions, clutches, round results, and
  unusual plays. Adjacent beats merge, so a 30-90s joke or teammate interaction
  stays together instead of being reduced to six-second peaks.
- `--ai-mode director|review` (default `director`) and an AI mode selector in the
  native app. `review` keeps the older peak-review pass.
- Local Whisper transcription via `faster-whisper` (CPU int8, roughly 2.5s for
  a 90-second clip). The `base.en` model downloads once to
  `%LOCALAPPDATA%\Clipper\models\huggingface`.
- Humour-cue validation so ordinary tactical callouts are not sold as funny
  banter, and transcript-based cut tightening for conversation clips.
- Director segments can be 4-120 seconds; the preview uses the strongest
  transcript/humour moment instead of the midpoint.

### Changed

- `pip install clipper-gg` now includes `faster-whisper` and a compatible PyAV
  pin, so the AI director works from the CLI without extra steps.
- The native build bundles the Whisper runtime. The first AI run still downloads
  the model once.

### Known limitations

- Whisper hears game voice lines and human chat on the same track. The humour
  cue check helps, but a strategy chat can still be misread as banter. This
  needs a labelled set of real clips to tune.
- Whisper runs on the CPU (very fast for these clips); the vision model runs on
  the GPU. Full-GPU transcription needs cuDNN and is a future packaging step.
- The director reviews sampled windows, not every frame. A 5-minute clip is
  covered in 15-20s windows rather than frame-by-frame video understanding.

## [0.3.5] - 2026-11-24

### Added

- Published `clipper-gg` 0.3.5 on PyPI: `pip install clipper-gg` (or
  `pip install "clipper-gg[desktop]"` for the native app).

### Changed

- The main window is now frameless: the duplicate native title bar is gone,
  leaving the in-app `CLIPPER` header. The header is the drag handle, window
  edges resize natively, and minimize/maximize/close buttons live in the
  header's top-right corner.
- The app icon's white background was removed so the transparent rounded
  corners no longer show white specks in the header or taskbar.

## [0.3.4] - 2026-11-24

### Changed

- Redesigned the native app around OpenCode's dark theme: `#0c0c0e`
  background, flat panels, OpenCode blue (`#4f8bff` / `#3b5cf6`) accents, and
  the same Inter + IBM Plex Mono typography (bundled locally, no download).
- Replaced the native Windows message boxes with a frameless custom dialog for
  updates, errors, and confirmations, so the update prompt matches the app.
- Recolored the app icon to OpenCode blue with a small peach status dot.
- Section labels, table headers, timecodes, scores, and header status now use
  IBM Plex Mono; body copy uses Inter.

### Fixed

- Long input and output paths display from the start instead of scrolling to
  the end.
- The scanned-file list is hidden when empty and grows only as files are added.

## [0.3.3] - 2026-11-24

### Fixed

- `clipper gpu` now lists only vision-capable Ollama models instead of every
  installed text model.

### Verified

- The public v0.3.2 → v0.3.3 update path: detection, download, SHA-256 check,
  silent install, and relaunch from the installed Windows build.

## [0.3.2] - 2026-11-24

### Fixed

- The detached update helper now launches through the Windows shell with the
  full PowerShell path, so it survives the app closing and can replace a running
  install. It writes a short diagnostic trail to
  `%LOCALAPPDATA%\Clipper\update.log`.
- The app waits 1.2 seconds before quitting after starting the helper, giving
  Windows time to hand off the process.

### Verified

- End-to-end from the frozen 0.3.2 app using a local release feed: detection,
  download, SHA-256 verification, helper handoff after the app exited, silent
  install, and relaunch all completed.
- Users still on 0.3.0 or 0.3.1 may need to install 0.3.2 manually once if the
  old helper cannot replace the running app. Releases after 0.3.2 use the
  hardened helper.

## [0.3.1] - 2026-11-24

### Added

- `clipper --version` / `clipper -V`.
- The release flow was exercised from an installed 0.3.0 build: it detected
  0.3.1, downloaded the installer, and verified its SHA-256. The helper handoff
  that performs the silent install was hardened in 0.3.2.

### Fixed

- The portable README bundled in the native zip and installer now documents the
  installer/auto-update flow, GPU-on-by-default behavior, and optional local AI.
- Launching the installer from a source/pip CLI no longer tries to reopen
  `python.exe`; it leaves the installed app on the Start Menu.

## [0.3.0] - 2026-11-24

### Added

- **Windows installer** (`ClipperSetup-0.3.0.exe`): per-user install to
  `%LOCALAPPDATA%\Programs\Clipper`, no admin prompt, Desktop and Start Menu
  shortcuts, Add/Remove Programs entry, and a standard uninstaller. Silent
  install (`/S`) supports in-place upgrades.
- **Built-in auto-updater**: checks GitHub Releases on launch and from the
  `Updates` button, downloads the installer, verifies its SHA-256 against the
  release's `SHA256SUMS.txt`, then installs silently and relaunches. No update
  is installed without a matching checksum.
- `clipper update` and `clipper update --install` for checking and installing
  releases from the terminal.
- **Optional local AI review** using Ollama vision models (default
  `qwen2.5vl:7b`, 100% GPU). It center-crops the game viewport, adds a zoomed
  top-HUD frame for the score and kill feed, rejects black/desktop/menu frames,
  and reviews candidate windows with structured JSON. Results are cached.
- CLI flags: `--ai`, `--ai-model`, `--ai-game`, `--ai-min-confidence`, and
  `--ai-max-candidates`.
- Native AI controls: model selector, game preset, and a GPU status label.
- `clipper gpu` now reports Ollama availability and installed vision models.

### Changed

- The primary download is now the installer instead of a zip. The portable zip
  remains available for users who prefer it.
- The left control panel keeps Detect/Cancel pinned while settings scroll.
- Checkbox indicators and the AI/update bars match the dark native theme.
- AI scores blend model confidence with the audio/motion score so the results
  table reflects both signals.

### Known limitations

- The local vision pass is a review layer, not a trained kill detector. It
  reliably skips menus, loading screens, and black frames, but can still
  misjudge a quiet gameplay moment; keep clips in the results table under
  review before exporting.
- `qwen2.5vl:7b` needs roughly 6 GB of VRAM at an 8k context. Smaller GPUs can
  use `qwen2.5vl:3b` at lower accuracy.
- OpenCV motion scoring and audio RMS remain CPU work. NVENC accelerates only
  decode, the analysis proxy encode, re-encode, and the AI runtime.
- The installer is unsigned, so SmartScreen may warn on first run.

## [0.2.1] - 2026-11-24

### Fixed

- GPU is now **enabled by default in the native app and CLI when a real
  one-frame NVENC test passes**, instead of being off by default or trusting
  the encoder list.
- The NVENC capability probe used a 128×128 test frame, which NVIDIA rejects as
  below its minimum supported dimension. It now uses 256×144 and correctly
  reports `NVENC H.264 test encode: PASS` on an RTX 3080.
- Analysis progress now reports the actual proxy backend (`NVENC`,
  `NVENC + hardware decode`, or CPU fallback), and a requested GPU that falls
  back to CPU produces a visible warning.
- Added `clipper gpu` diagnostics with the NVENC test result, `nvidia-smi`
  summary, and a clear note that OpenCV motion scoring/audio RMS remain CPU
  work.

## [0.2.0] - 2026-11-24

### Added

- Native Qt desktop app (`clipper-desktop` / `Clipper.exe`) with:
  - native folder picker and drag-and-drop,
  - sensitivity/padding controls and advanced tuning,
  - GPU/NVENC toggle for proxy encode and optional re-encode,
  - CPU thread cap, proxy size/FPS controls, and a low-power mode,
  - in-app progress, previews, results table, cancel, and export.
- Native Windows portable build now ships `Clipper.exe` (windowed, no console)
  with Python, PySide6, FFmpeg, and FFprobe bundled.
- CLI hardware controls: `--threads`, `--proxy-width`, `--gpu`, `--low-power`,
  and `--encoder auto`.
- Analysis defaults to a balanced half-core thread cap instead of using every
  core; low-power mode lowers process priority and caps threads/FPS/proxy size.

### Changed

- `clipper` with no arguments now opens the native desktop app when PySide6 is
  installed. `clipper ui` remains available as the optional local web UI.
- Re-encode defaults to `auto` (NVENC when available, libx264 fallback).

## [0.1.1] - 2026-11-23

### Added

- Windows x64 portable build with Python 3.13, FFmpeg, FFprobe, the web UI,
  and launcher scripts bundled. Unzip and double-click `Clipper UI.cmd`; no
  Python or FFmpeg install required.
- Frozen-build FFmpeg discovery: the executable now looks in its own folder,
  `bin/`, and `ffmpeg/bin/` before falling back to `PATH`.
- Public landing page, demo video/GIF, social preview, three guides, and a
  done-for-you clip request flow.

## [0.1.0] - 2026-11-22

### Added

- Folder and single-file batching for `.mp4`, `.mkv`, `.mov`, and `.avi`.
- Audio spike detector: 16 kHz mono PCM, 50 ms RMS windows, 4-second rolling
  median baseline, robust z-score, absolute-loudness blend, and p99
  normalization.
- Visual activity detector: FFmpeg 320px / 4fps proxy, OpenCV frame differencing,
  90th-percentile change, and brightness-flash scoring.
- Hybrid fusion with configurable audio/motion weights, agreement bonus,
  adaptive percentile peak picking, minimum peak spacing, smart padding, and
  overlapping-window merging.
- CLI with `--input`, `--output`, `--dry-run`, `--pre`, `--post`,
  `--sensitivity`, `--reencode`, hardware encoders, JSON output, and recursive
  scanning.
- Lossless stream-copy export with automatic H.264/AAC fallback when the source
  container or codec is incompatible.
- Local FastAPI + Tailwind/Alpine web UI with folder browser, sliders, preview
  thumbnails, background jobs, progress, cancellation, and export controls.
- Dry-run preview thumbnails and timestamped JSON reports.
- Synthetic footage generator and a gated end-to-end test.
- Dockerfile, GitHub Actions CI, MIT license, README, and Reddit launch kit.

### Known limitations

- Stream-copy clips can start on the previous keyframe; use `--reencode` for
  frame-accurate edges.
- Detection is heuristic. It understands loud and fast-moving, not game context.
- PyPI publication of `clipper-gg` is pending; install the release wheel or the
  GitHub source until then.

[Unreleased]: https://github.com/hatermedia/clipper/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/hatermedia/clipper/releases/tag/v0.6.0
[0.5.0]: https://github.com/hatermedia/clipper/releases/tag/v0.5.0
[0.4.0]: https://github.com/hatermedia/clipper/releases/tag/v0.4.0
[0.3.5]: https://github.com/hatermedia/clipper/releases/tag/v0.3.5
[0.3.4]: https://github.com/hatermedia/clipper/releases/tag/v0.3.4
[0.3.3]: https://github.com/hatermedia/clipper/releases/tag/v0.3.3
[0.3.2]: https://github.com/hatermedia/clipper/releases/tag/v0.3.2
[0.3.1]: https://github.com/hatermedia/clipper/releases/tag/v0.3.1
[0.3.0]: https://github.com/hatermedia/clipper/releases/tag/v0.3.0
[0.2.1]: https://github.com/hatermedia/clipper/releases/tag/v0.2.1
[0.2.0]: https://github.com/hatermedia/clipper/releases/tag/v0.2.0
[0.1.1]: https://github.com/hatermedia/clipper/releases/tag/v0.1.1
[0.1.0]: https://github.com/hatermedia/clipper/releases/tag/v0.1.0
