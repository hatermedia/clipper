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
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
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
MAX_INSTALLER_BYTES = 512 * 1024 * 1024
MAX_SIGNATURE_BYTES = 4096
# Hex-encoded Ed25519 public keys allowed to sign release SHA256SUMS files.
# When at least one key is listed, every update must ship a valid
# ``<checksums name>.sig`` asset or it is refused. Generate the key pair with
# ``python packaging/sign_release.py keygen`` and keep the private key offline.
UPDATE_PUBLIC_KEYS: tuple[str, ...] = ()
# Optional Authenticode publisher (certificate subject substring). When set, the
# installer must carry a valid signature from that publisher.
UPDATE_PUBLISHER = ""
# Authenticode states that always mean tampering or an untrusted certificate.
_BAD_AUTHENTICODE = {"HashMismatch", "NotTrusted", "Incompatible"}
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

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
    signature_name: str | None = None
    signature_url: str | None = None

    @property
    def has_installer(self) -> bool:
        return bool(self.installer_url and self.installer_name)

    @property
    def has_checksums(self) -> bool:
        return bool(self.checksums_url and self.checksums_name)

    @property
    def has_signature(self) -> bool:
        return bool(self.signature_url and self.signature_name)

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
            "signature_name": self.signature_name,
            "signature_url": self.signature_url,
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
            installer_name=(
                str(value["installer_name"]) if value.get("installer_name") else None
            ),
            installer_url=(
                str(value["installer_url"]) if value.get("installer_url") else None
            ),
            installer_size=max(0, _safe_int(value.get("installer_size", 0), 0)),
            checksums_name=(
                str(value["checksums_name"]) if value.get("checksums_name") else None
            ),
            checksums_url=(
                str(value["checksums_url"]) if value.get("checksums_url") else None
            ),
            signature_name=(
                str(value["signature_name"]) if value.get("signature_name") else None
            ),
            signature_url=(
                str(value["signature_url"]) if value.get("signature_url") else None
            ),
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


def _validate_https_url(url: str) -> None:
    """Reject local paths, UNC paths, HTTP, and private-network update URLs."""

    try:
        parsed = urllib.parse.urlparse(str(url))
        host = (parsed.hostname or "").lower().strip(".")
        port = parsed.port
    except ValueError as exc:
        raise UpdateError(f"Invalid update URL: {url!r}") from exc
    if parsed.scheme.lower() != "https" or not host:
        raise UpdateError(f"Update URLs must use HTTPS: {url!r}")
    if parsed.username or parsed.password:
        raise UpdateError(f"Update URL must not contain credentials: {url!r}")
    if port not in (None, 443):
        raise UpdateError(f"Update URL must use port 443: {url!r}")
    if host == "localhost" or host.endswith(".local"):
        raise UpdateError(f"Update URL host is not allowed: {url!r}")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host:
            raise UpdateError(f"Update URL host is not valid: {url!r}") from None
    else:
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        ):
            raise UpdateError(f"Update URL host is not public: {url!r}")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        absolute = urllib.parse.urljoin(req.full_url, newurl)
        _validate_https_url(absolute)
        return super().redirect_request(req, fp, code, msg, headers, absolute)


def _open_url(url: str, timeout: float):
    _validate_https_url(url)
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    return opener.open(_request(url, timeout), timeout=timeout)


def _request(url: str, timeout: float = 10.0) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json, application/octet-stream",
        },
    )


def _safe_installer_name(name: str | None, version: str) -> str:
    candidate = str(name or f"ClipperSetup-{version}.exe")
    if (
        not candidate
        or candidate in {".", ".."}
        or any(ord(char) < 32 for char in candidate)
        or any(char in candidate for char in ("/", "\\", ":"))
        or Path(candidate).name != candidate
        or not re.fullmatch(
            r"ClipperSetup-[A-Za-z0-9][A-Za-z0-9._-]*\.exe",
            candidate,
            re.IGNORECASE,
        )
    ):
        raise UpdateError(f"Unsafe installer filename: {candidate!r}")
    stem = Path(candidate).stem.upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        raise UpdateError(f"Reserved installer filename: {candidate!r}")
    if candidate.endswith((" ", ".")):
        raise UpdateError(f"Invalid Windows installer filename: {candidate!r}")
    return candidate


