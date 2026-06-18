from optical_flow_features import assign_optical_flow_to_objects


def test_optflow_sets_error_reason_for_missing_previous():
    objs = [{"id":"a","x":1,"y":1}]
    out = assign_optical_flow_to_objects(objs, "", "missing.png")
    assert out[0]["of_available"] == 0
    assert out[0]["of_error_reason"] in {"prev_radar_missing", "pysteps_or_numpy_missing"}
