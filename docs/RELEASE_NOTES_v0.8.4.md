# Clipper v0.8.4

Bundled local AI setup, safer 10 GB VRAM handling, and refreshed documentation
and media.

## Local AI setup

- The installer README, website, and main documentation now describe the bundled
  llama.cpp runtime and the Lite, Standard, and Google model tiers.
- Ollama is optional. The desktop app does not install it, does not start it
  automatically, and does not require it. The normal picker lists bundled models
  and explicitly connected OpenAI-compatible local servers.
- The downloaded llama.cpp runtime gets the Microsoft Visual C++ runtime DLLs
  staged beside `llama-server.exe`. A separate Visual C++ Redistributable is not
  required.
- Runtime and model downloads are pinned by size and SHA-256 and resume when
  possible.
- The AI model Download button no longer clips its label, and the CLI help text
  describes the local AI director accurately.

## Live VRAM guard

- Clipper now checks the selected GPU's total, used, and free memory immediately
  before every model start, and again between the vision, ears, and final-edit
  stages. It no longer treats total capacity as available capacity.
- It respects `CUDA_VISIBLE_DEVICES` and uses measured incremental allocations
  (LFM3 3,000 MiB, MiniCPM 6,600 MiB, Gemma 8,100 MiB) plus a 1,024 MiB reserve.
- On the clean RTX 3080 10 GB test desktop, about 9,140 MiB was free. Both models
  needed 9,600 MiB plus reserve, so the default Standard plus LFM3 ears
  configuration serialized. A real 35-second scan peaked at 7,396 MiB with one
  `llama-server` resident.
- A simulated 3,072 MiB external CUDA workload reduced free memory to
  6,037 MiB. MiniCPM alone was refused with a clear insufficient-VRAM message;
  LFM3 alone loaded and completed the scan.
- When live telemetry is unavailable, Clipper uses sequential inference and
  conservative checks rather than assuming free memory. A failed llama.cpp
  startup that hits CUDA out-of-memory is stopped, its memory is allowed to
  recover, and one retry is attempted before reporting the error.
- Low-power mode still forces one model at a time and also lowers threads,
  proxy resolution, and process priority.
- Repeated load, swap, and stop cycles returned to the pre-test VRAM baseline
  without orphaned servers.

## Documentation and media

- Rewrote the installer README with install, first-run AI setup, bundled versus
  on-demand components, paths, disk, GPU, driver, troubleshooting, update, and
  uninstall details.
- Synchronized the main README, website, AI model documentation, CLI portable
  README, third-party notices, and publishing checklist.
- Replaced stale screenshots with captures from the current GUI.
- Added a current workflow demonstration covering footage selection, detection,
  highlight preview, and export: `docs/media/demo.mp4`,
  `docs/media/demo.gif`, and `docs/media/desktop.png`.

## Verification

- Full test suite passes.
- Installer README is extracted and hash-checked after each build.
- Clean per-user install, upgrade, and uninstall paths were exercised.
- The installer remains unpublished until release authorization.
- Detailed VRAM and real-clip results are in
  [`VALIDATION_0.8.4.md`](VALIDATION_0.8.4.md).
