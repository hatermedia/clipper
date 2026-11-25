# Publishing Clipper

Clipper ships two ways from the same version:

- Windows installer and portable zip from GitHub Releases
- Python wheel/sdist on PyPI as `clipper-gg`

## Before publishing

1. Bump the version in `pyproject.toml` and `src/clipper/__init__.py`.
2. Run `pytest -q` and the frozen self-test.
3. Run `packaging\build_installer.ps1`. It creates the installer, portable
   zip, `SHA256SUMS.txt`, and verifies the release payload.
4. Build wheel/sdist with `python -m build`.
5. Verify notices and license files are present in the payload.

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
