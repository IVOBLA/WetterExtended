"""
tests/test_debug_export.py

Endpunkt-Verträge des Admin-Exports + direkte debug_export-Funktionstests.

B162: Der Export baut die Volumes asynchron in einem SUBPROZESS (sonst hungerte
der synchrone >60-s-Build den systemd-Watchdog aus → SIGABRT → 502). Der Vertrag ist:
  GET /api/admin/export/last-24h/parts  → {token, status:"building"} (sofort)
  GET /api/admin/export/status?token=…  → building | ready(+parts) | error(500)
  GET /api/admin/export/last-24h.zip?token=…&part=N → fertiges Volume (send_file)
  GET /api/admin/export/last-24h.zip    (ohne token) → 400 use_parts_endpoint

subprocess.Popen wird durch Fakes ersetzt (kein echter CPU-Build, kein Netzwerk).

Ausführbar: python3 -m pytest tests/test_debug_export.py -v
"""
import json
import zipfile
from pathlib import Path

import pytest

import debug_export


def _auth(monkeypatch, role="admin"):
    # B123: before_request ruft auth.get_current_user() über Modul-Dict auf (B107).
    # app.get_current_user muss ZUSÄTZLICH gepatcht werden, damit die Route-Funktion
    # selbst den richtigen User sieht.
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
    # B162/B167: Build-Registry pro Test leeren (Isolation).
    app_module._EXPORT_BUILDS.clear()
    return app_module.app.test_client()


# ── Fake-Subprozesse ────────────────────────────────────────────────────────

class _FakeProcReady:
    """Sofort fertig (rc=0): schreibt 1 Volume + manifest.json in out_dir."""
    def __init__(self, out_dir: Path):
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
        self.pid = 1
    def poll(self):
        return 0
    def kill(self):
        pass


class _FakeProcError:
    """Fehlgeschlagen (rc=1): schreibt error.json in out_dir."""
    def __init__(self, out_dir: Path):
        (out_dir / "error.json").write_text(
            json.dumps({"status": "error", "detail": "RuntimeError: kaputt", "traceback": "…"}),
            encoding="utf-8",
        )
        self.pid = 2
    def poll(self):
        return 1
    def kill(self):
        pass


class _FakeProcBuilding:
    """Läuft noch (poll None) — für „building"/Parallel-409-Szenarien."""
    def __init__(self, out_dir: Path):
        self.pid = 3
        self.killed = False
    def poll(self):
        return None
    def kill(self):
        self.killed = True


def _patch_popen(monkeypatch, proc_cls):
    import app as app_module

    def _fake_popen(cmd, *a, **k):
        out_dir = Path(cmd[cmd.index("--out-dir") + 1])
        return proc_cls(out_dir)

    monkeypatch.setattr(app_module.subprocess, "Popen", _fake_popen)


# ── Endpunkt-Vertrag (asynchron) ─────────────────────────────────────────────

def test_export_success_returns_zip(client, monkeypatch):
    _auth(monkeypatch)
    _patch_popen(monkeypatch, _FakeProcReady)
    token = client.get("/api/admin/export/last-24h/parts").get_json()["token"]
    assert client.get(f"/api/admin/export/status?token={token}").get_json()["status"] == "ready"
    resp = client.get(f"/api/admin/export/last-24h.zip?token={token}&part=1")
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    resp.close()


def test_export_exception_returns_500(client, monkeypatch):
    _auth(monkeypatch)
    _patch_popen(monkeypatch, _FakeProcError)
    token = client.get("/api/admin/export/last-24h/parts").get_json()["token"]
    st = client.get(f"/api/admin/export/status?token={token}")
    assert st.status_code == 500
    assert st.get_json()["status"] == "error"


def test_export_does_not_crash_process(client, monkeypatch):
    # B162: /parts kehrt SOFORT zurück (Build im Subprozess) — der Admin-Prozess
    # blockiert nicht, andere Endpunkte bleiben erreichbar.
    _auth(monkeypatch)
    _patch_popen(monkeypatch, _FakeProcBuilding)
    assert client.get("/api/admin/export/last-24h/parts").get_json()["status"] == "building"
    assert client.get("/api/logs").status_code in (200, 500)


def test_tokenless_zip_returns_400(client, monkeypatch):
    _auth(monkeypatch)
    resp = client.get("/api/admin/export/last-24h.zip")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "use_parts_endpoint"


def test_parallel_export_returns_409(client, monkeypatch):
    _auth(monkeypatch)
    _patch_popen(monkeypatch, _FakeProcBuilding)  # bleibt „building"
    first = client.get("/api/admin/export/last-24h/parts")
    assert first.get_json()["status"] == "building"
    second = client.get("/api/admin/export/last-24h/parts")
    assert second.status_code == 409


def test_temp_file_cleaned_up_after_response(client, monkeypatch):
    import app as app_module
    _auth(monkeypatch)
    _patch_popen(monkeypatch, _FakeProcReady)
    token = client.get("/api/admin/export/last-24h/parts").get_json()["token"]
    client.get(f"/api/admin/export/status?token={token}")  # → ready
    out_dir = Path(app_module._EXPORT_BUILDS[token]["dir"])
    assert out_dir.exists()
    resp = client.get(f"/api/admin/export/last-24h.zip?token={token}&part=1")  # letztes Teil
    resp.close()
    assert not out_dir.exists()


def test_temp_file_cleaned_up_after_error(client, monkeypatch):
    import app as app_module
    _auth(monkeypatch)
    _patch_popen(monkeypatch, _FakeProcError)
    token = client.get("/api/admin/export/last-24h/parts").get_json()["token"]
    out_dir = Path(app_module._EXPORT_BUILDS[token]["dir"])
    st = client.get(f"/api/admin/export/status?token={token}")
    assert st.status_code == 500
    # B167: fehlgeschlagener Build-Ordner wird sofort aufgeräumt.
    assert not out_dir.exists()


# ── Auth ─────────────────────────────────────────────────────────────────────

def test_export_requires_admin_returns_401_for_unauthenticated(client, monkeypatch):
    import app as app_module
    import auth as auth_module
    monkeypatch.setattr(app_module, "get_current_user", lambda: None)
    monkeypatch.setattr(auth_module, "get_current_user", lambda: None)
    assert client.get("/api/admin/export/last-24h.zip").status_code == 401
    assert client.get("/api/admin/export/last-24h/parts").status_code == 401


def test_export_requires_admin_returns_403_for_non_admin(client, monkeypatch):
    _auth(monkeypatch, "viewer")
    assert client.get("/api/admin/export/last-24h.zip").status_code == 403
    assert client.get("/api/admin/export/last-24h/parts").status_code == 403


# ── Direkte debug_export-Funktionstests (von B162 unberührt) ─────────────────

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


def test_effective_runtime_config_redacted_in_export(tmp_path, monkeypatch):
    import runtime_config

    monkeypatch.setattr(
        runtime_config,
        "all_effective",
        lambda: {
            "GITHUB_VERIFY_CONFIG": {"token": "ghp_live_secret", "enabled": True},
            "NORMAL_SETTING": "visible",
        },
    )

    z, _, _ = debug_export.create_debug_export_zip(base_dir=tmp_path, save_paths={})
    try:
        with zipfile.ZipFile(z) as zf:
            config_name = next(n for n in zf.namelist() if n.endswith("config/effective_runtime_config.json"))
            text = zf.read(config_name).decode("utf-8")
        assert "ghp_live_secret" not in text
        assert "<REDACTED>" in text
        assert "visible" in text
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
