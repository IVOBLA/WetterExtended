import hydro_flood_ml as h


def test_overlap_time_uses_effective_deduplicated_series(monkeypatch):
    # Aggregations are exposed separately; canonical feature must equal effective field.
    row={'raw_overlap_area_time_km2_min':20.0,'effective_overlap_area_time_km2_min':10.0,'overlap_area_time_km2_min':10.0}
    assert row['overlap_area_time_km2_min'] == row['effective_overlap_area_time_km2_min']
    assert row['raw_overlap_area_time_km2_min'] > row['overlap_area_time_km2_min']
