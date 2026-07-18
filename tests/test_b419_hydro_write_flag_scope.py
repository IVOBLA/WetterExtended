import json
import time

import pytest
import hydro_flood_ml as h


def _patch_eval(monkeypatch, tmp_path):
    monkeypatch.setattr(h, "HYDRO_RISK_PATH", tmp_path / "risk.json")
    monkeypatch.setattr(h, "readiness_status", lambda: {})
    monkeypatch.setattr(h, "load_active_hydro_model", lambda: {})
    monkeypatch.setattr(h, "load_q_trend_history", lambda: {})
    monkeypatch.setattr(h, "record_pending_samples", lambda *a, **k: {"pending_added": 0})
    monkeypatch.setattr(h, "materialize_pending_samples", lambda *a, **k: {"labeled_added": 0})
    monkeypatch.setattr(h, "predict_q_delta", lambda *a, **k: {"predicted_q_max_m3s": 1.0})
    monkeypatch.setattr(h, "heuristic_score", lambda row: {"flood_expected": False, "cell_diagnostics": row["cell_diagnostics"], "station_runoff_series": [{}], "model_signature": "secret"})
    monkeypatch.setattr(h, "build_feature_row", lambda *a, **k: {"station_id": "1", "cell_diagnostics": [{"cell_id": "x"}]})


@pytest.mark.parametrize("write,debug", [(False, False), (True, False), (False, True), (True, True)])
def test_write_and_debug_are_independent(monkeypatch, tmp_path, write, debug):
    _patch_eval(monkeypatch, tmp_path)
    doc = h.evaluate_live_flood_risk(stations=[{"station_id": "1"}], write=write, include_debug=debug)
    row = doc["stations"][0]
    assert ("cell_diagnostics" in row) is debug
    assert ("station_runoff_series" in row) is debug
    assert ("model_signature" in row) is debug
    assert h.HYDRO_RISK_PATH.exists() is (write and not debug)
    assert doc["payload_scope"] == ("admin_diagnostics" if debug else "public")
    if debug:
        assert doc["payload_schema_version"] == "b430_admin_diagnostics_v1"


def test_write_false_does_not_touch_cache(monkeypatch, tmp_path):
    _patch_eval(monkeypatch, tmp_path)
    h.HYDRO_RISK_PATH.write_text('{"old": true}')
    before = h.HYDRO_RISK_PATH.stat().st_mtime_ns
    time.sleep(0.001)
    h.evaluate_live_flood_risk(stations=[{"station_id": "1"}], write=False)
    assert h.HYDRO_RISK_PATH.stat().st_mtime_ns == before
    assert json.loads(h.HYDRO_RISK_PATH.read_text()) == {"old": True}


def test_diagnose_station_requests_debug(monkeypatch):
    monkeypatch.setattr(h, "load_latest_cell_frame", lambda: ([], {}))
    captured = {}
    def evaluate(**kwargs):
        captured.update(kwargs)
        return {"stations": [{"station_id": "2900158", "cell_diagnostics": []}]}
    monkeypatch.setattr(h, "evaluate_live_flood_risk", evaluate)
    h.diagnose_station("2900158")
    assert captured["write"] is False and captured["include_debug"] is True


def test_missing_payload_scope_is_error():
    with pytest.raises(ValueError, match="payload_scope"):
        h.require_public_payload_scope({"stations": []})
