from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from clipper.web.app import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "0.1.0"
    assert "ok" in payload


def test_index_serves_ui() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "CLIPPER" in response.text


def test_browse_roots() -> None:
    response = client.get("/api/browse")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["roots"], list)
    assert payload["roots"]


def test_scan_folder(tmp_path: Path) -> None:
    (tmp_path / "a.mp4").write_bytes(b"not a real video")
    (tmp_path / "ignore.txt").write_text("nope")
    response = client.post("/api/scan", json={"input": str(tmp_path)})
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["files"][0]["name"] == "a.mp4"


def test_analyze_empty_folder_is_rejected(tmp_path: Path) -> None:
    response = client.post(
        "/api/analyze",
        json={"input": str(tmp_path), "recursive": False, "sensitivity": 0.5},
    )
    assert response.status_code == 400


def test_thumbnail_missing_file_is_404() -> None:
    response = client.get("/api/thumb", params={"file": "C:/nope/missing.mp4", "t": 1.0})
    assert response.status_code == 404


def test_export_unknown_analysis_is_404() -> None:
    response = client.post(
        "/api/export",
        json={"analysis_id": "does-not-exist", "output": "trimmed"},
    )
    assert response.status_code == 404
