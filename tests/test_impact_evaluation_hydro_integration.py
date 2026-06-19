import sys
import types

sys.modules.setdefault("cv2", types.SimpleNamespace())
sys.modules.setdefault("geo_utils", types.SimpleNamespace(haversine_distance=lambda *args: 999.0))

import impact_evaluation


def test_impact_evaluation_continues_when_hydro_static_data_missing(monkeypatch):
    monkeypatch.setattr(impact_evaluation, "load_json_if_exists", lambda path: None)
    monkeypatch.setattr(impact_evaluation, "find_latest_ir_before", lambda ts: None)
    import hydro_impact
    monkeypatch.setenv("HYDRO_ENABLED", "true")
    monkeypatch.setattr(hydro_impact, "CATCHMENTS_PATH", hydro_impact.Path("/missing/catchments.geojson"))
    monkeypatch.setattr(hydro_impact, "NETWORK_INDEX_PATH", hydro_impact.Path("/missing/network.json"))
    objects = [{"id": 42, "lat": 46.7, "lon": 14.3}]

    impact_evaluation.evaluate_impact(objects, "2026-06-19_09-00-00")

    assert objects[0]["impact"]["hydro"] is False
    assert objects[0]["impact"]["hydro_status"] == "missing_static_data"


def test_impact_evaluation_marks_hydro_disabled(monkeypatch):
    monkeypatch.setattr(impact_evaluation, "load_json_if_exists", lambda path: None)
    monkeypatch.setattr(impact_evaluation, "find_latest_ir_before", lambda ts: None)
    monkeypatch.setenv("HYDRO_ENABLED", "false")
    objects = [{"id": 42, "lat": 46.7, "lon": 14.3}]

    impact_evaluation.evaluate_impact(objects, "2026-06-19_09-00-00")

    assert objects[0]["impact"]["hydro"] is False
    assert objects[0]["impact"]["hydro_status"] == "disabled"
