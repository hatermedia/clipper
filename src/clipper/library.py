"""Local scan library for Clipper.

The library keeps previous scans, clip decisions, notes, tags, evidence, and
export history in one versioned JSON file under the per-user Clipper folder.
It is deliberately local-only and dependency-free. Footage is never copied into
the library; only paths, cut metadata, and user-authored text are stored.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import AnalysisSummary, ClipWindow, FileAnalysis, clip_key

SCHEMA_VERSION = 1
DEFAULT_MAX_SCANS = 200


class LibraryError(RuntimeError):
    """Raised when the local scan library cannot be read or written."""


def app_data_dir() -> Path:
    """The per-user Clipper data folder used for settings and models."""

    override = os.environ.get("CLIPPER_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "Clipper"
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "clipper"


def library_dir() -> Path:
    override = os.environ.get("CLIPPER_LIBRARY_DIR")
    return Path(override).expanduser() if override else app_data_dir() / "library"


def library_path() -> Path:
    override = os.environ.get("CLIPPER_LIBRARY_PATH")
    return Path(override).expanduser() if override else library_dir() / "library.json"


def preview_dir() -> Path:
    """Stable preview cache so a reopened scan still has poster frames."""

    return library_dir() / "previews"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scan_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"scan_{stamp}_{secrets.token_hex(3)}"


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise LibraryError(f"Could not create the clip library folder: {exc}") from exc
    temp = path.with_name(path.name + ".tmp")
    try:
        text = json.dumps(payload, indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise LibraryError(f"Could not serialize the clip library: {exc}") from exc
    try:
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, path)
    except OSError as exc:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise LibraryError(f"Could not write the clip library: {exc}") from exc


def _iter_clips(summary: AnalysisSummary) -> Iterable[tuple[FileAnalysis, ClipWindow]]:
    for analysis in summary.files:
        for clip in analysis.clips:
            yield analysis, clip


def ensure_clip_ids(summary: AnalysisSummary) -> None:
    for analysis, clip in _iter_clips(summary):
        if not clip.id:
            clip.id = clip_key(analysis.path, clip.start, clip.end)


def _clip_overlays(summary: AnalysisSummary) -> dict[str, dict[str, Any]]:
    overlays: dict[str, dict[str, Any]] = {}
    for _analysis, clip in _iter_clips(summary):
        if not clip.id:
            continue
        overlays[clip.id] = {
            "keep": bool(clip.keep),
            "note": clip.note,
            "tags": list(clip.tags),
            "exports": [dict(item) for item in clip.exports],
        }
    return overlays


@dataclass(frozen=True)
class ScanInfo:
    id: str
    created_at: str
    updated_at: str
    input_path: str
    files: int
    clips: int
    kept: int

    @property
    def label(self) -> str:
        stamp = self.created_at.replace("T", " ")[:16]
        name = Path(self.input_path).name or self.input_path or "scan"
        return f"{stamp}  {name}  ({self.clips} clips)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "input_path": self.input_path,
            "files": self.files,
            "clips": self.clips,
            "kept": self.kept,
        }


class ClipLibrary:
    """A small, thread-safe, atomic JSON library of scan summaries."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        max_scans: int = DEFAULT_MAX_SCANS,
    ) -> None:
        self.path = Path(path).expanduser() if path is not None else library_path()
        self.max_scans = max(1, int(max_scans))
        self._lock = threading.RLock()
        self._raw: dict[str, Any] = {"schema": SCHEMA_VERSION, "scans": []}
        self._load()

    # -------------------------------------------------------------- storage
    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            backup = self.path.with_name(
                f"{self.path.name}.corrupt-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            )
            try:
                shutil.copy2(self.path, backup)
            except OSError:
                backup = None
            hint = f" A backup was kept at {backup}." if backup else ""
            raise LibraryError(f"Could not read the clip library: {exc}.{hint}") from exc
        if not isinstance(data, dict):
            raise LibraryError("The clip library has an unexpected format.")
        scans = data.get("scans")
        if not isinstance(scans, list):
            raise LibraryError("The clip library is missing its scan list.")
        self._raw = {
            "schema": _int_value(data.get("schema"), SCHEMA_VERSION),
            "scans": [item for item in scans if isinstance(item, dict)],
        }

    def reload(self) -> None:
        with self._lock:
            self._raw = {"schema": SCHEMA_VERSION, "scans": []}
            self._load()

    def _save(self) -> None:
        self._raw["schema"] = SCHEMA_VERSION
        _atomic_write(self.path, self._raw)

    def save(self, summary: AnalysisSummary) -> AnalysisSummary:
        """Save or update a scan and return it with scan and clip identifiers.

        A brand new scan inherits keep/note/tag/export decisions from the most
        recent scan of the same source files. That makes a rescan feel like a
        refresh instead of a reset.
        """

        with self._lock:
            now = _now()
            ensure_clip_ids(summary)
            existing = self._find_raw(summary.scan_id) if summary.scan_id else None
            if not summary.scan_id:
                summary.scan_id = _scan_id()
            if existing is not None:
                summary.created_at = str(existing.get("created_at") or summary.created_at or now)
            elif not summary.created_at:
                summary.created_at = now
            summary.updated_at = now

            if existing is None:
                previous = self._latest_raw_for_inputs(summary)
                if previous is not None:
                    try:
                        overlay_source = AnalysisSummary.from_dict(previous)
                    except Exception:
                        overlay_source = None
                    if overlay_source is not None:
                        overlays = _clip_overlays(overlay_source)
                        for _analysis, clip in _iter_clips(summary):
                            overlay = overlays.get(clip.id)
                            if overlay is None:
                                continue
                            clip.keep = bool(overlay["keep"])
                            if overlay.get("note"):
                                clip.note = str(overlay.get("note") or "")
                            if overlay.get("tags"):
                                clip.tags = list(overlay.get("tags") or [])
                            if overlay.get("exports"):
                                clip.exports = [
                                    dict(item) for item in overlay.get("exports") or []
                                ]

            payload = summary.to_dict(include_previews=True)
            scans = [
                item
                for item in self._raw.get("scans", [])
                if str(item.get("scan_id") or "") != summary.scan_id
            ]
            scans.insert(0, payload)
            scans.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
            self._raw["scans"] = scans[: self.max_scans]
            self._save()
            return summary

    def _find_raw(self, scan_id: str) -> dict[str, Any] | None:
        if not scan_id:
            return None
        for item in self._raw.get("scans", []):
            if str(item.get("scan_id") or "") == scan_id:
                return item
        return None

    def _latest_raw_for_inputs(self, summary: AnalysisSummary) -> dict[str, Any] | None:
        sources = {analysis.path for analysis in summary.files if analysis.path}
        if not sources:
            return None
        for item in self._raw.get("scans", []):
            try:
                old = AnalysisSummary.from_dict(item)
            except Exception:
                continue
            old_sources = {analysis.path for analysis in old.files if analysis.path}
            if sources & old_sources:
                return item
        return None

    # --------------------------------------------------------------- reading
    def scans(self) -> list[ScanInfo]:
        with self._lock:
            result: list[ScanInfo] = []
            for item in self._raw.get("scans", []):
                raw_summary = item.get("summary")
                summary = raw_summary if isinstance(raw_summary, dict) else {}
                scan_id = str(item.get("scan_id") or "")
                if not scan_id:
                    continue
                files = _int_value(summary.get("files"))
                clips = _int_value(summary.get("clips"))
                kept = summary.get("kept")
                if kept is None:
                    try:
                        loaded = AnalysisSummary.from_dict(item)
                        kept = sum(
                            1 for _file, clip in _iter_clips(loaded) if clip.keep
                        )
                        files = files or len(loaded.files)
                        clips = clips or loaded.total_clips
                    except Exception:
                        kept = 0
                result.append(
                    ScanInfo(
                        id=scan_id,
                        created_at=str(item.get("created_at") or ""),
                        updated_at=str(item.get("updated_at") or ""),
                        input_path=str(item.get("input") or ""),
                        files=files,
                        clips=clips,
                        kept=_int_value(kept),
                    )
                )
            return result

    def load(self, scan_id: str) -> AnalysisSummary | None:
        with self._lock:
            item = self._find_raw(scan_id)
            if item is None:
                return None
            summary = AnalysisSummary.from_dict(item)
            if not summary.scan_id:
                summary.scan_id = scan_id
            ensure_clip_ids(summary)
            return summary

    def latest(self) -> AnalysisSummary | None:
        scans = self.scans()
        return self.load(scans[0].id) if scans else None

    def latest_for_input(self, input_path: str) -> AnalysisSummary | None:
        wanted = os.path.normcase(os.path.abspath(str(input_path)))
        for info in self.scans():
            if os.path.normcase(os.path.abspath(info.input_path)) == wanted:
                return self.load(info.id)
        return None

    # -------------------------------------------------------------- mutating
    def set_clip(
        self,
        scan_id: str,
        clip_id: str,
        *,
        keep: bool | None = None,
        note: str | None = None,
        tags: list[str] | None = None,
    ) -> bool:
        with self._lock:
            summary = self.load(scan_id)
            if summary is None:
                return False
            changed = False
            for _analysis, clip in _iter_clips(summary):
                if clip.id != clip_id:
                    continue
                if keep is not None and clip.keep != bool(keep):
                    clip.keep = bool(keep)
                    changed = True
                if note is not None and clip.note != note:
                    clip.note = note
                    changed = True
                if tags is not None:
                    cleaned = _clean_tags(tags)
                    if clip.tags != cleaned:
                        clip.tags = cleaned
                        changed = True
                break
            if changed:
                self.save(summary)
            return changed

    def set_all_keep(self, scan_id: str, keep: bool) -> int:
        with self._lock:
            summary = self.load(scan_id)
            if summary is None:
                return 0
            changed = 0
            for _analysis, clip in _iter_clips(summary):
                if clip.keep != bool(keep):
                    clip.keep = bool(keep)
                    changed += 1
            if changed:
                self.save(summary)
            return changed

    def record_exports(self, scan_id: str, items: Iterable[Any]) -> int:
        """Attach export records to clips. Items may be dicts or objects."""

        with self._lock:
            summary = self.load(scan_id)
            if summary is None:
                return 0
            by_id = {clip.id: clip for _analysis, clip in _iter_clips(summary)}
            recorded = 0
            for item in items:
                if isinstance(item, dict):
                    data = dict(item)
                elif hasattr(item, "to_dict"):
                    data = dict(item.to_dict())
                else:
                    data = {
                        "clip_id": getattr(item, "clip_id", ""),
                        "path": getattr(item, "path", ""),
                        "preset": getattr(item, "preset", ""),
                        "error": getattr(item, "error", None),
                        "at": getattr(item, "at", ""),
                    }
                clip_id = str(data.get("clip_id") or "")
                clip = by_id.get(clip_id)
                if clip is None:
                    continue
                record = {
                    "path": str(data.get("path") or ""),
                    "preset": str(data.get("preset") or ""),
                    "at": str(data.get("at") or _now()),
                }
                if data.get("error"):
                    record["error"] = str(data["error"])
                clip.exports.append(record)
                clip.exports = clip.exports[-20:]
                recorded += 1
            if recorded:
                self.save(summary)
            return recorded

    def delete(self, scan_id: str) -> bool:
        with self._lock:
            before = len(self._raw.get("scans", []))
            self._raw["scans"] = [
                item
                for item in self._raw.get("scans", [])
                if str(item.get("scan_id") or "") != scan_id
            ]
            changed = len(self._raw["scans"]) != before
            if changed:
                self._save()
            return changed

    def clear(self) -> None:
        with self._lock:
            self._raw = {"schema": SCHEMA_VERSION, "scans": []}
            self._save()

    def prune(self, max_scans: int | None = None) -> int:
        with self._lock:
            limit = max(1, int(max_scans or self.max_scans))
            before = len(self._raw.get("scans", []))
            self._raw["scans"] = self._raw.get("scans", [])[:limit]
            removed = before - len(self._raw["scans"])
            if removed:
                self._save()
            return removed


def _clean_tags(tags: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in tags:
        tag = " ".join(str(raw).split()).strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        cleaned.append(tag[:32])
    return cleaned[:12]
