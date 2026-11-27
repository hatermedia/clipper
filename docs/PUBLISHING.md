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
6. Confirm the installer was built from the current source commit. The frozen
   `llama_runtime` must include the MSVC runtime staging logic from `ed2b278`
   or later, and the app version must match the README.
7. Test the installer on a clean per-user profile or a fresh Windows VM:
   install, launch, first-run AI setup, runtime download, model initialization,
   and one analysis. Verify Ollama is not installed or required.
8. Build wheel/sdist with `python -m build`.
9. Verify notices and license files are present in the payload.

Do not publish a build whose installer README does not match the staged README
or whose frozen app does not contain the current source.

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
  packaging\release\SHA256SUMS.txt `
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
