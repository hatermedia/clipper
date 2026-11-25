# Clipper v0.7.4

One-click local AI prerequisites, without making the base installer huge.

## One-click Ollama setup

The AI panel now has **Install Ollama**. It:

- Downloads the official `OllamaSetup.exe` from GitHub over HTTPS.
- Verifies GitHub's published SHA-256 when available, then the Windows
  Authenticode signature from Ollama Inc.
- Installs Ollama per-user, with no admin prompt.
- Starts the local Ollama server and refreshes the model list.
- Shows download progress, supports Cancel, and resumes a partial download if
  you retry.
- Refuses the download if the size cap, checksum, or signer does not match.

After Ollama is ready, **Install model** downloads `gemma3:4b` on 6 GB cards or
`qwen2.5vl:7b` on 8 GB+ through Ollama. Nothing is uploaded.

## Why not bundle the model

Ollama's Windows prerequisite is about 1.9 GB by itself because it ships the
CUDA/ROCm runners. A vision model is another 3–6 GB. Bundling either would make
every Clipper download large, including for people who only want Lite mode.
The base installer stays around 382 MB; AI is a deliberate, visible opt-in.

## Other changes

- The AI setup panel no longer sends users to a browser to find Ollama.
- Existing Ollama installs are detected automatically; Refresh starts the
  server if it is installed but not running.
- The privacy copy now lists the three network actions exactly: update check,
  Ollama prerequisite download, and model download.
- Release notes, README, portable README, and website updated for v0.7.4.

## Install

Download `ClipperSetup-0.7.4.exe`, run it, and launch Clipper. The installer is
per-user and preserves footage, caches, and settings during upgrades. The
portable zip is available for users who do not want an installer.

SHA-256 checksums are in `SHA256SUMS.txt` on the release page.
