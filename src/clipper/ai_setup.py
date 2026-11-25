"""One-click setup for the optional local AI prerequisite.

Clipper never bundles the multi-gigabyte Ollama runtime or a vision model in
the base installer. When the user asks for AI Director, this module downloads
the official Ollama installer from GitHub, verifies its published SHA-256 and
Authenticode signature, installs it per-user, and starts the local server. The
model itself is still downloaded by the user from inside the app.

The code is deliberately small and auditable: HTTPS only, a fixed asset name,
a size cap, published hashes when available, and no shell string construction
for the installer path.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import __version__
from .detect.ai import ollama_status

OLLAMA_REPO = "ollama/ollama"
OLLAMA_API_LATEST = f"https://api.github.com/repos/{OLLAMA_REPO}/releases/latest"
OLLAMA_DIRECT_URL = (
    "https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe"
)
OLLAMA_ASSET_NAME = "OllamaSetup.exe"
OLLAMA_MAX_BYTES = 3 * 1024 * 1024 * 1024
USER_AGENT = f"Clipper/{__version__} (+https://github.com/hatermedia/clipper)"
DOWNLOAD_CHUNK = 1024 * 1024
CREATE_NO_WINDOW = 0x08000000

ProgressFn = Callable[[int, int], None]
StatusFn = Callable[[str], None]
CancelFn = Callable[[], bool]

_SERVER_PROCESS: subprocess.Popen[bytes] | None = None


class AISetupError(RuntimeError):
    """The optional Ollama prerequisite could not be prepared."""


class AISetupCancelled(AISetupError):
    """The user cancelled the prerequisite download."""


@dataclass(frozen=True)
class OllamaRelease:
    version: str
    url: str
    size: int
    sha256: str | None

    @property
    def filename(self) -> str:
        return OLLAMA_ASSET_NAME


def ai_cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / "Clipper" / "ai"
    return Path.home() / ".cache" / "clipper" / "ai"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(DOWNLOAD_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_download_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }:
        raise AISetupError("Ollama download URL is not an official GitHub asset.")
    return url


def fetch_latest_release(timeout: float = 30.0) -> OllamaRelease:
    """Return the latest official OllamaSetup.exe release metadata."""

    request = urllib.request.Request(
        OLLAMA_API_LATEST,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
        assets = payload.get("assets") or []
        asset = next(
            (item for item in assets if item.get("name") == OLLAMA_ASSET_NAME),
            None,
        )
        if not isinstance(asset, dict):
            raise AISetupError("The Ollama release does not contain OllamaSetup.exe.")
        url = _validate_download_url(str(asset.get("browser_download_url") or ""))
        size = int(asset.get("size") or 0)
        if size <= 0 or size > OLLAMA_MAX_BYTES:
            raise AISetupError("The Ollama installer has an unexpected size.")
        digest = str(asset.get("digest") or "").strip().lower()
        sha256 = None
        if digest.startswith("sha256:"):
            candidate = digest.split(":", 1)[1]
            if len(candidate) == 64:
                sha256 = candidate
        version = str(payload.get("tag_name") or "latest").lstrip("v") or "latest"
        return OllamaRelease(version=version, url=url, size=size, sha256=sha256)
    except AISetupError:
        raise
    except urllib.error.HTTPError as exc:
        raise AISetupError(f"Ollama release lookup returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise AISetupError("Could not reach GitHub to look up Ollama.") from exc
    except (OSError, ValueError, TypeError) as exc:
        raise AISetupError("Could not read the Ollama release information.") from exc


def resolve_release() -> OllamaRelease:
    """Use release metadata when possible, otherwise the official latest URL.

    GitHub's anonymous API can be rate-limited. The direct URL still resolves
    to the official signed installer, which download_installer verifies with
    Authenticode when no published digest is available.
    """

    try:
        return fetch_latest_release()
    except AISetupError:
        return OllamaRelease(
            version="latest",
            url=OLLAMA_DIRECT_URL,
            size=0,
            sha256=None,
        )


def verify_authenticode(path: Path, timeout: float = 60.0) -> tuple[bool, str]:
    """Verify the Windows Authenticode signer without third-party packages."""

    if os.name != "nt":
        return False, "Authenticode verification is only available on Windows."
    powershell = (
        Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if not powershell.is_file():
        return False, "Windows PowerShell is not available."
    escaped = str(path).replace("'", "''")
    script = (
        f"$sig = Get-AuthenticodeSignature -LiteralPath '{escaped}'; "
        "[pscustomobject]@{"
        "Status = $sig.Status.ToString(); "
        "Subject = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { '' }"
        "} | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            [
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        if completed.returncode != 0:
            return False, "Windows could not check the installer signature."
        payload = json.loads(completed.stdout.strip() or "{}")
        status = str(payload.get("Status") or "")
        subject = str(payload.get("Subject") or "")
        if status != "Valid":
            return False, f"Installer signature is {status or 'not valid'}."
        if "Ollama" not in subject:
            return False, "Installer is signed by an unexpected publisher."
        return True, subject
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return False, f"Installer signature check failed: {exc}"


def _download_url(
    release: OllamaRelease,
    target: Path,
    progress: ProgressFn | None,
    cancelled: CancelFn | None,
) -> Path:
    partial = target.with_suffix(target.suffix + ".part")
    start = partial.stat().st_size if partial.exists() else 0
    if release.size and start > release.size:
        partial.unlink(missing_ok=True)
        start = 0
    headers = {"User-Agent": USER_AGENT}
    if start:
        headers["Range"] = f"bytes={start}-"
    request = urllib.request.Request(release.url, headers=headers)
    if progress:
        progress(start, release.size or start)
    try:
        with urllib.request.urlopen(request, timeout=60.0) as response:
            status = int(getattr(response, "status", 200) or 200)
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if "text/html" in content_type or "text/plain" in content_type:
                raise AISetupError(
                    "The Ollama download returned a web page instead of an installer."
                )
            if start and status != 206:
                partial.unlink(missing_ok=True)
                start = 0
            try:
                length = int(response.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                length = 0
            total = (start + length) if length else (release.size or 0)
            if total and total > OLLAMA_MAX_BYTES:
                raise AISetupError("The Ollama installer is larger than expected.")
            if release.size and total and total != release.size:
                raise AISetupError("The Ollama installer size did not match GitHub's metadata.")
            mode = "ab" if start else "wb"
            downloaded = start
            with partial.open(mode) as handle:
                while True:
                    if cancelled and cancelled():
                        raise AISetupCancelled(
                            "Ollama download cancelled. Retry to resume it."
                        )
                    chunk = response.read(DOWNLOAD_CHUNK)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > OLLAMA_MAX_BYTES:
                        raise AISetupError("The Ollama installer exceeded the size limit.")
                    handle.write(chunk)
                    if progress:
                        progress(downloaded, total or downloaded)
    except AISetupCancelled:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and start:
            partial.unlink(missing_ok=True)
            return _download_url(release, target, progress, cancelled)
        raise AISetupError(f"Ollama download returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise AISetupError("Could not download the Ollama installer.") from exc
    except OSError as exc:
        raise AISetupError(f"Could not save the Ollama installer: {exc}") from exc

    if release.size and partial.stat().st_size != release.size:
        raise AISetupError("The Ollama installer did not finish downloading.")
    if release.sha256:
        actual = _sha256_file(partial)
        if actual != release.sha256:
            partial.unlink(missing_ok=True)
            raise AISetupError(
                "The Ollama installer checksum did not match GitHub's metadata."
            )
    if os.name == "nt":
        valid, detail = verify_authenticode(partial)
        if not valid:
            partial.unlink(missing_ok=True)
            raise AISetupError(detail)
    if target.exists():
        target.unlink()
    partial.replace(target)
    return target


def download_installer(
    release: OllamaRelease,
    destination: Path | None = None,
    progress: ProgressFn | None = None,
    cancelled: CancelFn | None = None,
) -> Path:
    """Download and verify the official Ollama installer."""

    folder = destination or ai_cache_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / release.filename
    if target.exists() and release.size and target.stat().st_size == release.size:
        trusted = not release.sha256 or _sha256_file(target) == release.sha256
        if trusted and os.name == "nt":
            trusted, _detail = verify_authenticode(target)
        if trusted:
            return target
        target.unlink(missing_ok=True)
    try:
        free = shutil.disk_usage(folder).free
    except OSError:
        free = 0
    # The download is about 1.9 GB, and the installed runtime is another
    # ~2.9 GB. Leave room for both plus some working space.
    needed = release.size + 3 * 1024 * 1024 * 1024 if release.size else 0
    if free and needed and free < needed:
        raise AISetupError(
            "Not enough free disk space for Ollama. Free about "
            f"{needed / (1024 ** 3):.1f} GB and try again."
        )
    return _download_url(release, target, progress, cancelled)


def ollama_executable() -> Path | None:
    """Find an installed Ollama executable, including a just-finished install."""

    found = shutil.which("ollama")
    if found:
        candidate = Path(found)
        if candidate.is_file():
            return candidate
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidate = Path(local) / "Programs" / "Ollama" / "ollama.exe"
        if candidate.is_file():
            return candidate
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                user_path = str(winreg.QueryValueEx(key, "Path")[0])
            for entry in user_path.split(";"):
                entry = os.path.expandvars(entry.strip())
                if not entry:
                    continue
                candidate = Path(entry) / "ollama.exe"
                if candidate.is_file():
                    return candidate
        except (ImportError, OSError):
            pass
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidate = Path(program_files) / "Ollama" / "ollama.exe"
        if candidate.is_file():
            return candidate
    return None


def install_ollama(installer: Path, timeout: float = 900.0) -> Path:
    """Run the official installer silently, then return the executable."""

    if os.name != "nt":
        raise AISetupError("The Ollama prerequisite installer is Windows-only.")
    if not installer.is_file() or installer.name.lower() != OLLAMA_ASSET_NAME.lower():
        raise AISetupError("The Ollama installer file is missing or misnamed.")
    try:
        completed = subprocess.run(
            [
                str(installer),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/SP-",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise AISetupError("The Ollama installer timed out.") from exc
    except OSError as exc:
        raise AISetupError(f"Could not start the Ollama installer: {exc}") from exc
    if completed.returncode not in (0, 3010):
        raise AISetupError(
            f"The Ollama installer exited with code {completed.returncode}."
        )
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        executable = ollama_executable()
        if executable is not None:
            return executable
        time.sleep(0.5)
    raise AISetupError("Ollama installed, but its executable was not found.")


def start_ollama_server(wait: float = 20.0) -> bool:
    """Start the local Ollama server if it is not already answering."""

    global _SERVER_PROCESS
    if bool(ollama_status(timeout=1.0).get("ok")):
        return True
    executable = ollama_executable()
    if executable is None:
        return False
    if _SERVER_PROCESS is None or _SERVER_PROCESS.poll() is not None:
        try:
            _SERVER_PROCESS = subprocess.Popen(
                [str(executable), "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except OSError:
            return False
    deadline = time.monotonic() + max(1.0, wait)
    while time.monotonic() < deadline:
        if bool(ollama_status(timeout=1.0).get("ok")):
            return True
        process = _SERVER_PROCESS
        if process is not None and process.poll() is not None:
            _SERVER_PROCESS = None
            return False
        time.sleep(0.5)
    return False


def install_prerequisite(
    progress: ProgressFn | None = None,
    status: StatusFn | None = None,
    cancelled: CancelFn | None = None,
) -> Path:
    """Download, verify, install, and start Ollama. Returns its executable."""

    notify = status or (lambda _message: None)
    release = resolve_release()
    notify(
        "Downloading the official Ollama installer"
        + (f" {release.version}" if release.version != "latest" else "")
        + "..."
    )
    installer = download_installer(release, progress=progress, cancelled=cancelled)
    if cancelled and cancelled():
        raise AISetupCancelled("Ollama setup cancelled. Retry to resume the download.")
    notify("Verifying and installing Ollama...")
    executable = install_ollama(installer)
    if cancelled and cancelled():
        raise AISetupCancelled("Ollama was installed. Reopen Clipper to finish setup.")
    notify("Starting Ollama...")
    running = start_ollama_server(wait=20.0)
    try:
        installer.unlink(missing_ok=True)
        folder = installer.parent
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    except OSError:
        pass
    if running:
        notify("Ollama is ready. Download a model to enable AI Director.")
    else:
        notify(
            "Ollama installed, but its server is not running yet. "
            "Click Refresh in the AI panel to start it."
        )
    return executable
