"""B236 — Static-Hydro-Import laeuft im eigenen Prozess (async), Web-Worker blockiert nicht."""

import json
import os
import pytest


def test_run_build_job_writes_finished_state(tmp_path, monkeypatch):
    import hydro_static_import as hsi
    monkeypatch.setattr(hsi, "build_static_hydro", lambda static_dir=None: {
        "status": "ok", "basin_count": 3, "flowline_count": 4,
        "station_basin_count": 2, "impact_eligible_station_count": 1,
        "upstream_graph_cycle_count": 0, "topology_quality": "ok",
    })
    hsi.run_build_job(str(tmp_path))
    state = json.loads((tmp_path / "generated" / "hydro_import_job.json").read_text(encoding="utf-8"))
    assert state["status"] == "finished"
    assert state["summary"]["impact_eligible_station_count"] == 1
    assert state["finished_at"] and state["pid"] == os.getpid()


def test_run_build_job_records_failure_and_reraises(tmp_path, monkeypatch):
    import hydro_static_import as hsi
    def _boom(static_dir=None):
        raise RuntimeError("kaputt")
    monkeypatch.setattr(hsi, "build_static_hydro", _boom)
    with pytest.raises(RuntimeError):
        hsi.run_build_job(str(tmp_path))
    state = json.loads((tmp_path / "generated" / "hydro_import_job.json").read_text(encoding="utf-8"))
    assert state["status"] == "failed" and "kaputt" in state["error"]


def test_import_job_reader_idle_and_stale(tmp_path, monkeypatch):
    import app as app_module
    f = tmp_path / "hydro_import_job.json"
    monkeypatch.setattr(app_module, "_hydro_import_state_path", lambda: str(f))
    assert app_module._hydro_import_job()["status"] == "idle"
    f.write_text(json.dumps({"status": "running", "pid": 2147480000, "started_at": "x", "finished_at": None, "summary": None, "error": None}), encoding="utf-8")
    job = app_module._hydro_import_job()
    assert job["status"] == "stale" and job["alive"] is False


@pytest.fixture
def client():
    import app as app_module
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def test_import_status_is_public(client):
    assert client.get("/api/hydro/import-status").status_code == 200


def test_reload_static_spawns_and_guards_against_concurrent(client, tmp_path, monkeypatch):
    import app as app_module, auth, hydro_static_import as hsi
    monkeypatch.setattr(auth, "get_current_user", lambda: {"role": "admin"})
    f = tmp_path / "hydro_import_job.json"
    monkeypatch.setattr(app_module, "_hydro_import_state_path", lambda: str(f))
    monkeypatch.setattr(hsi, "_hydro_job_state_path", lambda static_dir=None: str(f))
    import hydro_api
    monkeypatch.setattr(hydro_api, "STATIC_GENERATED", tmp_path)

    class _FakeProc:
        def __init__(self): self.pid = os.getpid()  # lebender PID -> alive=True
    monkeypatch.setattr(app_module.subprocess, "Popen", lambda *a, **k: _FakeProc())

    r1 = client.post("/api/hydro/reload-static", json={})
    assert r1.status_code in (200, 202)
    assert r1.get_json()["data"]["status"] == "started"
    r2 = client.post("/api/hydro/reload-static", json={})
    assert r2.get_json()["data"]["status"] == "already_running"
