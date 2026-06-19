import json

import hydro_verification as hv


def test_measurement_gap_is_ambiguous_not_rejected(monkeypatch):
    monkeypatch.setattr(hv, "load_pending_hydro_impacts", lambda: [])
    result = hv.classify_hydro_response({"station_id": "S1", "cell_id": 1}, {"raw_data_status": "gap"})

    assert result["status"] == "ambiguous"
    assert "Messlücke" in " ".join(result["reason"])


def test_competing_cells_are_ambiguous(monkeypatch):
    event = {"event_id": "e1", "station_id": "S1", "cell_id": 1, "created_at": "2026-06-19T10:00:00Z", "estimated_lag_min": [20, 180]}
    competing = {"event_id": "e2", "station_id": "S1", "cell_id": 2, "created_at": "2026-06-19T10:30:00Z", "estimated_lag_min": [20, 180]}
    monkeypatch.setattr(hv, "load_pending_hydro_impacts", lambda: [event, competing])

    result = hv.classify_hydro_response(event, {
        "raw_data_status": "ok", "delta_q_m3s": 1.0, "relative_delta_q_pct": 80,
        "delta_w_cm": 10, "relative_delta_w_pct": 25,
    })

    assert result["status"] == "ambiguous"
    assert "konkurrierende Zellen" in " ".join(result["reason"])


def _poly(w, s, e, n):
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def _write_hydro_snapshot(path, fetched_at, station_id, q_m3s, w_cm):
    path.write_text(
        json.dumps({
            "fetched_at": fetched_at,
            "stations": [{
                "station_id": station_id,
                "measured_at": fetched_at,
                "q_m3s": q_m3s,
                "w_cm": w_cm,
                "status": "ok",
            }],
        }),
        encoding="utf-8",
    )


def test_end_to_end_competing_cells_same_catchment_stays_cautious(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    import hydro_impact

    static_dir = tmp_path / "static"
    live_dir = tmp_path / "live"
    impact_dir = tmp_path / "impact"
    static_dir.mkdir()
    live_dir.mkdir()
    impact_dir.mkdir()

    catchments_path = static_dir / "station_catchments.geojson"
    network_path = static_dir / "station_network_index.json"
    monkeypatch.setattr(hydro_impact, "SHAPELY_AVAILABLE", True)
    monkeypatch.setattr(hydro_impact, "compute_cell_catchment_overlap", lambda cell, feature: {
        "hit": True,
        "status": "ok",
        "overlap_area_km2": 6.0,
        "overlap_ratio_cell": 0.5,
        "overlap_ratio_catchment": 0.1,
        "cell_area_km2": 12.0,
        "catchment_area_km2": 60.0,
    })
    monkeypatch.setattr(hydro_impact, "CATCHMENTS_PATH", catchments_path)
    monkeypatch.setattr(hydro_impact, "NETWORK_INDEX_PATH", network_path)
    monkeypatch.setattr(hydro_impact, "IMPACT_DIR", impact_dir)
    monkeypatch.setattr(hydro_impact, "LATEST_IMPACTS_PATH", impact_dir / "latest_hydro_impacts.json")
    monkeypatch.setattr(hydro_impact, "HYDRO_IMPACT_STATE_PATH", impact_dir / "hydro_impact_state.json")
    monkeypatch.setattr(hv, "NETWORK_INDEX_PATH", network_path)
    monkeypatch.setattr(hv, "HYDRO_LIVE_DIR", live_dir)
    monkeypatch.setattr(hv, "HYDRO_VERIFICATION_PATH", impact_dir / "hydro_verifications.jsonl")
    monkeypatch.setattr(hv, "HYDRO_VERIFICATION_SUMMARY_PATH", impact_dir / "hydro_verification_summary.json")

    station_id = "PEGEL-1"
    catchment_id = "CATCH-A"
    catchments_path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "station_id": station_id,
                "station_name": "Testpegel",
                "catchment_id": catchment_id,
                "upstream_catchment_ids": [catchment_id],
            },
            "geometry": _poly(13.0, 46.0, 13.5, 46.5),
        }],
    }), encoding="utf-8")
    network_path.write_text(json.dumps({
        "by_station_id": {
            station_id: {
                "station_id": station_id,
                "enabled": True,
                "impact_eligible": True,
                "quality": "verified",
                "catchment_id": catchment_id,
                "upstream_catchment_ids": [catchment_id],
                "estimated_lag_min": [20, 180],
            }
        }
    }), encoding="utf-8")

    cells = [
        {"id": "cell-a", "status": "active", "intensity": "heavy", "duration_min": 45, "contour_geo": [[13.05, 46.05], [13.25, 46.05], [13.25, 46.25], [13.05, 46.25]]},
        {"id": "cell-b", "status": "active", "intensity": "heavy", "duration_min": 40, "contour_geo": [[13.20, 46.20], [13.40, 46.20], [13.40, 46.40], [13.20, 46.40]]},
    ]
    events = hydro_impact.evaluate_hydro_impact(cells, "2026-06-19T10:00:00Z")
    assert len(events) == 2
    assert {event["catchment_id"] for event in events} == {catchment_id}
    hydro_impact.save_hydro_impact_events(events, "2026-06-19T10:00:00Z")

    _write_hydro_snapshot(live_dir / "hydro_20260619_101000.json", "2026-06-19T10:10:00Z", station_id, 10.0, 100.0)
    _write_hydro_snapshot(live_dir / "hydro_20260619_104000.json", "2026-06-19T10:40:00Z", station_id, 14.0, 112.0)

    results = hv.verify_pending_hydro_impacts(datetime(2026, 6, 19, 13, 30, tzinfo=timezone.utc))
    assert len(results) == 2
    for result in results:
        reason_text = " ".join(result["reason"])
        interpretation = result["interpretation"].lower()
        full_text = (reason_text + " " + interpretation).lower()

        assert result["status"] == "ambiguous"
        assert result["confidence"] == "low"
        assert "competing_cells_same_catchment" in result["reason"]
        assert "uneindeutig" in interpretation or "plausibel" in interpretation
        assert "verursacht" not in full_text
        assert "eindeutig verantwortlich" not in full_text
        assert "amtliche hochwasserwarnung" not in full_text
        assert "hochwasserwarnung" not in full_text
