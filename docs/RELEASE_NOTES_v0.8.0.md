# Clipper v0.8.0

AI-only highlighting, a grouped local model picker, and caption buttons that sit
in the corner.

## AI is now the only highlighting path

- Removed Lite mode, the AI on/off toggle, and the heuristic-only fallback.
  Every scan is reviewed by the local vision director.
- **Detect highlights** stays disabled until Ollama and a local model are ready.
  If Ollama is installed but not running, Clipper starts it in the background.
- The director still reviews the whole clip in short windows, with Whisper
  transcript, HUD/audio signals, and sampled frames. A new regression test
  verifies that every 15-second window of a full clip is reviewed.
- If the director fails, Clipper reports the error instead of silently replacing
  it with audio/motion peaks.

## Model picker

- The model selector is grouped into **Vision models** and **Other local
  models**, followed by **Custom model…** for any Ollama tag.
- Custom tags are added to the picker and saved.
- This uses local Ollama models only. Subscription/cloud models are not included,
  because that would upload clips and break the local-only design.

## Window and input polish

- Minimize, maximize/restore, and close now sit flush in the top-right corner,
  with thin Edge-style icons and no gaps between the buttons.
- The drop zone now says **Drop a video here** with **or click to choose a video
  file** underneath. Browse still opens the native folder picker.
- Removed stale Lite/heuristic wording, including the low-power tooltip that
  told users to turn off the director.

## Setup

1. Install Clipper.
2. Open Clipper and click **Install Ollama**.
3. Click **Install model** and choose `gemma3:4b` on 6 GB cards or
   `qwen2.5vl:7b` on 8 GB+.
4. Detect highlights becomes available when the local director is ready.

SHA-256 checksums are in `SHA256SUMS.txt` on the release page.
