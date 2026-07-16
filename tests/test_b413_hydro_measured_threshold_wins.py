import hydro_flood_ml as h


def _score(**overrides):
    row={"current_q_m3s": 11.0, "station_q_threshold_m3s": 10.0, "catchment_geometry_available": True, "precip_status": "ok"}
    row.update(overrides)
    return h.heuristic_score(row)


def test_measured_threshold_wins_without_catchment_polygon():
    sc=_score(catchment_geometry_available=False)
    assert sc["flood_expected"] is True
    assert sc["flood_status"] == "threshold_already_exceeded"
    assert "catchment_geometry_missing" in sc["warning_reasons"]
    assert sc["forecast_flood_evaluable"] is False


def test_measured_threshold_wins_with_bbox_fallback():
    sc=_score(geometry_quality="bbox_fallback")
    assert sc["flood_expected"] is True
    assert sc["flood_status"] == "threshold_already_exceeded"
    assert "geometry_fallback_not_authoritative" in sc["warning_reasons"]
    assert sc["forecast_flood_evaluable"] is False


def test_below_threshold_without_catchment_polygon_is_not_evaluable():
    sc=_score(current_q_m3s=9.0, catchment_geometry_available=False)
    assert sc["flood_expected"] is False
    assert sc["flood_evaluable"] is False
    assert sc["flood_status"] == "catchment_geometry_missing"


def test_missing_current_q_not_evaluable():
    sc=_score(current_q_m3s=None)
    assert sc["flood_status"] == "missing_current_q"
    assert sc["current_threshold_evaluable"] is False


def test_missing_threshold_not_evaluable():
    sc=_score(station_q_threshold_m3s=None)
    assert sc["flood_status"] == "missing_threshold"
    assert sc["current_threshold_evaluable"] is False
