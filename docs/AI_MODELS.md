# Local AI models

Clipper runs every model locally. The default setup uses a pinned llama.cpp
runtime that Clipper downloads on demand. There is no system install and no
background daemon. The app's AI model picker contains bundled model tiers and
explicitly connected OpenAI-compatible local servers.

## Runtime

The bundled runtime is llama.cpp release `b12776`, built for Windows x64 with
CUDA 12.4. It is downloaded to:

```text
%LOCALAPPDATA%\Clipper\ai-runtime\llama-b12776
```

Downloads:

| File | Size |
| --- | ---: |
| `llama-cuda.zip` | 357,982,680 bytes |
| `cudart.zip` | 391,443,627 bytes |
| **Total download** | **749,426,307 bytes (749 MB, 715 MiB)** |
| **Installed size** | **about 1.41 GB (1.31 GiB)** |

The runtime archive does not include the Microsoft Visual C++ runtime. Clipper
copies `msvcp140.dll`, `vcruntime140.dll`, `vcruntime140_1.dll`, and the related
runtime DLLs beside `llama-server.exe` after extraction and before the server
starts. This keeps the runtime self-contained on a clean Windows install. No
Visual C++ Redistributable is required.

The runtime also includes its own CUDA user-mode DLLs. The CUDA Toolkit is not
required. An NVIDIA Windows driver version 551.61 or newer is required for the
CUDA 12.4 build; current drivers are recommended.

## Model tiers

Models are stored under `%LOCALAPPDATA%\Clipper\ai-models\<model-id>` and
survive app upgrades.

| Tier | Model | Download / installed | Recommended VRAM | Audio | Status |
| --- | --- | ---: | ---: | --- | --- |
| Lite | LFM3-Omni-2B | 2,049,471,328 bytes (2.05 GB, 1.91 GiB) | about 4 GB | native | Tested; fastest, good ears, weaker final visual judgment |
| Standard | MiniCPM-o 4.5 (vision) | 6,121,827,584 bytes (6.12 GB, 5.70 GiB) | about 8.5 GB | via LFM3 ears | Tested on 10 GB; good HUD reading and clips |
| Google | Gemma 4 12B (vision) | 7,556,499,296 bytes (7.56 GB, 7.04 GiB) | about 10.5 GB | via LFM3 ears | Tested on 10 GB; strongest, slowest |

The **Standard** and **Google** tiers combine their vision model with the Lite
LFM3 ears model. MiniCPM-o and Gemma 4 audio encoders are not exposed by
upstream llama.cpp today; using LFM3 for audio keeps the stack on one runtime
and one GPU budget.

### Actual VRAM use

The VRAM column is a conservative planning target from the model manifests, not
an exact measurement. Actual use depends on context size, the vision projector,
driver, desktop composition, and other GPU apps.

Measured on the Clipper test machine (RTX 3080 10 GB, NVIDIA driver 610.88,
Windows, 8192 context for LFM3 and 4096 for the larger models), model load was
approximately:

| Model | Measured above idle | Total GPU use including desktop |
| --- | ---: | ---: |
| LFM3-Omni-2B | 2.9 GiB | about 4.4 GiB |
| MiniCPM-o 4.5 | 6.4 GiB | about 7.8 GiB |
| Gemma 4 12B | 7.8 GiB | about 9.5 GiB |

If the LFM3 audio ears run at the same time as a different vision model, add
about 2.9 GiB. On a 10 GB card, use Low-power mode with Standard or Google, or
close other GPU apps. On 8 GB or less, Lite is the safe choice.

Practical minimum and recommended VRAM:

- Lite: 4 GB minimum, 6 GB recommended.
- Standard: 8.5 GB minimum, 10 GB recommended.
- Google: 10 GB works with little headroom, 12 GB recommended.

The Audio ears setting can be turned off to save the extra model. If the
selected vision model is LFM3, the same model handles vision and audio and no
second copy is used.

## Disk space

The app, runtime, and models are separate:

