# Clipper v0.8.2

Faster installs, true in-place upgrades, and better game-aware direction for
the NVIDIA capture folders.

## Installer

- Switched the installer from solid LZMA to **per-file LZMA**. Solid compression
  forced the installer to decompress the whole ~1 GB payload before reaching the
  145 MB Whisper `model.bin`, which made a normal install look stuck. Per-file
  extraction gets to `model.bin` immediately; the installer is slightly larger,
  but installation is much more responsive.
- Removed the install-directory page. Upgrades now always reuse the existing
  Clipper location, so a new installer overwrites the old version instead of
  creating a second copy.
- Added a registry fallback to the Windows uninstall entry for older installs
  whose primary install key is missing.
- Existing settings, footage, and caches are still preserved.

## Game-aware direction

- Expanded automatic game detection for the NVIDIA library, including Arc
  Raiders, Chained Together, Destiny 2, Forza Horizon 5, Garry's Mod, PEAK,
  Satisfactory, Muck, FiveM, and Warframe.
- Added Director guidance for those games so the model knows what a highlight
  looks like instead of falling back to generic advice.
- **Desktop and Omegle-style clips now use Social mode.** The director ignores
  game HUD and gameplay events and prioritises jokes, trolling, reactions,
  banter, and visible human responses.
- Game Guard still ignores launchers and only pauses for actual game processes.

## Ollama setup and memory

- The Ollama installer now runs silently without leaving its tray app,
  sign-in/onboarding window, or IDE-connection flow open. Clipper creates the
  onboarding-complete marker, kills the GUI while the installer runs, and starts
  only its own headless `ollama serve` process.
- **Install model** now lets you choose `gemma3:4b`, `qwen2.5vl:7b`, or
  `qwen3-vl:4b` instead of silently picking one.
- Model pulls stream progress through Ollama's API, so the panel shows download
  percentages instead of appearing frozen.
- Closing Clipper unloads the local model and stops the server Clipper started,
  freeing VRAM. Cancelling a job also asks Ollama to unload the model.
- The Advanced toggle no longer shifts or jumps when opened and closed.

## Verified upgrade

On the test machine, a silent 0.8.2 install over 0.8.1 completed in **40.8
seconds**, updated the existing `%LOCALAPPDATA%\Programs\Clipper` folder in
place, and left exactly one Clipper installation.

## Real-footage validation

- Full-clip Director test on a 74-second Rocket League capture found the goal
  at 55.0-73.9s.
- Full-clip test on a 90-second Chained Together capture found a 45-second
  banter interaction.
- Full-clip test on a 90-second Desktop capture found a 30-second trolling
  exchange in Social mode.

## Install

Download `ClipperSetup-0.8.2.exe`, run it over any older Clipper install, and
launch Clipper. The installer is per-user and preserves footage, caches, and
settings. SHA-256 checksums are in `SHA256SUMS.txt` on the release page.
