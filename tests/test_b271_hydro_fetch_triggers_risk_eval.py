"""B271 — Flood-Risk/Trend-Cache wurde nie aktualisiert, wenn niemand
MapView.jsx (und damit /api/hydro/flood-risk) geöffnet hatte. Live auf der
Pi verifiziert: latest_hydro_flood_risk.json existierte nach mehreren
Betriebsstunden überhaupt nicht. Fix: evaluate_live_flood_risk() wird jetzt
direkt im Hydro-Fetch-Erfolgspfad ausgelöst (gleiche Stelle wie
append_hydro_history()), unabhängig von jeder UI-Seite."""
import sys
import types

import hydro_fetch


def _install_fake_debug_utils(monkeypatch):
    module = types.SimpleNamespace(
        log_api_call=lambda *a, **k: None,
        log_api_failure=lambda *a, **k: None,
        debug_log=lambda *a, **k: None,
    )
    monkeypatch.setitem(sys.modules, "debug_utils", module)


def _install_fake_http_retry(monkeypatch, func):
    monkeypatch.setitem(sys.modules, "http_retry", types.SimpleNamespace(retry_get=func))


def test_successful_fetch_triggers_flood_risk_evaluation(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_fetch, "_LIVE_DIR", tmp_path)
    monkeypatch.setattr(hydro_fetch, "LATEST_FILE", tmp_path / "latest_hydro.json")
    monkeypatch.setattr(hydro_fetch, "STATUS_FILE", tmp_path / "hydro_status.json")
    monkeypatch.setattr(hydro_fetch, "FLOOD_EVAL_STATUS_FILE", tmp_path / "hydro_flood_eval_status.json")

    class Response:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self):
            return {"stations": [{"id": "A", "name": "A", "lat": 46.7, "lon": 14.0, "q": 1.5}]}

    _install_fake_http_retry(monkeypatch, lambda *a, **k: Response())
    _install_fake_debug_utils(monkeypatch)

    calls = []
    import hydro_flood_ml
    monkeypatch.setattr(hydro_flood_ml, "load_latest_cell_frame", lambda: ([{}], {"status": "ok"}))

    def _evaluate(**kwargs):
        calls.append(kwargs)
        return {"stations": []}

    monkeypatch.setattr(hydro_flood_ml, "evaluate_live_flood_risk", _evaluate)

    result = hydro_fetch.fetch_hydro_live(force=True)

    assert result["status"]["ok"] is True
    assert len(calls) == 1, "evaluate_live_flood_risk() wurde nicht beim erfolgreichen Fetch ausgelöst"
    assert calls[0].get("live", {}).get("fetched_at") == result["fetched_at"]
    assert [s["station_id"] for s in calls[0].get("live", {}).get("stations") or []] == [
        s["station_id"] for s in result["stations"]
    ]


def test_flood_risk_evaluation_failure_does_not_break_fetch(tmp_path, monkeypatch):
    """Ein Fehler in der Flood-Risk-Auswertung darf den Hydro-Fetch selbst
    nicht zum Absturz bringen (gleiche Robustheit wie append_hydro_history)."""
    monkeypatch.setattr(hydro_fetch, "_LIVE_DIR", tmp_path)
    monkeypatch.setattr(hydro_fetch, "LATEST_FILE", tmp_path / "latest_hydro.json")
    monkeypatch.setattr(hydro_fetch, "STATUS_FILE", tmp_path / "hydro_status.json")
    monkeypatch.setattr(hydro_fetch, "FLOOD_EVAL_STATUS_FILE", tmp_path / "hydro_flood_eval_status.json")

    class Response:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self):
            return {"stations": [{"id": "A", "name": "A", "lat": 46.7, "lon": 14.0, "q": 1.5}]}

    _install_fake_http_retry(monkeypatch, lambda *a, **k: Response())
    _install_fake_debug_utils(monkeypatch)

    import hydro_flood_ml
    monkeypatch.setattr(hydro_flood_ml, "load_latest_cell_frame", lambda: ([{}], {"status": "ok"}))

    def _boom(**kwargs):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(hydro_flood_ml, "evaluate_live_flood_risk", _boom)

    result = hydro_fetch.fetch_hydro_live(force=True)
    assert result["status"]["ok"] is True
    assert (tmp_path / "latest_hydro.json").exists()
