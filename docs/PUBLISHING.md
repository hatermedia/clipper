# Publishing Clipper to PyPI

The GitHub release works today. PyPI publication is the only blocked release
step because this machine has no PyPI API token stored.

## Status

- PyPI distribution name: **`clipper-gg`**
- Import package: `clipper`
- Console command: `clipper`
- `clipper` on PyPI is an unrelated 2014 CLIP-seq package. Do not use it.
- `clipper-gg` was unregistered when checked on 2026-11-22. Re-check before
  uploading.

## One-time setup

1. Create or sign in to a PyPI account at <https://pypi.org>.
2. Verify the email and enable 2FA.
3. Go to **Account settings → API tokens → Add API token**.
4. Scope the token to the `clipper-gg` project (or "Entire account" for the
   first upload, then replace it with a project-scoped token).
5. Do **not** paste the token into chat, a commit, or `opencode.jsonc`.

## Upload

```powershell
cd C:\Users\ADMIN\clipper
.venv\Scripts\activate

python -m build
python -m twine check dist\*

# Option A: environment variable (current shell only)
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "pypi-..."
python -m twine upload dist\clipper_gg-0.2.0-py3-none-any.whl dist\clipper_gg-0.2.0.tar.gz

# Option B: prompt (no shell history)
python -m twine upload dist\clipper_gg-0.2.0-py3-none-any.whl dist\clipper_gg-0.2.0.tar.gz
```

## Verify

```powershell
curl.exe -s https://pypi.org/pypi/clipper-gg/json
pipx install clipper-gg
clipper --version
```

## After the first publish

- Add the PyPI badge and replace "once the PyPI release is live" with the
  install command in `README.md`.
- Create a project-scoped token and revoke the broader first-upload token.
- Keep the GitHub release assets as the offline fallback.
- For later versions: bump `version` in `pyproject.toml`, rebuild, upload, tag,
  and publish a GitHub release.

## Why this is not automated

An API token is a credential, not a code change. Automating token creation
requires interactive account access and 2FA. The upload command is ready; the
token must come from you.
