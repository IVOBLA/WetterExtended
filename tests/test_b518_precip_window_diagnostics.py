"""B518 — Persistenz der Niederschlagsfenster-Diagnosedaten."""
import json
import hydro_flood_ml as h


def _patch_eval(monkeypatch, tmp_path, *, row_extra=None):
    monkeypatch.setattr(h, "HYDRO_RISK_PATH", tmp_path / "risk.json")
    monkeypatch.setattr(h, "HYDRO_PRECIP_WINDOW_DIAG_PATH", tmp_path / "precip_window_diagnostics.json")
    monkeypatch.setattr(h, "readiness_status", lambda: {})
    monkeypatch.setattr(h, "load_active_hydro_model", lambda: {})
    monkeypatch.setattr(h, "load_q_trend_history", lambda: {})
    monkeypatch.setattr(h, "record_pending_samples", lambda *a, **k: {"pending_added": 0})
    monkeypatch.setattr(h, "materialize_pending_samples", lambda *a, **k: {"labeled_added": 0})
    monkeypatch.setattr(h, "predict_q_delta", lambda *a, **k: {"predicted_q_max_m3s": 1.0})
    monkeypatch.setattr(h, "heuristic_score", lambda row: {"flood_expected": False})
    row = {"station_id": "1", "cell_diagnostics": [], "observed_precip_available": True,
           "observed_precip_used_in_forecast": False,
           "observed_precip_rejection_reason": "measurement_window_overlap",
           "precip_window_overlap_min": 7.5, "precip_window_gap_min": 0.0}
    if row_extra:
        row.update(row_extra)
    monkeypatch.setattr(h, "build_feature_row", lambda *a, **k: dict(row))


def test_precip_window_diagnostics_written_on_regular_write_cycle(monkeypatch, tmp_path):
    _patch_eval(monkeypatch, tmp_path)
    h.evaluate_live_flood_risk(stations=[{"station_id": "1"}], write=True, include_debug=False)
    doc = json.loads(h.HYDRO_PRECIP_WINDOW_DIAG_PATH.read_text(encoding="utf-8"))
    assert doc["payload_scope"] == "admin_diagnostics"
    row = doc["stations"][0]
    assert (row["station_id"], row["observed_precip_rejection_reason"],
            row["precip_window_overlap_min"], row["precip_window_gap_min"]) == (
                "1", "measurement_window_overlap", 7.5, 0.0)


def test_precip_window_diagnostics_not_written_when_write_false(monkeypatch, tmp_path):
    _patch_eval(monkeypatch, tmp_path)
    h.evaluate_live_flood_risk(stations=[{"station_id": "1"}], write=False, include_debug=False)
    assert not h.HYDRO_PRECIP_WINDOW_DIAG_PATH.exists()


def test_precip_window_diagnostics_not_written_in_debug_mode(monkeypatch, tmp_path):
    _patch_eval(monkeypatch, tmp_path)
    h.evaluate_live_flood_risk(stations=[{"station_id": "1"}], write=False, include_debug=True)
    assert not h.HYDRO_PRECIP_WINDOW_DIAG_PATH.exists()


def test_precip_window_diagnostics_does_not_break_public_payload(monkeypatch, tmp_path):
    _patch_eval(monkeypatch, tmp_path)
    doc = h.evaluate_live_flood_risk(stations=[{"station_id": "1"}], write=True, include_debug=False)
    row = doc["stations"][0]
    assert not {"observed_precip_rejection_reason", "precip_window_overlap_min", "precip_window_gap_min"} & row.keys()


def test_precip_window_diagnostics_write_failure_does_not_break_main_flow(monkeypatch, tmp_path):
    _patch_eval(monkeypatch, tmp_path)
    original = h._atomic_json
    def selective(path, payload):
        if path == h.HYDRO_PRECIP_WINDOW_DIAG_PATH:
            raise OSError("Platte voll")
        return original(path, payload)
    monkeypatch.setattr(h, "_atomic_json", selective)
    doc = h.evaluate_live_flood_risk(stations=[{"station_id": "1"}], write=True, include_debug=False)
    assert doc["status"] == "ok" and doc["stations"][0]["station_id"] == "1"


def test_precip_window_diagnostics_covers_multiple_stations(monkeypatch, tmp_path):
    _patch_eval(monkeypatch, tmp_path)
    monkeypatch.setattr(h, "build_feature_row", lambda st, **k: {
        "station_id": st["station_id"], "cell_diagnostics": [],
        "observed_precip_rejection_reason": None, "precip_window_overlap_min": 0.0,
        "precip_window_gap_min": 3.0})
    h.evaluate_live_flood_risk(stations=[{"station_id": "1"}, {"station_id": "2"}], write=True, include_debug=False)
    doc = json.loads(h.HYDRO_PRECIP_WINDOW_DIAG_PATH.read_text(encoding="utf-8"))
    assert {r["station_id"] for r in doc["stations"]} == {"1", "2"}
