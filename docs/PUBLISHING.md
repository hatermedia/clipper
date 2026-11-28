# Publishing Clipper

Clipper ships two ways from the same version:

- Windows installer and portable zip from GitHub Releases
- Python wheel/sdist on PyPI as `clipper-gg`

## Before publishing

1. Bump the version in `pyproject.toml` and `src/clipper/__init__.py`.
2. Run `pytest -q` and the frozen self-test.
3. Run `packaging\build_installer.ps1`. It creates the installer, portable
   zip, `SHA256SUMS.txt`, and verifies the release payload.
4. Verify the installer README is the current one. The build substitutes
   `__CLIPPER_VERSION__` in `packaging\PORTABLE_DESKTOP_README.txt` and copies
   it to `desktop-dist\Clipper\README.txt`. `build_installer.ps1` rejects a
   README with the wrong version or an unresolved placeholder.
5. Extract `README.txt` from the generated installer and compare it with the
   staged payload. For example:
   `7z e packaging\release\ClipperSetup-X.Y.Z.exe README.txt -o<temp-dir>`.
6. Confirm the installer was built from the current source commit. `BUILD_INFO.txt`
   must record the full commit, and `Clipper.exe` must report the expected file
   and product versions. `build_installer.ps1` refuses a dirty tree and verifies
   both automatically.
7. Confirm neither package contains stale editable metadata. The build removes
   `clipper_gg-*.dist-info` and editable `direct_url.json` files, writes a clean
   versioned package record, and fails if any personal Windows user path is
   present in any payload file. Packaging tests cover these checks.
8. Test the installer on a clean per-user profile or a fresh Windows VM:
   install, launch, first-run AI setup, runtime download, model initialization,
   and one analysis. Verify Ollama is not installed or required.
9. Build wheel/sdist with `python -m build`.
10. Verify notices and license files are present in the payload.
11. Verify every website, README, and release-note media reference points to
    the current workflow demo and current GUI screenshots. Remove retired
    screenshots and recordings instead of leaving stale promotional assets.
12. On NVIDIA hardware, verify live free-VRAM detection with no external
    workload, with a simulated external CUDA allocation, and with telemetry
    unavailable. Confirm that a full model does not start when free memory is
    below the measured allocation plus the 1 GiB reserve.

Do not publish a build whose installer README does not match the staged README
or whose frozen app does not contain the current source.

## Release signing (updater trust)

The in-app updater checks the installer's SHA-256 against the release's
`SHA256SUMS-X.Y.Z.txt`. On its own that only detects corruption: anyone who can
publish a GitHub release could also publish matching checksums. A detached
Ed25519 signature made with a key that never touches GitHub closes that gap.

One-time setup:

1. `python packaging\sign_release.py keygen --out <offline path>\clipper-release.key`
   (refuses to write inside the repository). Back the key up offline.
2. Paste the printed public key into `UPDATE_PUBLIC_KEYS` in
   `src\clipper\update.py` and ship that build. From then on, installed apps
   refuse any update whose checksums are unsigned or signed by another key.

Every release:

1. `packaging\build_installer.ps1 -SigningKey <offline path>\clipper-release.key`
   writes `SHA256SUMS-X.Y.Z.txt.sig`.
2. `python packaging\sign_release.py verify packaging\release\SHA256SUMS-X.Y.Z.txt`
3. Upload the `.sig` next to the checksums (see below).

If you also get an Authenticode certificate, sign `ClipperSetup-X.Y.Z.exe`
and set `UPDATE_PUBLISHER` in `update.py` to the certificate subject so the
updater requires that publisher. Any Authenticode signature that Windows
reports as `HashMismatch` or `NotTrusted` is always refused.

Pending updates are never installed silently on launch; the user clicks
**Restart and install**.

## GitHub release

```powershell
git add -A
git commit -m "vX.Y.Z: ..."
git tag -a vX.Y.Z -m "Clipper vX.Y.Z"
git push origin main
git push origin vX.Y.Z
gh release create vX.Y.Z --title "vX.Y.Z" --notes-file docs\RELEASE_NOTES_vX.Y.Z.md `
  packaging\release\ClipperSetup-X.Y.Z.exe `
  packaging\release\clipper-X.Y.Z-windows-x64-native.zip `
  packaging\release\SHA256SUMS-X.Y.Z.txt `
  packaging\release\SHA256SUMS-X.Y.Z.txt.sig `
  dist\clipper_gg-X.Y.Z-py3-none-any.whl `
  dist\clipper_gg-X.Y.Z.tar.gz `
  packaging\release\ffmpeg-source\*.tar.gz `
  packaging\FFMPEG_SOURCE_MANIFEST.txt
```

## PyPI

```powershell
python -m twine upload --repository pypi dist\clipper_gg-X.Y.Z-py3-none-any.whl dist\clipper_gg-X.Y.Z.tar.gz
```

Do not publish if the clean-profile install test, checksum manifest, or
FFmpeg source assets are missing.
