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

`story._serial_plan()` now checks the selected GPU's live free memory, not total
capacity alone. It uses measured incremental allocations of 3,000 MiB for LFM3,
6,600 MiB for MiniCPM, and 8,100 MiB for Gemma, plus a 1,024 MiB reserve. The
decision is rechecked immediately before every `llama-server` launch and between
the vision, ears, and final-edit stages.

A real 35-second Standard scan on the 10 GB card with a clean desktop:

| Mode | Peak used | Peak delta | Max `llama-server` | Both resident |
| --- | ---: | ---: | ---: | --- |
| Normal, live guard | 7,396 MiB | 6,484 MiB | 1 | 0 samples |
| Low-power, forced swap | 7,376 MiB | 6,477 MiB | 1 | 0 samples |
| LFM3 vision and ears | 3,837 MiB | 2,937 MiB | 1 | 0 samples |

The normal scan reported:

```text
VRAM guard: 9140 MiB free; both models need about 9600 MiB plus 1024 MiB reserve. Using sequential inference.
```

The automatic guard scan returned one clip at 14.28-35.02 seconds with score 80
and reason `AI goal (HUD): VELY SCORED`. Low-power returned the same goal at
13.28-35.02 seconds. No CUDA OOM occurred.

### External workload and dynamic recheck

A separate process allocated 3,072 MiB with `cudaMalloc` to simulate a game or
other GPU workload. With a clean desktop baseline at 919 MiB used and 9,133 MiB
free, the allocation raised usage to 4,015 MiB and left 6,037 MiB free.
MiniCPM alone needed 6,600 MiB plus reserve and was refused before any process
started. LFM3 alone loaded and completed the same scan, peaking at 6,960 MiB
total with one model resident.

A second test allocated 2,048 MiB after MiniCPM was already resident, which
simulates memory being consumed between the vision and audio stages:

| Stage | Used | Free | Result |
| --- | ---: | ---: | --- |
| Clean baseline | 916 MiB | 9,136 MiB | Normal desktop |
| MiniCPM loaded | 7,393 MiB | 2,659 MiB | Vision model resident |
| +2,048 MiB external | 9,438 MiB | 614 MiB | Simulated external workload |
| LFM3 start attempt | 9,666 MiB | 574 MiB | Refused with a clear insufficient-VRAM error; no `llama-server` started |
| After stopping MiniCPM and freeing external allocation | 958 MiB | 9,094 MiB | Memory recovered |

### Telemetry unavailable and CUDA OOM

- An invalid `CUDA_VISIBLE_DEVICES` value made telemetry return `None`. The plan
  selected sequential inference with reason `telemetry_unavailable`; no model
  was treated as safely fitting.
- Mocked `nvidia-smi` tests cover missing executables, command failures,
  incomplete rows, `[N/A]` fields, multiple GPUs, and UUID selection.
- Mocked llama.cpp OOM tests verify one retry, failed-process termination,
  memory-recovery polling, and a final `VramError` without leaving a server in
  `_SERVERS`.

Repeated load, swap, and stop cycles returned to the pre-test VRAM baseline.
No orphaned `llama-server` process was left after a successful stop or failed
start.

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

The default 10 GB Standard plus LFM3 ears configuration is safe because
Clipper checks live free VRAM immediately before each model start and serializes
when the selected pair cannot fit with a 1 GiB reserve. It is not described as a
simultaneous dual-model configuration on 10 GB cards. Games and other GPU
workloads reduce the measured free memory and change the decision.

No live game was running during these tests. The external workload was a
3,072 MiB CUDA allocation from a separate process, which is representative of
memory pressure but not a substitute for every game engine. Multi-GPU selection
was verified with mocked telemetry; only one physical GPU was available. Actual
CUDA OOM startup recovery was verified with mocked failures, not by forcing a
live driver OOM.

The docs and UI state that low or busy GPU memory loads one model at a time, and
Low-power mode additionally lowers threads and proxy resolution. When telemetry
is unavailable, Clipper uses the conservative sequential path rather than
assuming the memory is free.
