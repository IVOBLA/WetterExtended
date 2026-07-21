"""B444: Der Eval-Status wird auch bei malformed Sample-DB ausgeliefert.

Codex-Review zu B433: /api/hydro/flood-risk/status las den cache-festen Eval-Status erst
nach flood_risk_status(), das über readiness_status() die SQLite öffnet. Bei malformed DB
warf das vorher, und _hydro_safe verschluckte den Eval-Status — genau im Störfall.
"""
import json
import sqlite3

import pytest

pytest.importorskip("flask")

import app as app_module
import hydro_flood_ml
import hydro_fetch


@pytest.fixture()
def _eval_file(tmp_path, monkeypatch):
    p = tmp_path / "hydro_flood_eval_status.json"
    p.write_text(json.dumps({
        "hydro_flood_eval_status": "error",
        "error": "DatabaseError: database disk image is malformed",
        "hydro_flood_eval_at": "2026-07-20T06:00:00Z",
    }), encoding="utf-8")
    monkeypatch.setattr(hydro_fetch, "FLOOD_EVAL_STATUS_FILE", p)
    return p


def test_eval_status_kommt_trotz_defekter_db(_eval_file, monkeypatch):
    # flood_risk_status wirft (malformed DB).
    def _boom():
        raise sqlite3.DatabaseError("database disk image is malformed")
    monkeypatch.setattr(hydro_flood_ml, "flood_risk_status", _boom)

    client = app_module.app.test_client()
    resp = client.get("/api/hydro/flood-risk/status")
    data = resp.get_json()
    payload = data.get("data") or data
    # Der Eval-Status muss enthalten sein, obwohl der DB-Status warf.
    assert payload.get("hydro_flood_eval_status") == "error"
    assert "malformed" in payload.get("error", "")
    assert "base_status_error" in payload


def test_eval_status_und_basis_bei_gesunder_db(_eval_file, monkeypatch):
    monkeypatch.setattr(hydro_flood_ml, "flood_risk_status",
                        lambda: {"status": "ok", "model_source": "ml"})
    client = app_module.app.test_client()
    resp = client.get("/api/hydro/flood-risk/status")
    payload = (resp.get_json() or {}).get("data") or resp.get_json()
    assert payload.get("hydro_flood_eval_status") == "error"
    assert payload.get("model_source") == "ml"
    assert "base_status_error" not in payload


def test_never_ran_wenn_datei_fehlt(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_fetch, "FLOOD_EVAL_STATUS_FILE", tmp_path / "fehlt.json")
    monkeypatch.setattr(hydro_flood_ml, "flood_risk_status", lambda: {"status": "ok"})
    client = app_module.app.test_client()
    resp = client.get("/api/hydro/flood-risk/status")
    payload = (resp.get_json() or {}).get("data") or resp.get_json()
    assert payload.get("hydro_flood_eval_status") == "never_ran"
