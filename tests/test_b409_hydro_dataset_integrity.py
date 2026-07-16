import json
from datetime import datetime, timedelta, timezone

import hydro_flood_ml as h


def test_label_without_threshold_materializes_q_targets():
    start = {"measured_at":"2026-01-01T00:00:00Z", "q_m3s": 5.0}
    future = [{"measured_at":"2026-01-01T01:00:00Z", "q_m3s": 7.0}]
    label = h._label_from_future(start, future, None)
    assert label["target_missing"] is False
    assert label["target_q_delta_m3s"] == 2.0
    assert label["target_q_max_m3s"] == 7.0
    assert label["target_q_threshold_exceeded"] is None
