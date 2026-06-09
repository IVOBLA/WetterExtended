import io
import json
import os
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from debug_export import create_debug_export_zip, parse_timestamp_from_name
from export_security import REDACTION_VALUE, redact_text


def _set_mtime(path: Path, dt: datetime):
    ts = dt.timestamp()
    os.utime(path, (ts, ts))


@pytest.fixture()
def export_tree(tmp_path, monkeypatch):
    now = datetime(2026, 6, 9, 9, 0, 0, tzinfo=timezone.utc)
    for rel in [
        "train_data/radar",
        "train_data/objects",
        "train_data/evaluation",
        "train_data/external_responses/geosphere_nowcast",
    ]:
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    (tmp_path / "data").mkdir()

    recent_radar = tmp_path / "train_data/radar/radar_2026-06-09_08-15-00.png"
    recent_radar.write_bytes(b"PNG")
    old_radar = tmp_path / "train_data/radar/radar_2026-06-07_08-15-00.png"
    old_radar.write_bytes(b"OLD")
    _set_mtime(old_radar, now)

    latest_objects = tmp_path / "latest_objects.json"
    latest_objects.write_text('{"API_KEY":"abc","cells":[1]}', encoding="utf-8")
    forecast = tmp_path / "forecast.kmz"
    forecast.write_bytes(b"KMZ")
    (tmp_path / "data/latest.png").write_bytes(b"LATEST")
    (tmp_path / "train_data/evaluation/accuracy_2026-06-09_08-30-00.json").write_text('{"ok":true}', encoding="utf-8")
    (tmp_path / "train_data/external_responses/geosphere_nowcast/geosphere_nowcast_2026-06-09_08-31-00_200_abcd.json").write_text(
        '{"url":"https://x.test?a=1&token=abc","response_body":"ok"}', encoding="utf-8"
    )
    (tmp_path / "config.py").write_text('API_KEY="abc"\nSAFE=1\n', encoding="utf-8")

    save_paths = {
        "radar": str(tmp_path / "train_data/radar"),
        "objects": str(tmp_path / "train_data/objects"),
        "evaluation": str(tmp_path / "train_data/evaluation"),
    }
    return tmp_path, save_paths, now


def _zip_names_and_manifest(zip_path: Path):
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        manifest_name = next(name for name in names if name.endswith("/manifest.json"))
        manifest = json.loads(zf.read(manifest_name).decode("utf-8"))
        contents = {name: zf.read(name) for name in names}
    return names, manifest, contents


def test_timestamp_parser_supported_formats():
    assert parse_timestamp_from_name("wetter_2026-06-09_08-15-00.json") == datetime(2026, 6, 9, 8, 15, tzinfo=timezone.utc)
    assert parse_timestamp_from_name("radar_20260609_081500.png") == datetime(2026, 6, 9, 8, 15, tzinfo=timezone.utc)
    assert parse_timestamp_from_name("external_2026-06-09T08-15-00.json") == datetime(2026, 6, 9, 8, 15, tzinfo=timezone.utc)


@pytest.mark.parametrize("sample", [
    "API_KEY=abc",
    "JWT_SECRET=abc",
    "password=abc",
    "token=abc",
    "https://x.test?a=1&token=abc",
    "Authorization: Bearer abc",
])
def test_redaction_patterns(sample):
    assert REDACTION_VALUE in redact_text(sample)
    assert "abc" not in redact_text(sample)


def test_debug_export_zip_contains_expected_recent_files_and_redacts(export_tree):
    base, save_paths, now = export_tree
    zip_path, filename, manifest = create_debug_export_zip(base_dir=base, save_paths=save_paths, now=now)
    try:
        assert filename == "wetterextended_debug_2026-06-09_09-00-00_last24h.zip"
        names, manifest, contents = _zip_names_and_manifest(zip_path)
        assert any(name.endswith("/manifest.json") for name in names)
        assert any(name.endswith("radar_2026-06-09_08-15-00.png") for name in names)
        assert any(name.endswith("latest_objects.json") for name in names)
        assert any(name.endswith("forecast.kmz") for name in names)
        assert not any(name.endswith("radar_2026-06-07_08-15-00.png") for name in names)
        redacted_text = b"\n".join(contents.values()).decode("utf-8", errors="ignore")
        assert "***REDACTED***" in redacted_text
        assert "API_KEY\": \"abc" not in redacted_text
        assert manifest["radar_files_count"] >= 1
        assert manifest["objects_files_count"] >= 1
        assert manifest["forecast_files_count"] >= 1
        assert "geosphere_nowcast" in manifest["external_sources_detected"]
    finally:
        zip_path.unlink(missing_ok=True)


