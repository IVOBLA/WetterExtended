import hydro_flood_ml as h

BASE = {"id":"C", "contour_geo":[[0,0],[0.1,0],[0.1,0.1],[0,0.1],[0,0]], "lat":0.05, "lon":0.05}

def test_hydro_relevant_cell_status_filter():
    assert h.is_hydro_relevant_cell(BASE.copy()) is True
    for key, val in [("inactive", True), ("expired", True), ("tracking_state", "inactive_rain"), ("silent_tracking", True), ("missing", 1)]:
        c = BASE.copy(); c[key] = val
        assert h.is_hydro_relevant_cell(c) is False
    c = BASE.copy(); c.update({"missing": 2, "tracking_state": "reactivated"})
    assert h.is_hydro_relevant_cell(c) is True