def _fetch_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    _validate_https_url(url)
    try:
        with _open_url(url, timeout) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise UpdateError("GitHub returned oversized update metadata.")
            payload = json.loads(raw.decode("utf-8"))
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
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise UpdateError("GitHub returned malformed update metadata.") from exc
    if not isinstance(payload, dict):
        raise UpdateError("GitHub returned an unexpected response.")
    return payload


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _release_from_payload(payload: dict[str, Any]) -> ReleaseInfo:
    tag = str(payload.get("tag_name") or payload.get("name") or "")
    if not tag:
        raise UpdateError("The latest release has no version tag.")
    assets_value = payload.get("assets")
    assets = (
        [item for item in assets_value if isinstance(item, dict)]
        if isinstance(assets_value, list)
        else []
    )
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
            if (
                "sha256" in str(item.get("name", "")).lower()
                or "checksum" in str(item.get("name", "")).lower()
            )
            and not str(item.get("name", "")).lower().endswith(".sig")
        ),
        None,
    )
    signature = None
    if checksums:
        wanted = str(checksums.get("name", "")).lower() + ".sig"
        signature = next(
            (item for item in assets if str(item.get("name", "")).lower() == wanted),
            None,
        )
    installer_name = (
        _safe_installer_name(str(installer.get("name")), tag.lstrip("vV"))
        if installer
        else None
    )
    installer_url = str(installer.get("browser_download_url")) if installer else None
    checksums_url = str(checksums.get("browser_download_url")) if checksums else None
    if installer_url:
        _validate_https_url(installer_url)
    if checksums_url:
        _validate_https_url(checksums_url)
    signature_url = str(signature.get("browser_download_url")) if signature else None
    if signature_url:
        _validate_https_url(signature_url)
    return ReleaseInfo(
        version=tag.lstrip("vV"),
        tag=tag,
        name=str(payload.get("name") or tag),
        notes=str(payload.get("body") or "")[:8000],
        page_url=str(payload.get("html_url") or RELEASES_PAGE),
        published_at=str(payload.get("published_at") or ""),
        installer_name=installer_name,
        installer_url=installer_url,
        installer_size=max(0, _safe_int((installer or {}).get("size", 0), 0)),
        checksums_name=str(checksums.get("name")) if checksums else None,
        checksums_url=checksums_url,
        signature_name=str(signature.get("name")) if signature else None,
        signature_url=signature_url,
    )


def signature_enforced() -> bool:
    """True when this build only accepts Ed25519-signed release checksums."""

    return bool(UPDATE_PUBLIC_KEYS)


def verify_checksums_signature(
    checksums: bytes,
    signature_text: str | bytes,
    keys: tuple[str, ...] | None = None,
) -> bool:
    from .signing import parse_signature, verify

    try:
        signature = parse_signature(signature_text)
    except ValueError:
        return False
    for key in UPDATE_PUBLIC_KEYS if keys is None else keys:
        try:
            public = bytes.fromhex(key.strip())
        except ValueError:
            continue
        if verify(public, checksums, signature):
            return True
    return False


def _require_signature(release: "ReleaseInfo", checksums: bytes, timeout: float) -> None:
    if not signature_enforced():
        return
    if not release.has_signature:
        raise UpdateError(
            "This release has no checksum signature, so Clipper will not install "
            "it. Download it manually from " + release.page_url
        )
    signature_text = _fetch_bytes(
        release.signature_url or "", timeout=timeout, limit=MAX_SIGNATURE_BYTES
    )
    if not verify_checksums_signature(checksums, signature_text):
        raise UpdateError(
            "The release checksums are not signed by the Clipper release key; "
            "refusing to install."
        )