def test_debug_export_missing_directories_do_not_fail(tmp_path):
    (tmp_path / "config.py").write_text("SAFE=1\n", encoding="utf-8")
    zip_path, _filename, manifest = create_debug_export_zip(
        base_dir=tmp_path,
        save_paths={"radar": str(tmp_path / "missing-radar"), "objects": str(tmp_path / "missing-objects"), "evaluation": str(tmp_path / "missing-eval")},
        now=datetime(2026, 6, 9, 9, 0, 0, tzinfo=timezone.utc),
    )
    try:
        assert "radar" in manifest["missing_expected_sections"]
        assert "evaluation" in manifest["missing_expected_sections"]
    finally:
        zip_path.unlink(missing_ok=True)


@pytest.fixture()
def client_with_export_data(export_tree, monkeypatch):
    pytest.importorskip("flask")
    import app as app_module

    base, save_paths, now = export_tree
    monkeypatch.setitem(app_module.SAVE_PATHS, "radar", save_paths["radar"])
    monkeypatch.setitem(app_module.SAVE_PATHS, "objects", save_paths["objects"])
    monkeypatch.setitem(app_module.SAVE_PATHS, "evaluation", save_paths["evaluation"])
    # Route nutzt Projektwurzel für config.py, die Daten kommen aus den gemonkeypatchten SAVE_PATHS.
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def test_export_route_requires_admin_auth(client_with_export_data):
    resp = client_with_export_data.get("/api/admin/export/last-24h.zip")
    assert resp.status_code == 401


def test_export_route_returns_zip_with_admin_auth(client_with_export_data, monkeypatch):
    monkeypatch.setattr("auth.get_current_user", lambda: {"role": "admin", "sub": "1"})
    resp = client_with_export_data.get("/api/admin/export/last-24h.zip")
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    assert "wetterextended_debug_" in resp.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        names = zf.namelist()
        assert any(name.endswith("/manifest.json") for name in names)
        assert any(name.endswith("latest_objects.json") for name in names)


def test_debug_export_manifest_contains_diagnostics(export_tree):
    base, save_paths, now = export_tree
    zip_path, _filename, manifest = create_debug_export_zip(base_dir=base, save_paths=save_paths, now=now)
    try:
        assert manifest["duration_s"] >= 0
        assert manifest["candidates_count"] >= manifest["total_files"]
        assert isinstance(manifest["scanned_roots"], list)
        assert manifest["skipped_old_files"] >= 1
        assert manifest["excluded_files_count"] >= manifest["skipped_old_files"]
    finally:
        zip_path.unlink(missing_ok=True)


def test_debug_export_limit_exceeded_aborts_cleanly(export_tree):
    base, save_paths, now = export_tree
    import pytest
    from debug_export import ExportLimitExceeded

    with pytest.raises(ExportLimitExceeded, match="max_files=1"):
        create_debug_export_zip(base_dir=base, save_paths=save_paths, now=now, max_files=1)


def test_export_route_exception_logs_stacktrace_and_returns_json(client_with_export_data, monkeypatch, caplog):
    import logging
    import debug_export

    monkeypatch.setattr("auth.get_current_user", lambda: {"role": "admin", "sub": "1"})

    def boom(**_kwargs):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(debug_export, "create_debug_export_zip", boom)
    caplog.set_level(logging.INFO, logger="app")

    resp = client_with_export_data.get("/api/admin/export/last-24h.zip")

    assert resp.status_code == 500
    payload = resp.get_json()
    assert payload["type"] == "RuntimeError"
    assert "kaputt" in payload["error"]
    assert "[ADMIN-EXPORT] start" in caplog.text
    assert "[ADMIN-EXPORT] failed" in caplog.text
    assert "Traceback" in caplog.text


def test_export_route_success_logs_start_and_success(client_with_export_data, monkeypatch, caplog):
    import logging

    monkeypatch.setattr("auth.get_current_user", lambda: {"role": "admin", "sub": "1"})
    caplog.set_level(logging.INFO, logger="app")

    resp = client_with_export_data.get("/api/admin/export/last-24h.zip")
    try:
        assert resp.status_code == 200
        assert "[ADMIN-EXPORT] start" in caplog.text
        assert "[ADMIN-EXPORT] zip_created" in caplog.text
        assert "manifest_total_files=" in caplog.text
    finally:
        resp.close()


