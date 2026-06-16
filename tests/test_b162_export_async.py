"""
tests/test_b162_export_async.py

B162: Der Admin-Export baut nicht mehr synchron im Request (das hungerte den
systemd-Watchdog aus → SIGABRT → 502), sondern asynchron in einem Subprozess.
/parts liefert sofort {token, status:"building"}; /status pollt; der Download
liefert das fertige Volume.

Die echte subprocess.Popen wird durch ein Fake ersetzt, das den Build sofort als
"fertig" markiert (manifest.json schreiben). Kein echter CPU-Build, kein Netzwerk.

Ausführbar: python3 -m pytest tests/test_b162_export_async.py -v
"""
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
    # Build-Registry pro Test leeren.
    app_module._EXPORT_BUILDS.clear()
    return app_module.app.test_client()


class _FakeProc:
    """Simuliert einen sofort beendeten Build-Subprozess (rc=0)."""

    def __init__(self, out_dir: Path):
        self._out_dir = out_dir
        # Ein fertiges Volume + manifest.json ablegen.
        part = out_dir / "wetterextended_debug1.zip"
        with zipfile.ZipFile(part, "w") as zf:
            zf.writestr("dummy.txt", "ok")
        (out_dir / "manifest.json").write_text(
            json.dumps({
                "status": "ready",
                "parts": [{"index": 1, "filename": part.name, "bytes": part.stat().st_size}],
                "manifest": {"total_files": 1},
            }),
            encoding="utf-8",
        )
        self.pid = 4242

    def poll(self):
        return 0  # sofort fertig

    def kill(self):
        pass


def _patch_popen(monkeypatch):
    """Ersetzt subprocess.Popen im app-Modul durch ein Fake, das out_dir aus argv liest."""
    import app as app_module

    def _fake_popen(cmd, *a, **k):
        out_dir = Path(cmd[cmd.index("--out-dir") + 1])
        # stdout-Filehandle aus kwargs sauber schließen lassen (wie echtes Popen)
        return _FakeProc(out_dir)

    monkeypatch.setattr(app_module.subprocess, "Popen", _fake_popen)


def test_parts_returns_token_building_immediately(client, monkeypatch):
    _auth(monkeypatch)
    _patch_popen(monkeypatch)
    resp = client.get("/api/admin/export/last-24h/parts")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "building"
    assert data["token"]


def test_status_reports_ready_and_parts(client, monkeypatch):
    _auth(monkeypatch)
    _patch_popen(monkeypatch)
    token = client.get("/api/admin/export/last-24h/parts").get_json()["token"]
    st = client.get(f"/api/admin/export/status?token={token}").get_json()
    assert st["status"] == "ready"
    assert st["part_count"] == 1
    assert st["parts"][0]["filename"].endswith(".zip")


def test_download_part_after_ready(client, monkeypatch):
    _auth(monkeypatch)
    _patch_popen(monkeypatch)
    token = client.get("/api/admin/export/last-24h/parts").get_json()["token"]
    client.get(f"/api/admin/export/status?token={token}")  # → ready
    resp = client.get(f"/api/admin/export/last-24h.zip?token={token}&part=1")
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    resp.close()


def test_tokenless_zip_returns_400_no_sync_build(client, monkeypatch):
    _auth(monkeypatch)
    _patch_popen(monkeypatch)
    resp = client.get("/api/admin/export/last-24h.zip")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "use_parts_endpoint"


def test_status_requires_token(client, monkeypatch):
    _auth(monkeypatch)
    resp = client.get("/api/admin/export/status")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "missing_token"


def test_status_unknown_token_410(client, monkeypatch):
    _auth(monkeypatch)
    resp = client.get("/api/admin/export/status?token=does-not-exist")
    assert resp.status_code == 410


def test_export_requires_admin(client, monkeypatch):
    _auth(monkeypatch, "viewer")
    assert client.get("/api/admin/export/last-24h/parts").status_code == 403
    assert client.get("/api/admin/export/status?token=x").status_code == 403
