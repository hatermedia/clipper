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

## 10 GB VRAM guard

- Clipper now serializes the vision model and LFM3 audio ears when their
  conservative VRAM targets do not fit with 1 GB of headroom.
- On the RTX 3080 10 GB test machine, direct dual residency peaked at
  9,733 MiB of 10,240 MiB. That left only about 0.5 GiB, so the default
  Standard plus LFM3 ears configuration now uses the guard.
- A real 35-second Standard scan with the guard peaked at 8,021 MiB and kept
  only one `llama-server` resident.
- Low-power mode forces the same one-at-a-time swap and also lowers threads,
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
