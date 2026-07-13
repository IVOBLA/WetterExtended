"""B350: Der zuletzt erstellte Export wird persistiert und ist auf der
Logs-Seite jederzeit ohne neuen Build abrufbar."""
import json
import zipfile
from pathlib import Path

import pytest


def _auth(monkeypatch, role="admin"):
    import app as app_module
    import auth as auth_module
    user = {"role": role, "sub": "1"}
    monkeypatch.setattr(app_module, "get_current_user", lambda: user)
    monkeypatch.setattr(auth_module, "get_current_user", lambda: user)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("flask")
    import app as app_module
    monkeypatch.setitem(app_module.SAVE_PATHS, "objects", str(tmp_path / "objects"))
    monkeypatch.setitem(app_module.SAVE_PATHS, "evaluation", str(tmp_path / "evaluation"))
    (tmp_path / "objects").mkdir()
    (tmp_path / "evaluation").mkdir()
    app_module.app.config.update(TESTING=True, DEBUG_EXPORT_BASE_DIR=str(tmp_path))
    app_module._EXPORT_BUILDS.clear()
    return app_module.app.test_client()


class _FakeProc:
    def __init__(self, out_dir: Path):
        self._out_dir = out_dir
        part = out_dir / "wetterextended_debug1.zip"
        with zipfile.ZipFile(part, "w") as zf:
            zf.writestr("dummy.txt", "ok")
        (out_dir / "manifest.json").write_text(
            json.dumps({
                "status": "ready",
                "parts": [{"index": 1, "filename": part.name, "bytes": part.stat().st_size}],
                "manifest": {"total_files": 1, "created_at": "2026-07-13T06:00:00+00:00", "export_reason": "last_24h_debug_run"},
            }),
            encoding="utf-8",
        )
        self.pid = 4242

    def poll(self):
        return 0

    def kill(self):
        pass


def _patch_popen(monkeypatch):
    import app as app_module

    def _fake_popen(cmd, *a, **k):
        out_dir = Path(cmd[cmd.index("--out-dir") + 1])
        return _FakeProc(out_dir)

    monkeypatch.setattr(app_module.subprocess, "Popen", _fake_popen)


def _run_build_to_ready(client, monkeypatch):
    token = client.get("/api/admin/export/last-24h/parts").get_json()["token"]
    st = client.get(f"/api/admin/export/status?token={token}").get_json()
    assert st["status"] == "ready"
    return token


def test_meta_unavailable_before_any_build(client, monkeypatch):
    _auth(monkeypatch)
    resp = client.get("/api/admin/export/latest/meta")
    assert resp.status_code == 200
    assert resp.get_json()["available"] is False


def test_build_persists_latest_export_meta(client, monkeypatch):
    _auth(monkeypatch)
    _patch_popen(monkeypatch)
    _run_build_to_ready(client, monkeypatch)
    resp = client.get("/api/admin/export/latest/meta")
    data = resp.get_json()
    assert data["available"] is True
    assert data["part_count"] == 1
    assert data["part_files"][0].endswith(".zip")


def test_latest_zip_downloads_persisted_part_without_new_build(client, monkeypatch):
    _auth(monkeypatch)
    _patch_popen(monkeypatch)
    _run_build_to_ready(client, monkeypatch)
    resp = client.get("/api/admin/export/latest.zip?part=1")
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    resp.close()


def test_latest_zip_survives_temp_build_cleanup(client, monkeypatch, tmp_path):
    """Kernpunkt B350: auch nachdem der urspruengliche Build-Temp-Ordner weg
    ist, muss der persistierte Export weiterhin abrufbar sein."""
    _auth(monkeypatch)
    _patch_popen(monkeypatch)
    import app as app_module
    token = _run_build_to_ready(client, monkeypatch)
    info = app_module._EXPORT_BUILDS.get(token)
    if info:
        import shutil
        shutil.rmtree(info["dir"], ignore_errors=True)
    resp = client.get("/api/admin/export/latest.zip?part=1")
    assert resp.status_code == 200
    resp.close()


def test_latest_zip_invalid_part_404(client, monkeypatch):
    _auth(monkeypatch)
    _patch_popen(monkeypatch)
    _run_build_to_ready(client, monkeypatch)
    resp = client.get("/api/admin/export/latest.zip?part=99")
    assert resp.status_code == 404


def test_latest_zip_no_export_yet_404(client, monkeypatch):
    _auth(monkeypatch)
    resp = client.get("/api/admin/export/latest.zip?part=1")
    assert resp.status_code == 404


def test_latest_meta_requires_admin(client, monkeypatch):
    _auth(monkeypatch, "viewer")
    resp = client.get("/api/admin/export/latest/meta")
    assert resp.status_code == 403


def test_latest_zip_requires_admin(client, monkeypatch):
    _auth(monkeypatch, "viewer")
    resp = client.get("/api/admin/export/latest.zip?part=1")
    assert resp.status_code == 403