def test_export_route_does_not_use_read_bytes():
    source = Path("app.py").read_text(encoding="utf-8")
    route_start = source.index('def api_admin_export_last_24h_zip():')
    route_end = source.index('@app.route("/api/download/logs")', route_start)
    route_source = source[route_start:route_end]

    assert ".read_bytes(" not in route_source
    assert "send_file(" in route_source
    assert "call_on_close" in route_source


def test_download_logs_contains_nginx_section_or_not_readable_message(client_with_export_data, monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "_journalctl_unit_lines", lambda unit, limit=500: [f"{unit} log"])
    resp = client_with_export_data.get("/api/download/logs")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "=== nginx error (/var/log/nginx/error.log) ===" in text
    assert "=== nginx access (/var/log/nginx/access.log) ===" in text
    assert ("[nginx] /var/log/nginx/error.log nicht lesbar" in text) or ("=== nginx error" in text and len(text) > 0)


def test_debug_export_includes_api_logs_and_manifest_metadata(export_tree, monkeypatch):
    import debug_export

    base, save_paths, now = export_tree

    def fake_journal(unit, window_start):
        return f"{unit} token=secret log\n", True

    def fake_nginx(path, *args):
        return f"{path} error 502\n", True

    monkeypatch.setattr(debug_export, "_journalctl_export_text", fake_journal)
    monkeypatch.setattr(debug_export, "_read_nginx_log_for_export", fake_nginx)

    zip_path, _filename, manifest = create_debug_export_zip(base_dir=base, save_paths=save_paths, now=now)
    try:
        names, zip_manifest, contents = _zip_names_and_manifest(zip_path)
        assert manifest["api_logs_included"] is True
        assert zip_manifest["api_logs_included"] is True
        assert zip_manifest["api_logs_files_count"] >= 5
        assert zip_manifest["nginx_logs_included"] is True
        assert "api_logs" not in zip_manifest["missing_expected_sections"]
        assert any("/api_logs/journal/wetterprojekt.service.log" in name for name in names)
        assert any("/api_logs/nginx/nginx_error.log" in name for name in names)
        redacted_text = b"\n".join(contents.values()).decode("utf-8", errors="ignore")
        assert "secret" not in redacted_text
        assert "***REDACTED***" in redacted_text
    finally:
        zip_path.unlink(missing_ok=True)


def test_debug_export_notes_unreadable_nginx_logs(export_tree, monkeypatch):
    import debug_export

    base, save_paths, now = export_tree
    monkeypatch.setattr(debug_export, "_journalctl_export_text", lambda unit, window_start: (f"{unit}\n", True))
    monkeypatch.setattr(debug_export, "_read_nginx_log_for_export", lambda path, *args: (f"[nginx] {path} nicht lesbar\n", False))

    zip_path, _filename, manifest = create_debug_export_zip(base_dir=base, save_paths=save_paths, now=now)
    try:
        names, zip_manifest, contents = _zip_names_and_manifest(zip_path)
        assert zip_manifest["api_logs_included"] is True
        assert zip_manifest["nginx_logs_included"] is False
        assert "/var/log/nginx/error.log" in zip_manifest["api_logs_unavailable_reason"]
        nginx_error_name = next(name for name in names if name.endswith("/api_logs/nginx/nginx_error.log"))
        assert "nicht lesbar" in contents[nginx_error_name].decode("utf-8")
        assert "api_logs" not in zip_manifest["missing_expected_sections"]
    finally:
        zip_path.unlink(missing_ok=True)


