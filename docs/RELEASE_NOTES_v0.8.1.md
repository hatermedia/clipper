# Clipper v0.8.1

Launcher-safe Game Guard and a strictly vision-only model picker.

## Game Guard: launchers are not games

- Riot Client is now ignored, including `RiotClientServices`,
  `RiotClientCrashHandler`, `RiotClientUX`, and League Client.
- Added launcher exclusions for Steam, Epic, Battle.net, EA Desktop, Ubisoft
  Connect, GOG Galaxy, Xbox app, Playnite, Rockstar, Bethesda, Paradox,
  Wargaming, Minecraft Launcher, and itch.
- Launcher install paths such as `\Riot Games\Riot Client\` are rejected before
  the game-library path heuristics run, so future launcher helper processes
  cannot be mistaken for games.
- Real Riot games still detect normally: `VALORANT-Win64-Shipping.exe`,
  `League of Legends.exe`, and the game folders under `Riot Games`.
- Added regression tests for Riot Client, League Client, and a broad set of
  common launchers and launcher install paths.

## Only supported vision models

- The model picker now lists only the families the Director is built and tested
  around: **gemma3**, **qwen2.5vl**, and **qwen3-vl**.
- Removed non-vision/text models, the “Other local models” group, and the custom
  model tag option. If a downloaded model cannot inspect frames, it is not
  offered.
- If no supported vision model is installed, Detect highlights stays disabled
  and the setup panel shows exactly what to install.

## Quality

- The Director remains the only highlight path: full-clip windows, Whisper
  transcript, HUD evidence, acoustic/motion signals, and strict JSON verdicts.
- Added model-family tests and kept the full-clip coverage test so every window
  of a clip is reviewed.

## Install

Download `ClipperSetup-0.8.1.exe`, run it, and launch Clipper. The installer is
per-user and preserves footage, caches, and settings during upgrades. SHA-256
checksums are in `SHA256SUMS.txt` on the release page.