def authenticode_status(path: Path, timeout: float = 60.0) -> tuple[str, str]:
    """Return (status, signer subject) from Windows, or ("Unavailable", "")."""

    if os.name != "nt":
        return "Unavailable", ""
    powershell = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if not powershell.is_file():
        return "Unavailable", ""
    script = (
        f"$sig = Get-AuthenticodeSignature -LiteralPath {_ps_quote(str(path))}; "
        "[pscustomobject]@{"
        "Status = $sig.Status.ToString(); "
        "Subject = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { '' }"
        "} | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=0x08000000,
        )
        if completed.returncode != 0:
            return "Unavailable", ""
        payload = json.loads(completed.stdout.strip() or "{}")
        return str(payload.get("Status") or "Unavailable"), str(payload.get("Subject") or "")
    except (OSError, ValueError, subprocess.SubprocessError):
        return "Unavailable", ""


def _check_authenticode(path: Path) -> None:
    status, subject = authenticode_status(path)
    if status in _BAD_AUTHENTICODE:
        raise UpdateError(f"The installer's Windows signature is {status}; refusing to install.")
    if UPDATE_PUBLISHER:
        if status != "Valid":
            raise UpdateError("The installer is not signed by the Clipper publisher.")
        if UPDATE_PUBLISHER.lower() not in subject.lower():
            raise UpdateError("The installer is signed by an unexpected publisher.")


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


def update_cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "Clipper" / "updates"


def cached_installer_path(release: ReleaseInfo) -> Path:
    name = _safe_installer_name(release.installer_name, release.version)
    return update_cache_dir() / release.version / name


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


def clear_pending_update() -> None:
    state = load_state()
    if "pending" not in state:
        return
    state.pop("pending", None)
    save_state(state)


def save_pending_update(release: ReleaseInfo, installer: Path | str) -> None:
    path = Path(installer)
    if not path.is_file():
        return
    state = load_state()
    state["pending"] = {
        "release": release.to_dict(),
        "installer": str(path.resolve()),
        "sha256": sha256_file(path),
    }
    save_state(state)


def load_pending_update() -> tuple[ReleaseInfo, Path] | None:
    state = load_state()
    pending = state.get("pending")
    if not isinstance(pending, dict):
        return None
    try:
        release = ReleaseInfo.from_dict(dict(pending.get("release") or {}))
        path = Path(str(pending.get("installer") or ""))
        expected = str(pending.get("sha256") or "").lower()
    except (TypeError, ValueError, OSError):
        clear_pending_update()
        return None
    if not version_is_newer(release.version, __version__):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        clear_pending_update()
        return None
    if not expected or not path.is_file() or not path.parent.is_dir():
        clear_pending_update()
        return None
    if sha256_file(path).lower() != expected:
        clear_pending_update()
        return None
    return release, path


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
        except (TypeError, ValueError, OverflowError):
            return check_with_cache(current, max_age, force=True, timeout=timeout)
        return (release if version_is_newer(release.version, current) else None), True

    latest = fetch_latest(timeout=timeout)
    state["checked_at"] = now
    state["current"] = current
    state["release"] = latest.to_dict()
    save_state(state)
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
    return _fetch_bytes(url, timeout=timeout).decode("utf-8", errors="replace")


