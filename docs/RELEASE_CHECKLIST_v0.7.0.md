# Clipper v0.7.0 release checklist

Artifacts produced by `packaging/build_installer.ps1`:

- `ClipperSetup-0.7.0.exe` - 382,280,514 bytes
  SHA-256 `80c37eb5fd6d89de01e2bd5c46329f9a15806dedaec6400ecff118f45a58056d`
- `clipper-0.7.0-windows-x64-native.zip` - 493,565,573 bytes
  SHA-256 `0f9e8a7964beafd78b75ef0b14a784690cffb8d118b75ca795b98b2be046afa2`
- `SHA256SUMS.txt` lists both artifacts and the three staged source archives.

## Local verification already completed

- `pytest -q` passes, including updater adversarial cases, PowerShell helper
  syntax, FFmpeg child cleanup, OCR/YAMNet cooldowns, Lite HUD retention,
  malformed Ollama responses, packaging contracts, and desktop DPI/shutdown
  contracts.
- `python -m compileall` passes for `src`, `tests`, and packaging scripts.
- Frozen desktop `Clipper.exe --self-test report.json` returns 0 and reports
  `whisper`, `rapidocr`, and `yamnet` as loaded from `_internal\clipper\assets`.
- A clean-environment simulation with the external FFmpeg folder and the local
  `%LOCALAPPDATA%\Clipper` model/cache folder temporarily removed passed:
  install, self-test, demo scan, and uninstall all succeeded from bundled data.
- Silent install to a temp directory, `--self-test` from that install, silent
  uninstall, and registry/shortcut cleanup all succeed.
- Re-installing over a running install closes the old app before replacing it.
- Installing and uninstalling into a directory containing `keep.txt` preserves
  that file; the directory is not wiped.
- Uninstalling after a recent app run removes `_internal` and the install
  directory (short delay after process exit).

## Clean Windows VM checks (required before publishing)

Use a fresh Windows 10/11 x64 VM with no Python, FFmpeg, Ollama, or prior
Clipper install. Take a checkpoint before each scenario.

1. Verify the installer hash against `SHA256SUMS.txt`.
2. Run `ClipperSetup-0.7.0.exe` as a standard user. Confirm there is no UAC
   admin prompt and the default path is
   `%LOCALAPPDATA%\Programs\Clipper`.
3. Launch from the Start Menu and Desktop shortcut. Confirm the window opens,
   the title bar buttons work, and the app is not clipped on a 150% or 200%
   display scale and after moving between two monitors with different DPI.
4. Scan and export a real clip. Confirm preview playback, selected export, and
   frame-accurate re-encode.
5. Disconnect the network. Run the frozen self-test from the install directory:
   `Clipper.exe --self-test "%TEMP%\clipper-self-test.json"`. Confirm exit code
   0 and `whisper`, `rapidocr`, and `yamnet` are true.
6. Run a Lite-mode analysis offline. Confirm HUD OCR, Whisper transcript, and
   YAMNet tags appear without downloading models.
7. Start an analysis, close the window while FFmpeg is running, and confirm no
   `ffmpeg.exe`/`ffprobe.exe` child remains in Task Manager.
8. Install over an existing 0.6.0 install while the app is running. Confirm the
   app closes, the installer finishes silently, and the app reopens at 0.7.0.
9. Uninstall. Confirm the install folder, shortcuts, `HKCU\Software\Clipper`,
   `HKCU\Software\hatermedia\Clipper`, and the uninstall entry are removed.
   Confirm footage, `%LOCALAPPDATA%\Clipper\ai-cache`, and
   `%LOCALAPPDATA%\Clipper\models` are preserved.
10. Check Windows Settings > Apps shows the correct version and that a repair
    or second uninstall does not remove unrelated files.
11. Verify `THIRD_PARTY_NOTICES.txt`, `FFMPEG_NOTICE.txt`,
    `COPYING.GPLv3.txt`, and `licenses\` (Apache-2.0, BSD-3-Clause,
    CC-BY-SA-4.0, LGPL-3.0, MIT, MPL-2.0) are present in the install folder.

## Release blockers

- **FFmpeg source offer:** the bundled FFmpeg is the gyan.dev 9.1 GPLv3 build
  (source commit `74e4393595`). The exact FFmpeg, x264, and x265 source archives
  are attached to the v0.7.0 GitHub release and can be reproduced with
  `packaging\fetch_ffmpeg_source.ps1`. Review the remaining statically linked
  library sources in `packaging\FFMPEG_SOURCE_MANIFEST.txt`.
- **Clean VM:** a true clean VM run is still recommended for DPI, multi-monitor,
  and update-from-0.6.0 coverage. The elevated fresh-profile test and local
  clean-environment simulation both passed install, self-test, offline scan, and
  uninstall.
- **Signing:** the executable is unsigned. SmartScreen warnings are expected.
