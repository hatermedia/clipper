# Local AI models

Clipper runs every model locally. The **bundled llama.cpp runtime** is a
one-click download (no system install, no daemon). Models are stored under
`%LOCALAPPDATA%\Clipper\ai-models` and survive app upgrades.

## Why llama.cpp

- No admin install and no background Ollama service.
- One pinned server binary, verified by SHA-256.
- GGUF models can be downloaded, resumed, and verified individually.
- LFM3-Omni-2B runs vision **and** audio in the same process, which is what
  makes the audio-ears pass possible without a second runtime.

Ollama remains supported as an optional backend for users who already have it
and for models that need Ollama's audio engine.

## Tiers

| Tier | Model | Files | VRAM | Audio | Status |
| --- | --- | --- | --- | --- | --- |
| Lite | LFM3-Omni-2B | 2.0 GB | ~4 GB | native | Tested; fast, good ears, weaker final visual judgment |
| Standard | MiniCPM-o 4.5 (vision) | 5.7 GB | ~8.5 GB | via LFM3 ears | Tested on 10 GB; good HUD reading and clips |
| Google | Gemma 4 12B (vision) | 7.6 GB | ~10.5 GB | via LFM3 ears | Tested on 10 GB; strongest, slowest |

The **Standard** and **Google** tiers combine their vision model with the Lite
LFM3 ears model. MiniCPM-o and Gemma 4 audio encoders are not exposed by
upstream llama.cpp today; using LFM3 for audio keeps the stack on one runtime
and one GPU budget.

## Audio ears

For each candidate clip the ears pass:

1. Slices the 16 kHz WAV into 5-second chunks (2.5-second steps).
2. Asks LFM3 for `speech`, `tone`, `laughter`, `shouting`, `sound`, and `proof`.
3. Cross-checks the heard words against Whisper's transcript.
4. Trusts a reaction only when the words overlap or the acoustic energy agrees.
5. Uses the best trusted chunk to boost confidence and tighten the clip.

The ears pass never invents a candidate and never deletes a HUD-verified clip.

## Low-power mode

Low-power mode keeps only one model resident at a time when the selected vision
model and the audio ears are different. It unloads the vision model before the
ears pass, then reloads it for the final edit, and releases both models when the
video finishes. This is significantly slower because every video pays the model
load cost again. If both roles use the same model, no swap is needed. The mode
also lowers analysis threads and proxy resolution.

## Model sources

- LFM3-Omni-2B: Ollama registry blobs, LFM Open License v1.0.
- MiniCPM-o 4.5: `openbmb/MiniCPM-o-4_5-gguf`, Apache-2.0.
- Gemma 4 12B: Ollama registry blobs, Gemma Terms of Use.
- Qwen2.5-VL 7B: `ggml-org/Qwen2.5-VL-7B-Instruct-GGUF`, Apache-2.0.

Every download is pinned by size and SHA-256. Runtime archives are pinned to
llama.cpp release `b12776`.

## Still open

- MiniCPM-o 4.5 native audio needs `llama.cpp-omni`; upstream llama.cpp cannot
  load its audio projector.
- Gemma 4 12B native audio works through Ollama's OpenAI endpoint, not
  llama.cpp; the current tier uses LFM3 ears instead.
- Qwen2.5-VL 7B GGUF produced good clips but was much slower than Ollama on
  the test machine, so it is not part of the bundled picker yet.
