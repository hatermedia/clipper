from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from clipper import __version__
from clipper.web.app import app

client = TestClient(app, base_url="http://127.0.0.1:8765")


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == __version__
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


def test_foreign_host_header_is_refused() -> None:
    # DNS rebinding: a hostile domain pointed at 127.0.0.1 keeps its own Host.
    response = client.get("/api/browse", headers={"Host": "evil.example:8765"})
    assert response.status_code == 421
    assert client.get("/", headers={"Host": "attacker.test"}).status_code == 421


def test_localhost_hosts_are_allowed() -> None:
    for host in ("localhost:8765", "127.0.0.1", "[::1]:8765"):
        assert client.get("/api/health", headers={"Host": host}).status_code == 200


def test_extra_allowed_host_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CLIPPER_ALLOWED_HOSTS", "nas.lan, clipper.home")
    assert client.get("/api/health", headers={"Host": "nas.lan:8765"}).status_code == 200


def test_cross_site_and_foreign_origin_api_calls_are_refused(tmp_path: Path) -> None:
    blocked = client.post(
        "/api/scan",
        json={"input": str(tmp_path)},
        headers={"Origin": "https://evil.example"},
    )
    assert blocked.status_code == 403
    sneaky = client.get(
        "/api/thumb",
        params={"file": "C:/x.mp4", "t": 0},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert sneaky.status_code == 403
    same = client.post(
        "/api/scan",
        json={"input": str(tmp_path)},
        headers={"Origin": "http://127.0.0.1:8765", "Sec-Fetch-Site": "same-origin"},
    )
    assert same.status_code == 200


def test_security_headers_and_no_path_leak() -> None:
    response = client.get("/api/health")
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    payload = response.json()
    assert "cwd" not in payload and "ffmpeg_path" not in payload


def test_index_loads_no_third_party_assets() -> None:
    html = client.get("/").text
    assert "cdn.tailwindcss.com" not in html
    assert "cdn.jsdelivr.net" not in html
    assert "/static/vendor/alpine.min.js" in html
    assert client.get("/static/vendor/alpine.min.js").status_code == 200
    assert client.get("/static/vendor/tailwind.css").status_code == 200


def test_roots_confine_every_path_endpoint(tmp_path: Path, monkeypatch) -> None:
    allowed = tmp_path / "footage"
    allowed.mkdir()
    (allowed / "a.mp4").write_bytes(b"x")
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "b.mp4").write_bytes(b"x")
    monkeypatch.setenv("CLIPPER_ROOTS", str(allowed))

    roots = client.get("/api/browse").json()["roots"]
    assert roots == [str(allowed.resolve())]
    assert client.get("/api/browse", params={"path": str(allowed)}).status_code == 200
    assert client.get("/api/browse", params={"path": str(outside)}).status_code == 403
    assert client.post("/api/scan", json={"input": str(allowed)}).status_code == 200
    assert client.post("/api/scan", json={"input": str(outside)}).status_code == 403
    assert client.post("/api/analyze", json={"input": str(outside)}).status_code == 403
    thumb = client.get("/api/thumb", params={"file": str(outside / "b.mp4"), "t": 0})
    assert thumb.status_code == 403


def test_analyze_request_uses_the_ai_director() -> None:
    from clipper.web.app import AnalyzeRequest

    settings = AnalyzeRequest(input="x").settings()
    assert settings.ai is True and settings.ai_mode == "director"
    server = AnalyzeRequest(
        input="x", ai_model="llava", ai_server_url="http://127.0.0.1:1234/v1/"
    ).settings()
    assert server.ai_model == "server:llava"
    assert server.ai_server_url == "http://127.0.0.1:1234"


def test_analyze_rejects_bad_server_url(tmp_path: Path) -> None:
    (tmp_path / "a.mp4").write_bytes(b"x")
    response = client.post(
        "/api/analyze",
        json={"input": str(tmp_path), "ai_server_url": "file:///C:/Windows/win.ini"},
    )
    assert response.status_code == 400


def test_export_rejects_unknown_x264_preset() -> None:
    from clipper.web.app import manager
    from clipper.models import AnalysisSummary

    analysis_id = manager.store_analysis(AnalysisSummary(files=[], input_path="x"))
    response = client.post(
        "/api/export",
        json={"analysis_id": analysis_id, "output": "trimmed", "preset": "-y"},
    )
    assert response.status_code == 400