def test_export_route_streams_file_path_and_cleans_after_close(client_with_export_data, monkeypatch, tmp_path):
    import app as app_module

    monkeypatch.setattr("auth.get_current_user", lambda: {"role": "admin", "sub": "1"})
    zip_path = tmp_path / "streamed.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("manifest.json", "{}")

    monkeypatch.setattr(app_module.debug_export, "create_debug_export_zip", lambda **kwargs: (zip_path, "streamed.zip", {"total_files": 1}))
    calls = {}
    real_send_file = app_module.send_file

    def spy_send_file(path, **kwargs):
        calls["path"] = path
        calls["kwargs"] = kwargs
        return real_send_file(path, **kwargs)

    monkeypatch.setattr(app_module, "send_file", spy_send_file)
    resp = client_with_export_data.get("/api/admin/export/last-24h.zip")
    assert resp.status_code == 200
    assert calls["path"] == zip_path
    assert calls["kwargs"]["mimetype"] == "application/zip"
    assert calls["kwargs"]["as_attachment"] is True
    assert calls["kwargs"]["download_name"] == "streamed.zip"
    assert zip_path.exists()
    resp.close()
    assert not zip_path.exists()


def test_export_route_source_uses_no_zip_bytesio_delivery():
    source = Path("app.py").read_text(encoding="utf-8")
    route_start = source.index('def api_admin_export_last_24h_zip():')
    route_end = source.index('@app.route("/api/download/logs")', route_start)
    route_source = source[route_start:route_end]
    assert "Path(zip_path).read_bytes" not in route_source
    assert "io.BytesIO" not in route_source
    assert "send_file(\n            zip_path" in route_source


def test_api_logs_limits_and_truncation_marker(client_with_export_data, monkeypatch):
    import app as app_module

    huge = "\n".join(f"line-{i}" for i in range(20))
    monkeypatch.setattr(app_module.subprocess, "run", lambda *args, **kwargs: type("R", (), {"returncode": 0, "stdout": huge, "stderr": ""})())
    monkeypatch.setattr(app_module, "_tail_readable_file_lines", lambda *args, **kwargs: ["nginx"])

    resp = client_with_export_data.get("/api/logs?lines=5&max_bytes=1024")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["limits"]["lines"] == 5
    assert payload["wetterprojekt"][0].startswith("[TRUNCATED]")
    assert len(payload["wetterprojekt"]) == 6


def test_api_logs_source_error_does_not_abort_route(client_with_export_data, monkeypatch):
    import app as app_module

    def fail(*args, **kwargs):
        raise RuntimeError("journal kaputt")

    monkeypatch.setattr(app_module, "_journalctl_unit_lines", fail)
    monkeypatch.setattr(app_module, "_tail_readable_file_lines", lambda *args, **kwargs: ["nginx ok"])

    resp = client_with_export_data.get("/api/logs")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert "Fehler beim Lesen" in payload["wetterprojekt"][0]
    assert payload["nginx_error"] == ["nginx ok"]


def test_api_logs_limits_do_not_change_debug_export(export_tree, monkeypatch):
    import debug_export

    base, save_paths, now = export_tree
    monkeypatch.setattr(debug_export, "_journalctl_export_text", lambda unit, window_start: ("full\n" * 2000, True))
    monkeypatch.setattr(debug_export, "_read_nginx_log_for_export", lambda path, *args: ("nginx\n" * 2000, True))

    zip_path, _filename, manifest = create_debug_export_zip(base_dir=base, save_paths=save_paths, now=now)
    try:
        names, _zip_manifest, contents = _zip_names_and_manifest(zip_path)
        journal_name = next(name for name in names if name.endswith("/api_logs/journal/wetterprojekt.service.log"))
        assert contents[journal_name].decode("utf-8").count("full") == 2000
        assert manifest["api_logs_included"] is True
    finally:
        zip_path.unlink(missing_ok=True)


def test_api_logs_then_export_succeeds_without_process_abort(client_with_export_data, monkeypatch, tmp_path):
    import app as app_module

    monkeypatch.setattr("auth.get_current_user", lambda: {"role": "admin", "sub": "1"})
    monkeypatch.setattr(app_module, "_journalctl_unit_lines", lambda *args, **kwargs: ["ok"])
    monkeypatch.setattr(app_module, "_tail_readable_file_lines", lambda *args, **kwargs: ["ok"])

    zip_path = tmp_path / "after-logs.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("manifest.json", "{}")
    monkeypatch.setattr(app_module.debug_export, "create_debug_export_zip", lambda **kwargs: (zip_path, "after-logs.zip", {"total_files": 1}))

    logs_resp = client_with_export_data.get("/api/logs")
    export_resp = client_with_export_data.get("/api/admin/export/last-24h.zip")
    try:
        assert logs_resp.status_code == 200
        assert export_resp.status_code == 200
        assert export_resp.mimetype == "application/zip"
    finally:
        export_resp.close()
