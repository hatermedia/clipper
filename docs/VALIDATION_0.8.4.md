# Clipper 0.8.4 validation

This document records the final verification for the 0.8.4 installer and AI
setup. It is not a product claim for every GPU, game, or capture device.

## Test environment

- Windows 11 Pro, build 26200, 64-bit
- AMD Ryzen 5 3600
- NVIDIA GeForce RTX 3080, 10,240 MiB, driver 610.88
- Clipper 0.8.4 source tree
- Bundled llama.cpp `b12776`, CUDA 12.4 runtime
- Models: LFM3-Omni-2B, MiniCPM-o 4.5, Gemma 4 12B

## 10 GB VRAM matrix

All values are from `nvidia-smi` on the 10,240 MiB card. "Delta" is the increase
over the idle desktop baseline. The monitor sampled every 250 ms.

| Case | Models resident | Peak used | Peak delta | Result |
| --- | --- | ---: | ---: | --- |
| MiniCPM alone | MiniCPM | 7,999 MiB | 6,545 MiB | Loaded and served a request |
| LFM3 alone | LFM3 | 4,460 MiB | 2,991 MiB | Loaded and returned JSON |
| MiniCPM + LFM3 | Both | 9,733 MiB | 8,264 MiB | Both loaded, about 507 MiB free, no CUDA OOM |
| LFM3 + MiniCPM | Both | 9,840 MiB | 8,452 MiB | Both loaded, about 400 MiB free, no CUDA OOM |
| Low-power vision | MiniCPM | 7,907 MiB | 6,533 MiB | One model resident |
| Low-power ears | LFM3 | 4,412 MiB | 2,991 MiB | One model resident |
| Switch cycle 1 | One at a time | 7,774 MiB | 6,523 MiB | Returned to 1,226 MiB after stop |
| Switch cycle 2 | One at a time | 7,751 MiB | 6,525 MiB | Returned to 1,226 MiB after stop |
| Switch cycle 3 | One at a time | 7,745 MiB | 6,519 MiB | Returned to 1,247 MiB after stop |

Direct dual residency technically fits on 10 GB, but only with about 0.5 GiB
free. That is not adequate headroom for the desktop, browser hardware
acceleration, or capture software. No CUDA out-of-memory error was observed in
these tests, but the margin is too small to recommend.

### Automatic VRAM guard

`story._vram_requires_serial()` now compares the vision and ears targets with
total VRAM plus 1 GB headroom. When the pair does not fit, Clipper starts only
the vision model, unloads it before the ears pass, starts LFM3 for ears, then
reloads the vision model for the final edit.

A real 35-second Standard scan on the 10 GB card:

| Mode | Peak used | Peak delta | Max `llama-server` | Both resident |
| --- | ---: | ---: | ---: | --- |
| Normal, automatic guard | 8,021 MiB | 6,763 MiB | 1 | 0 samples |
| Low-power, forced swap | 7,890 MiB | 6,492 MiB | 1 | 0 samples |
| LFM3 vision and ears | 4,393 MiB | 3,105 MiB | 1 | 0 samples |

The automatic guard scan returned one clip at 14.28-35.02 seconds with score 80
and reason `AI goal (HUD): VELY SCORED`. Low-power returned the same goal at
13.28-35.02 seconds. No CUDA OOM occurred.

Repeated load, swap, and stop cycles returned to the pre-test VRAM baseline.
No orphaned `llama-server` process was left after a successful stop.

## Real-clip validation

Model: LFM3-Omni-2B unless noted. All clips were decoded from the local NVIDIA
capture library.

| Category | Source | Outcome | Notes |
| --- | --- | --- | --- |
| Gameplay achievement without voice | Rocket League 2025.08.01 | 13-35 s, score 80 | HUD goal only; audio score 0.0 |
| Funny social conversation | Omegle-style Desktop 2025.09.05 | 49.2-78.0 s, score 90 | Birthday laughter and reaction |
| Laughter and excited reactions | Chained Together 2026.02.15 | 60.1-86.1 s, score 90 | Banter and laughter; source had H.264 decode errors, visual pass skipped |
| Ordinary gameplay, loud audio | Counter-strike 2 2026.02.18 | No clips | No story beats; one unreadable window; no false positive |
| Sarcastic and joking insults | Chained Together 2026.02.19 | 63.9-90.4 s, score 90 | Insults and laughter; clip reaches the end of the source |
| Social banter in a game menu | Arc Raiders 2026.01.17 | 57.0-87.0 s, score 85 | Hype, laughter, and a reaction while matchmaking; not an in-game event |
| Combined visual and audio evidence | Rocket League in Desktop 2025.11.29 | 14.8-45.6 s, score 90 | HUD goal plus laughter and "We gotta win!" |

## False positives and missed highlights

- No clear false positive was found in the selected clips.
- The Counter-strike 2 sample produced no clip, which is the desired result for
  ordinary gameplay with loud but uninteresting audio.
- The Chained Together 2026.02.15 source has damaged H.264 frames. The visual
  pass was skipped and the clip was found from audio evidence. Visual-only
  moments in that source may have been missed.
- The Counter-strike 2 sample also reported one unreadable analysis window.
- No Discord-specific capture was available in the local library. An
  Omegle-style social video chat was used as the social conversation sample.
- These are spot checks, not a labeled benchmark. They do not prove recall for
  every game or capture setup.

## Conclusion

The default 10 GB Standard plus LFM3 ears configuration is safe only because
Clipper now serializes the models automatically. It should not be described as
a simultaneous dual-model configuration on 10 GB cards. The docs and UI now
state that tight-VRAM systems load one model at a time, and Low-power mode
additionally lowers threads and proxy resolution.
