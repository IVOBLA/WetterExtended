from prediction import _append_kinematic


def _obj():
    return {"id":"x","x":0,"y":0,"lat":46.0,"lon":14.0,"vx":0,"vy":0,"history":[
        {"timestamp":"2026-06-18_00-00-00","x":0,"y":0},
        {"timestamp":"2026-06-18_00-05-00","x":5,"y":0},
        {"timestamp":"2026-06-18_00-10-00","x":10,"y":0},
    ]}


def test_ewma_before_kalman_only():
    obj = _obj(); obj["of_available"] = 0
    forecasts = {h: [] for h in [10,20,30,40,60]}
    _append_kinematic(obj, forecasts)
    assert obj["kinematic_source"].startswith("ewma")
    assert obj["forecast_displacement_km_10"] > 0
    assert obj["kinematic_source"] != "kalman_only"


def test_optflow_has_priority():
    obj = _obj(); obj["of_available"] = 1; obj["of_vx"] = 10; obj["of_vy"] = 0
    forecasts = {h: [] for h in [10,20,30,40,60]}
    _append_kinematic(obj, forecasts)
    assert obj["kinematic_source"].startswith("optflow")
    assert obj["kinematic_vx"] > 1.5
