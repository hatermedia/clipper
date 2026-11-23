"""GitHub-release updater for the native Clipper app.

The desktop build is installed per-user by an NSIS installer. Auto-update is
deliberately small and auditable: ask GitHub for the latest release, download
the installer over HTTPS, verify its SHA-256 against the release checksums,
then hand the installer to a detached helper that waits for Clipper to exit,
installs silently, and relaunches the app.

No third-party update framework, no background service, no admin rights.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import __version__

GITHUB_REPO = "hatermedia/clipper"
API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases"
CHECK_INTERVAL_SECONDS = 6 * 60 * 60
USER_AGENT = f"Clipper/{__version__} (+https://github.com/{GITHUB_REPO})"

DownloadProgress = Callable[[int, int], None]


class UpdateError(RuntimeError):
    """An update could not be checked, downloaded, or verified."""


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    name: str
    notes: str
    page_url: str
    published_at: str
    installer_name: str | None = None
    installer_url: str | None = None
    installer_size: int = 0
    checksums_name: str | None = None
    checksums_url: str | None = None

    @property
    def has_installer(self) -> bool:
        return bool(self.installer_url and self.installer_name)

    @property
    def has_checksums(self) -> bool:
        return bool(self.checksums_url and self.checksums_name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "tag": self.tag,
            "name": self.name,
            "notes": self.notes,
            "page_url": self.page_url,
            "published_at": self.published_at,
            "installer_name": self.installer_name,
            "installer_url": self.installer_url,
            "installer_size": self.installer_size,
            "checksums_name": self.checksums_name,
            "checksums_url": self.checksums_url,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ReleaseInfo":
        return cls(
            version=str(value.get("version", "0")),
            tag=str(value.get("tag", "")),
            name=str(value.get("name", "")),
            notes=str(value.get("notes", "")),
            page_url=str(value.get("page_url", RELEASES_PAGE)),
            published_at=str(value.get("published_at", "")),
            installer_name=value.get("installer_name"),
            installer_url=value.get("installer_url"),
            installer_size=int(value.get("installer_size", 0) or 0),
            checksums_name=value.get("checksums_name"),
            checksums_url=value.get("checksums_url"),
        )


def parse_version(value: str) -> tuple[int, ...]:
    cleaned = value.strip().lstrip("vV")
    match = re.match(r"(\d+(?:\.\d+)*)", cleaned)
    if not match:
        raise UpdateError(f"Unrecognised version: {value!r}")
    return tuple(int(part) for part in match.group(1).split("."))


def version_is_newer(candidate: str, current: str = __version__) -> bool:
    left = parse_version(candidate)
    right = parse_version(current)
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) > right + (0,) * (width - len(right))


def _request(url: str, timeout: float = 10.0) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json, application/octet-stream",
        },
    )


def _fetch_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(_request(url, timeout), timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("No published Clipper release was found.") from exc
        if exc.code == 403:
            raise UpdateError(
                "GitHub rate-limited the update check. Try again later."
            ) from exc
        raise UpdateError(f"GitHub returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"Could not reach GitHub: {exc.reason}") from exc
    except TimeoutError as exc:
        raise UpdateError("The update check timed out.") from exc
    if not isinstance(payload, dict):
        raise UpdateError("GitHub returned an unexpected response.")
    return payload


def _release_from_payload(payload: dict[str, Any]) -> ReleaseInfo:
    tag = str(payload.get("tag_name") or payload.get("name") or "")
    if not tag:
        raise UpdateError("The latest release has no version tag.")
    assets = [item for item in payload.get("assets", []) if isinstance(item, dict)]
    installer = next(
        (
            item
            for item in assets
            if str(item.get("name", "")).lower().startswith("clippersetup")
            and str(item.get("name", "")).lower().endswith(".exe")
        ),
        None,
    )
    checksums = next(
        (
            item
            for item in assets
            if "sha256" in str(item.get("name", "")).lower()
            or "checksum" in str(item.get("name", "")).lower()
        ),
        None,
    )
    return ReleaseInfo(
        version=tag.lstrip("vV"),
        tag=tag,
        name=str(payload.get("name") or tag),
        notes=str(payload.get("body") or "")[:8000],
        page_url=str(payload.get("html_url") or RELEASES_PAGE),
        published_at=str(payload.get("published_at") or ""),
        installer_name=str(installer.get("name")) if installer else None,
        installer_url=str(installer.get("browser_download_url")) if installer else None,
        installer_size=int((installer or {}).get("size", 0) or 0),
        checksums_name=str(checksums.get("name")) if checksums else None,
        checksums_url=str(checksums.get("browser_download_url")) if checksums else None,
    )


def fetch_latest(timeout: float = 10.0) -> ReleaseInfo:
    return _release_from_payload(_fetch_json(API_LATEST, timeout=timeout))


def check_for_update(
    current: str = __version__, timeout: float = 10.0
) -> ReleaseInfo | None:
    """Return the latest release only when it is newer than *current*."""

    latest = fetch_latest(timeout=timeout)
    return latest if version_is_newer(latest.version, current) else None


def _state_file() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "Clipper" / "update-state.json"


def load_state() -> dict[str, Any]:
    path = _state_file()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def save_state(state: dict[str, Any]) -> None:
    path = _state_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass


def check_with_cache(
    current: str = __version__,
    max_age: float = CHECK_INTERVAL_SECONDS,
    force: bool = False,
    timeout: float = 10.0,
) -> tuple[ReleaseInfo | None, bool]:
    """Check GitHub, using a cached result for *max_age* seconds.

    Returns ``(release_or_none, from_cache)``. A cached release is re-filtered
    against *current* so a local upgrade still turns the banner off.
    """

    state = load_state()
    now = time.time()
    checked_at = float(state.get("checked_at", 0) or 0)
    cached = state.get("release")
    if not force and cached and now - checked_at < max_age:
        try:
            release = ReleaseInfo.from_dict(cached)
        except (TypeError, ValueError):
            return check_with_cache(current, max_age, force=True, timeout=timeout)
        return (release if version_is_newer(release.version, current) else None), True

    latest = fetch_latest(timeout=timeout)
    save_state(
        {
            "checked_at": now,
            "current": current,
            "release": latest.to_dict(),
        }
    )
    return (latest if version_is_newer(latest.version, current) else None), False


def parse_checksums(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+)$", line)
        if match:
            result[match.group(2).strip().lower()] = match.group(1).lower()
    return result


def _fetch_text(url: str, timeout: float = 30.0) -> str:
    try:
        with urllib.request.urlopen(_request(url, timeout), timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise UpdateError(f"Could not download update metadata: {exc.reason}") from exc


def download_installer(
    release: ReleaseInfo,
    destination: Path | str | None = None,
    progress: DownloadProgress | None = None,
    timeout: float = 60.0,
) -> Path:
    """Download and SHA-256 verify the release installer."""

    if not release.has_installer:
        raise UpdateError(
            "This release has no Windows installer. Download it from "
            f"{release.page_url}"
        )
    if not release.has_checksums:
        raise UpdateError(
            "The release publishes no SHA-256 checksums, so Clipper will not "
            "auto-install it. Download manually from " + release.page_url
        )

    name = release.installer_name or f"ClipperSetup-{release.version}.exe"
    if destination is None:
        destination = Path(tempfile.gettempdir()) / "Clipper" / name
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")

    checksums_text = _fetch_text(release.checksums_url or "", timeout=timeout)
    expected = parse_checksums(checksums_text).get(name.lower())
    if not expected:
        raise UpdateError(
            f"The release checksums do not list {name}; refusing to install it."
        )

    digest = hashlib.sha256()
    downloaded = 0
    total = release.installer_size
    try:
        with urllib.request.urlopen(
            _request(release.installer_url or "", timeout), timeout=timeout
        ) as response:
            total = int(response.headers.get("Content-Length") or total or 0)
            with partial.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    if progress:
                        progress(downloaded, total)
    except urllib.error.URLError as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"Download failed: {exc.reason}") from exc
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"Could not save the installer: {exc}") from exc

    actual = digest.hexdigest()
    if actual != expected:
        partial.unlink(missing_ok=True)
        raise UpdateError(
            "The downloaded installer failed SHA-256 verification "
            f"(expected {expected[:12]}..., got {actual[:12]}...)."
        )
    partial.replace(target)
    return target


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def installed_exe() -> Path:
    """Best guess at the installed Clipper.exe path."""

    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Clipper") as key:
                folder = str(winreg.QueryValueEx(key, "InstallDir")[0])
                candidate = Path(folder) / "Clipper.exe"
                if candidate.is_file():
                    return candidate
        except OSError:
            pass
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidate = Path(local) / "Programs" / "Clipper" / "Clipper.exe"
        if candidate.is_file():
            return candidate
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return Path(sys.executable)


def is_installed_build() -> bool:
    """True when running the frozen app from the per-user install folder."""

    if not getattr(sys, "frozen", False) or os.name != "nt":
        return False
    exe = Path(sys.executable).resolve()
    return exe.name.lower() == "clipper.exe" and "programs" in str(exe).lower()


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _update_log(message: str) -> None:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    path = Path(base) / "Clipper" / "update.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def launch_installer(
    installer: Path | str,
    *,
    relaunch: bool = True,
    wait_pid: int | None = None,
) -> Path:
    """Install silently after this process exits, then optionally relaunch.

    Returns the helper script path (useful for diagnostics and tests).
    """

    if os.name != "nt":
        raise UpdateError("Silent install is only supported on Windows.")
    installer_path = Path(installer).resolve()
    if not installer_path.is_file():
        raise UpdateError(f"Installer not found: {installer_path}")
    exe = installed_exe()
    # A source/pip CLI has no app to relaunch; the installer adds a Start Menu
    # shortcut instead of opening python.exe with no arguments.
    if relaunch and not getattr(sys, "frozen", False):
        relaunch = False
    log_path = (Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
                / "Clipper" / "update.log")
    _update_log(f"install requested: {installer_path} relaunch={relaunch} wait_pid={wait_pid}")

    lines = [
        "$ErrorActionPreference = 'SilentlyContinue'",
        f"$log = {_ps_quote(str(log_path))}",
        f"Add-Content -LiteralPath $log -Value \"$(Get-Date -Format o) helper start\"",
        f"$targetPid = {int(wait_pid or 0)}",
        "$deadline = (Get-Date).AddSeconds(90)",
        "while ($targetPid -gt 0 -and (Get-Process -Id $targetPid -ErrorAction SilentlyContinue) "
        "-and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }",
        "$deadline = (Get-Date).AddSeconds(90)",
        "while ((Get-Process -Name 'Clipper' -ErrorAction SilentlyContinue) "
        "-and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }",
        f"Add-Content -LiteralPath $log -Value \"$(Get-Date -Format o) running installer\"",
        f"Start-Process -FilePath {_ps_quote(str(installer_path))} -ArgumentList '/S' -Wait",
        "Start-Sleep -Milliseconds 1200",
        f"Add-Content -LiteralPath $log -Value \"$(Get-Date -Format o) installer finished\"",
    ]
    if relaunch:
        lines.append(
            f"if (Test-Path {_ps_quote(str(exe))}) "
            f"{{ Start-Process -FilePath {_ps_quote(str(exe))} }}"
        )
    lines.append("Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force")

    helper = Path(tempfile.gettempdir()) / "Clipper" / f"install-{os.getpid()}.ps1"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")

    powershell = shutil.which("powershell.exe") or str(
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    command = [
        powershell,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-WindowStyle",
        "Hidden",
        "-File",
        str(helper),
    ]
    # ShellExecute hands the helper to Explorer, outside this process's job
    # object. A plain Popen child can be killed when the app exits, and an
    # installer cannot replace a running Clipper.exe.
    if os.name == "nt":
        try:
            import ctypes

            parameters = subprocess.list2cmdline(command[1:])
            result = ctypes.windll.shell32.ShellExecuteW(
                None,
                "open",
                command[0],
                parameters,
                None,
                0,  # SW_HIDE
            )
            _update_log(f"ShellExecute result={result} powershell={powershell}")
            if result > 32:
                return helper
        except Exception as exc:
            _update_log(f"ShellExecute failed: {exc}")

    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    try:
        process = subprocess.Popen(
            command,
            creationflags=creationflags,
            close_fds=True,
        )
        _update_log(f"Popen helper pid={process.pid}")
    except OSError as exc:
        _update_log(f"Popen helper failed: {exc}")
        raise UpdateError(f"Could not start the installer helper: {exc}") from exc
    return helper


def open_release_page(release: ReleaseInfo | None = None) -> None:
    url = release.page_url if release else RELEASES_PAGE
    try:
        os.startfile(url)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        import webbrowser

        webbrowser.open(url)