- Clipper installer download: about 380 MiB.
- Installed app: about 1.05 GB (1.0 GiB), including the bundled Whisper model.
- llama.cpp runtime: 749 MB download, about 1.41 GB installed.
- Models: see the table above.

Approximate total disk use after setup:

| Configuration | Approx. total |
| --- | ---: |
| App + runtime + Lite only | 4.5 GB (4.2 GiB) |
| App + runtime + Standard + LFM3 ears | 10.6 GB (9.9 GiB) |
| App + runtime + Google + LFM3 ears | 12.1 GB (11.2 GiB) |

Leave extra space for the analysis proxy, temporary audio, preview frames, and
exports. A long source video can need several gigabytes of working space even
when the models are already installed.

Windows and apps may display disk sizes in GiB while labeling them GB. The byte
counts in this document are the source of truth.

## Setup flow

1. Open the **AI model** dropdown in the Local AI director panel.
2. Choose a bundled tier or **Connect local server...**.
3. Click **Download** for a bundled tier. Clipper installs the runtime first,
   then the model, with progress shown in the panel.
4. Wait for the model to report ready, then start a scan.

Downloads are pinned by size and SHA-256. Partial downloads are kept as `.part`
files and resume when possible. Models and the runtime are shared by every
Clipper install for the same Windows user.

## Audio ears

For each candidate clip the ears pass:

1. Slices the 16 kHz WAV into 5-second chunks (2.5-second steps).
2. Asks LFM3 for `speech`, `tone`, `laughter`, `shouting`, `sound`, and `proof`.
3. Cross-checks the heard words against Whisper's transcript.
4. Trusts a reaction only when the words overlap or the acoustic energy agrees.
5. Uses the best trusted chunk to boost confidence and tighten the clip.

The ears pass never invents a candidate and never deletes a HUD-verified clip.

## Local server

The AI model picker also offers **Connect local server...**. It accepts an
OpenAI-compatible base URL, reads `/v1/models`, and lets the user explicitly
choose which model to add. Only that chosen model appears in the picker; the URL
and model list are saved for future launches. This works with LM Studio,
llama.cpp server, vLLM, Jan, and similar local endpoints. The model must support
vision input and JSON responses for the Director. No API key is sent.

Use the base URL, for example `http://127.0.0.1:1234`. Clipper appends
`/v1/models` and `/v1/chat/completions`. A server that requires an API key is
not currently supported by this connection flow.

## Ollama

Ollama is **not required** for the bundled setup. Clipper does not install it
and the normal picker does not list Ollama models. It remains an optional
alternative backend for the CLI and existing configurations, and for models
that need Ollama-specific audio support. The normal first-run path is the
bundled llama.cpp runtime plus one of the three model tiers.

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

## Troubleshooting

- **Runtime download fails:** check internet, VPN/proxy, firewall, and free
  disk. Retry; partial files resume. The runtime is about 1.41 GB installed.
- **Model download fails:** check free disk and retry. Model folders can be
  removed and downloaded again.
- **Model does not start:** open
  `%LOCALAPPDATA%\Clipper\ai-models\<model-id>\server.log`. Check the NVIDIA
  driver, free VRAM, and other GPU apps.
- **Out of VRAM:** use Lite, close games and GPU-heavy apps, or enable
  Low-power mode. Standard and Google are tight on a 10 GB card.
- **No CUDA device:** the runtime can fall back to the CPU, but it is much
  slower. NVIDIA/CUDA is the recommended path.
- **Local server fails:** confirm the base URL, `/v1/models`, and that the
  model accepts images and returns JSON. No API key is sent.
- **Audio ears fail:** the ears pass needs LFM3-Omni-2B. Download it from the
  Audio ears row or turn audio ears off.

## Still open

- MiniCPM-o 4.5 native audio needs `llama.cpp-omni`; upstream llama.cpp cannot
  load its audio projector.
- Gemma 4 12B native audio works through Ollama's OpenAI endpoint, not
  llama.cpp; the current tier uses LFM3 ears instead.
- Qwen2.5-VL 7B GGUF produced good clips but was much slower than Ollama on
  the test machine, so it is not part of the bundled picker yet.
