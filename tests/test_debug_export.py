import io
import json
import time
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest

import debug_export


def _auth(monkeypatch, role="admin"):
    import app as app_module
    monkeypatch.setattr(app_module, "get_current_user", lambda: {"role": role, "sub": "1"})


@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("flask")
    import app as app_module
    monkeypatch.setitem(app_module.SAVE_PATHS, "objects", str(tmp_path / "objects"))
    monkeypatch.setitem(app_module.SAVE_PATHS, "evaluation", str(tmp_path / "evaluation"))
    (tmp_path / "objects").mkdir()
    (tmp_path / "evaluation").mkdir()
    app_module.app.config.update(TESTING=True, DEBUG_EXPORT_BASE_DIR=str(tmp_path))
    return app_module.app.test_client()


def test_export_success_returns_zip(client, monkeypatch, tmp_path):
    _auth(monkeypatch)
    def fake(**kwargs):
        path = Path(kwargs["tmp_path"])
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("dummy.txt", "ok")
        return path, "x.zip", {"total_files": 1}
    monkeypatch.setattr(debug_export, "create_debug_export_zip", fake)
    resp = client.get("/api/admin/export/last-24h.zip")
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"


def test_export_limit_exceeded_returns_413(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(debug_export, "create_debug_export_zip", Mock(side_effect=debug_export.ExportLimitExceeded("zu groß")))
    resp = client.get("/api/admin/export/last-24h.zip")
    assert resp.status_code == 413
    assert resp.get_json()["error"] == "export_too_large"


def test_export_exception_returns_500(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(debug_export, "create_debug_export_zip", Mock(side_effect=RuntimeError("kaputt")))
    resp = client.get("/api/admin/export/last-24h.zip")
    assert resp.status_code == 500
    assert resp.get_json()["error"] == "export_failed"


def test_export_does_not_crash_process(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(debug_export, "create_debug_export_zip", Mock(side_effect=RuntimeError("kaputt")))
    assert client.get("/api/admin/export/last-24h.zip").status_code == 500
    assert client.get("/api/logs").status_code in (200, 500)


def test_export_requires_admin_returns_401_for_unauthenticated(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "get_current_user", lambda: None)
    assert client.get("/api/admin/export/last-24h.zip").status_code == 401


def test_export_requires_admin_returns_403_for_non_admin(client, monkeypatch):
    _auth(monkeypatch, "viewer")
    assert client.get("/api/admin/export/last-24h.zip").status_code == 403


def test_parallel_export_returns_409(client, monkeypatch):
    _auth(monkeypatch)
    def slow(**kwargs):
        time.sleep(0.2)
        path = Path(kwargs["tmp_path"])
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("dummy.txt", "ok")
        return path, "x.zip", {}
    monkeypatch.setattr(debug_export, "create_debug_export_zip", slow)
    import threading
    results = []
    t = threading.Thread(target=lambda: results.append(client.get("/api/admin/export/last-24h.zip").status_code))
    t.start(); time.sleep(0.05)
    second = client.get("/api/admin/export/last-24h.zip").status_code
    t.join()
    assert second == 409 or 409 in results


def test_temp_file_cleaned_up_after_response(client, monkeypatch):
    _auth(monkeypatch)
    seen = {}
    def fake(**kwargs):
        path = Path(kwargs["tmp_path"]); seen["path"] = path
        with zipfile.ZipFile(path, "w") as zf: zf.writestr("x", "y")
        return path, "x.zip", {}
    monkeypatch.setattr(debug_export, "create_debug_export_zip", fake)
    resp = client.get("/api/admin/export/last-24h.zip")
    resp.close()
    assert not seen["path"].exists()


def test_temp_file_cleaned_up_after_error(client, monkeypatch):
    _auth(monkeypatch)
    created = []
    orig = debug_export.create_debug_export_zip
    def boom(**kwargs):
        created.append(Path(kwargs["tmp_path"])); raise RuntimeError("x")
    monkeypatch.setattr(debug_export, "create_debug_export_zip", boom)
    assert client.get("/api/admin/export/last-24h.zip").status_code == 500
    assert created and not created[0].exists()


def test_old_zip_not_included_in_export(tmp_path):
    (tmp_path / "debug_old.zip").write_bytes(b"old")
    (tmp_path / "data").mkdir(); (tmp_path / "data" / "debug_old.zip").write_bytes(b"old")
    z, _, _ = debug_export.create_debug_export_zip(base_dir=tmp_path, save_paths={}, now=None)
    try:
        with zipfile.ZipFile(z) as zf:
            assert not any(n.endswith("debug_old.zip") for n in zf.namelist())
    finally:
        z.unlink(missing_ok=True)


def test_secrets_redacted_in_export(tmp_path):
    (tmp_path / ".env").write_text("SMTP_PASS=geheim\n", encoding="utf-8")
    z, _, _ = debug_export.create_debug_export_zip(base_dir=tmp_path, save_paths={})
    try:
        data = b"\n".join(zipfile.ZipFile(z).read(n) for n in zipfile.ZipFile(z).namelist())
        text = data.decode("utf-8", "ignore")
        assert "geheim" not in text
        assert "<REDACTED>" in text
    finally:
        z.unlink(missing_ok=True)


def test_missing_log_source_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(debug_export, "_read_nginx_log_for_export", lambda p, *a: (f"source_unavailable: {p}\n", False))
    z, _, _ = debug_export.create_debug_export_zip(base_dir=tmp_path, save_paths={})
    try:
        text = b"\n".join(zipfile.ZipFile(z).read(n) for n in zipfile.ZipFile(z).namelist()).decode("utf-8", "ignore")
        assert "source_unavailable" in text
    finally:
        z.unlink(missing_ok=True)