def _fetch_bytes(url: str, timeout: float = 30.0, limit: int = 4 * 1024 * 1024) -> bytes:
    _validate_https_url(url)
    try:
        with _open_url(url, timeout) as response:
            raw = response.read(limit + 1)
            if len(raw) > limit:
                raise UpdateError("Update metadata is unreasonably large.")
            return raw
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"Update metadata returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"Could not download update metadata: {exc.reason}") from exc
    except TimeoutError as exc:
        raise UpdateError("The update metadata request timed out.") from exc


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
    if release.installer_size > MAX_INSTALLER_BYTES:
        raise UpdateError("The release installer exceeds the download size limit.")

    name = _safe_installer_name(release.installer_name, release.version)
    created_dir: Path | None = None
    if destination is None:
        created_dir = Path(tempfile.mkdtemp(prefix="clipper-update-"))
        target = created_dir / name
    else:
        target = Path(destination)
        if target.name != name:
            raise UpdateError("Installer destination name does not match release asset.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if created_dir is not None:
        try:
            target.resolve().relative_to(created_dir.resolve())
        except ValueError as exc:
            raise UpdateError("Installer destination escaped the temp directory.") from exc
    partial = target.with_suffix(target.suffix + ".part")

    def cleanup_partial() -> None:
        partial.unlink(missing_ok=True)
        if created_dir is not None and created_dir.is_dir():
            shutil.rmtree(created_dir, ignore_errors=True)

    checksums_text = ""
    try:
        checksums_text = _fetch_text(release.checksums_url or "", timeout=timeout)
        # Release checksum files are ASCII, so these are the exact signed bytes.
        _require_signature(release, checksums_text.encode("utf-8"), timeout)
    except Exception:
        if created_dir is not None:
            shutil.rmtree(created_dir, ignore_errors=True)
        raise
    expected = parse_checksums(checksums_text).get(name.lower())
    if not expected:
        if created_dir is not None:
            shutil.rmtree(created_dir, ignore_errors=True)
        raise UpdateError(
            f"The release checksums do not list {name}; refusing to install it."
        )
    if target.is_file() and sha256_file(target).lower() == expected:
        # A verified installer from an earlier attempt is already on disk.
        _check_authenticode(target)
        return target

    digest = hashlib.sha256()
    downloaded = 0
    total = release.installer_size
    try:
        with _open_url(release.installer_url or "", timeout) as response:
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if "text/html" in content_type or "text/plain" in content_type:
                raise UpdateError("The installer URL returned a web page, not an installer.")
            try:
                response_size = int(response.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                response_size = 0
            if response_size > MAX_INSTALLER_BYTES:
                raise UpdateError("The installer exceeds the download size limit.")
            total = response_size or total
            with partial.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > MAX_INSTALLER_BYTES:
                        raise UpdateError("The installer exceeded the download size limit.")
                    handle.write(chunk)
                    digest.update(chunk)
                    if progress:
                        progress(downloaded, total)
    except UpdateError:
        cleanup_partial()
        raise
    except urllib.error.HTTPError as exc:
        cleanup_partial()
        raise UpdateError(f"Installer download returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        cleanup_partial()
        raise UpdateError(f"Download failed: {exc.reason}") from exc
    except OSError as exc:
        cleanup_partial()
        raise UpdateError(f"Could not save the installer: {exc}") from exc

    try:
        if downloaded == 0:
            raise UpdateError("The downloaded installer is empty.")
        if release.installer_size > 0 and downloaded != release.installer_size:
            raise UpdateError(
                f"Installer download is truncated ({downloaded} of "
                f"{release.installer_size} bytes)."
            )
        with partial.open("rb") as handle:
            if handle.read(2) != b"MZ":
                raise UpdateError("The downloaded file is not a Windows executable.")
        actual = digest.hexdigest()
        if actual != expected:
            raise UpdateError(
                "The downloaded installer failed SHA-256 verification "
                f"(expected {expected[:12]}..., got {actual[:12]}...)."
            )
        partial.replace(target)
        try:
            _check_authenticode(target)
        except UpdateError:
            target.unlink(missing_ok=True)
            raise
    except UpdateError:
        cleanup_partial()
        raise
    except OSError as exc:
        cleanup_partial()
        raise UpdateError(f"Could not finalize the installer: {exc}") from exc
    return target


def cleanup_download(path: Path | str) -> None:
    """Remove a verified installer and its unique download directory."""

    try:
        target = Path(path).resolve()
        parent = target.parent
        temp_root = Path(tempfile.gettempdir()).resolve()
        if parent.name.startswith("clipper-update-"):
            try:
                parent.relative_to(temp_root)
            except ValueError:
                return
            shutil.rmtree(parent, ignore_errors=True)
    except OSError:
        pass


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _registered_install_exe() -> Path | None:
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
    return None


def installed_exe() -> Path:
    """Best guess at the installed Clipper.exe path."""

    registered = _registered_install_exe()
    if registered is not None:
        return registered
    return Path(sys.executable)


def is_installed_build() -> bool:
    """True when running the frozen app from the registered install folder."""

    if not getattr(sys, "frozen", False) or os.name != "nt":
        return False
    exe = Path(sys.executable).resolve()
    if exe.name.lower() != "clipper.exe":
        return False
    registered = _registered_install_exe()
    if registered is None:
        return False
    try:
        return exe == registered.resolve()
    except OSError:
        return False


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


def _wait_for_helper_marker(
    log_path: Path, offset: int, timeout: float = 6.0
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with log_path.open("rb") as handle:
                handle.seek(max(0, offset))
                chunk = handle.read().decode("utf-8", errors="replace")
            if "helper start" in chunk:
                return True
        except OSError:
            pass
        time.sleep(0.2)
    return False


def _helper_script(
    installer_path: Path,
    exe: Path,
    log_path: Path,
    *,
    relaunch: bool,
    wait_pid: int | None,
) -> list[str]:
    installer_dir = installer_path.parent
    if exe.name.lower() == "clipper.exe":
        install_dir = exe.parent
    else:
        install_dir = (
            Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
            / "Programs"
            / "Clipper"
        )
    lines = [
        "$ErrorActionPreference = 'SilentlyContinue'",
        f"$log = {_ps_quote(str(log_path))}",
        "function Write-UpdateLog([string]$message) { "
        "Add-Content -LiteralPath $log -Value \"$(Get-Date -Format o) $message\" }",
        f"$installerDir = {_ps_quote(str(installer_dir))}",
        "$helperDir = Split-Path -Parent $MyInvocation.MyCommand.Path",
        "function Remove-InstallerDir {",
        "  if ($installerDir -like \"$env:TEMP\\clipper-update-*\") { "
        "Remove-Item -LiteralPath $installerDir -Recurse -Force -ErrorAction SilentlyContinue }",
        "}",
        "function Remove-HelperDir {",
        "  Remove-Item -LiteralPath $helperDir -Recurse -Force -ErrorAction SilentlyContinue",
        "}",
        "function Remove-TempDirs { Remove-InstallerDir; Remove-HelperDir }",
        f"$installDir = {_ps_quote(str(install_dir).rstrip(chr(92)))}",
        # Only touch Clipper processes running from this install folder; an
        # unrelated program that happens to be called Clipper.exe is left alone.
        "function Get-ClipperProcess { @(Get-CimInstance Win32_Process "
        "-Filter \"Name='Clipper.exe'\" -ErrorAction SilentlyContinue | "
        "Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($installDir + '\\', "
        "[System.StringComparison]::OrdinalIgnoreCase) } | "
        "ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }) }",
        "Write-UpdateLog 'helper start'",
        f"$targetPid = {int(wait_pid or 0)}",
        "$deadline = (Get-Date).AddSeconds(90)",
        "while ($targetPid -gt 0 -and (Get-Process -Id $targetPid -ErrorAction SilentlyContinue) "
        "-and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }",
        "$deadline = (Get-Date).AddSeconds(90)",
        "while ((Get-ClipperProcess).Count -gt 0 "
        "-and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }",
        "$running = Get-ClipperProcess",
        "if ($running.Count -gt 0) {",
        "  $running | ForEach-Object { $_.CloseMainWindow() | Out-Null }",
        "  Start-Sleep -Seconds 3",
        "}",
        "$running = Get-ClipperProcess",
        "if ($running.Count -gt 0) {",
        "  $running | Stop-Process -Force -ErrorAction SilentlyContinue",
        "  Start-Sleep -Seconds 2",
        "}",
        "if ((Get-ClipperProcess).Count -gt 0) {",
        "  Write-UpdateLog 'Clipper did not exit; aborting before install'",
        "  Remove-TempDirs",
        "  exit 92",
        "}",
        f"$installer = {_ps_quote(str(installer_path))}",
        "Write-UpdateLog 'running installer'",
        "try {",
        "  $proc = Start-Process -FilePath $installer -ArgumentList '/S' -PassThru -ErrorAction Stop",
        "} catch {",
        "  Write-UpdateLog \"installer launch failed: $_\"",
        "  Remove-TempDirs",
        "  exit 90",
        "}",
        "if ($null -eq $proc) {",
        "  Write-UpdateLog 'installer did not return a process handle'",
        "  Remove-TempDirs",
        "  exit 90",
        "}",
        "$installerTimeoutMs = 900000",
        "if (-not $proc.WaitForExit($installerTimeoutMs)) {",
        "  Write-UpdateLog 'installer timed out; terminating it'",
        "  & \"$env:SystemRoot\\System32\\taskkill.exe\" /F /PID $proc.Id /T | Out-Null",
        "  Remove-TempDirs",
        "  exit 93",
        "}",
        "$proc.Refresh()",
        "if ($proc.ExitCode -ne 0) {",
        "  Write-UpdateLog \"installer failed: $($proc.ExitCode)\"",
        "  Remove-TempDirs",
        "  exit 91",
        "}",
        "Write-UpdateLog 'installer finished'",
        "Remove-InstallerDir",
    ]
    if relaunch:
        lines.extend(
            [
                f"$exe = {_ps_quote(str(exe))}",
                "if (Test-Path -LiteralPath $exe) { Start-Process -FilePath $exe }",
            ]
        )
    lines.append("Remove-HelperDir")
    return lines


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
    temp_root = Path(tempfile.gettempdir()).resolve()
    trusted = False
    try:
        installer_path.relative_to(temp_root)
        if installer_path.parent.name.startswith("clipper-update-"):
            trusted = True
    except ValueError:
        pass
    if not trusted:
        try:
            installer_path.relative_to(update_cache_dir().resolve())
            trusted = True
        except ValueError as exc:
            raise UpdateError(
                "Installer path is outside the update temp/cache directory."
            ) from exc
    if not trusted:
        raise UpdateError("Installer path is not a Clipper update download.")
    exe = installed_exe()
    # A source/pip CLI has no app to relaunch; the installer adds a Start Menu
    # shortcut instead of opening python.exe with no arguments.
    if relaunch and not getattr(sys, "frozen", False):
        relaunch = False
    log_path = (
        Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
        / "Clipper"
        / "update.log"
    )
    try:
        log_offset = log_path.stat().st_size
    except OSError:
        log_offset = 0
    _update_log(f"install requested: {installer_path} relaunch={relaunch} wait_pid={wait_pid}")

    lines = _helper_script(
        installer_path,
        exe,
        log_path,
        relaunch=relaunch,
        wait_pid=wait_pid,
    )

    try:
        helper_dir = Path(tempfile.mkdtemp(prefix="clipper-helper-"))
    except OSError as exc:
        raise UpdateError(f"Could not create the installer helper: {exc}") from exc
    helper = helper_dir / "install.ps1"
    try:
        helper.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    except OSError as exc:
        shutil.rmtree(helper_dir, ignore_errors=True)
        raise UpdateError(f"Could not create the installer helper: {exc}") from exc

    powershell = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if not powershell.is_file():
        found = shutil.which("powershell.exe")
        if not found:
            raise UpdateError("Could not find Windows PowerShell.")
        powershell = Path(found)
    command = [
        str(powershell),
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
    shell_started = False
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
            shell_started = result > 32
        except Exception as exc:
            _update_log(f"ShellExecute failed: {exc}")

    if not shell_started:
        creationflags = 0
        if os.name == "nt":
            creationflags = (
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        try:
            process = subprocess.Popen(
                command,
                creationflags=creationflags,
                close_fds=True,
            )
            _update_log(f"Popen helper pid={process.pid}")
        except OSError as exc:
            shutil.rmtree(helper_dir, ignore_errors=True)
            _update_log(f"Popen helper failed: {exc}")
            raise UpdateError(f"Could not start the installer helper: {exc}") from exc

    if _wait_for_helper_marker(log_path, log_offset):
        return helper
    shutil.rmtree(helper_dir, ignore_errors=True)
    _update_log("helper did not confirm startup")
    raise UpdateError(
        "The installer helper did not start. Please retry the update."
    )


def open_release_page(release: ReleaseInfo | None = None) -> None:
    url = release.page_url if release else RELEASES_PAGE
    try:
        _validate_https_url(url)
    except UpdateError:
        url = RELEASES_PAGE
    try:
        import webbrowser

        webbrowser.open(url)
    except (AttributeError, OSError):
        pass
