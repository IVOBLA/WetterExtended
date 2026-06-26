"""B252 — IR-Track Ausalterung bei eingefrorener Observation + Kurzintervall-Freshness."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _cell(obs_ts="2026-06-25T19:15:00Z", tiff="ir108_20260625191500.tif"):
    return {
        "lat": 46.36,
        "lon": 12.71,
        "bt_min_k": 240.0,
        "bt_mean_k": 242.0,
        "overshooting_top": 0.0,
        "area_px": 100,
        "cloud_height_m": 8225.0,
        "cloud_height_confidence": 0.35,
        "cloud_height_source": "default_fallback",
        "height_stage": "pre_cb",
        "ir_score": 0.5,
        "ir_stage": "ir_pre_cb",
        "cape": 500.0,
        "arome_li": -1.0,
        "observation_timestamp": obs_ts,
        "tiff_file": tiff,
        "source_timestamp": obs_ts,
        "timestamp_source": None,
        "availability_latency_min": None,
        "source_layer": "msg_fes:ir108",
        "scan_mode": "FES",
    }


def _state_track():
    track = _cell()
    track.update({
        "ir_id": "ir_0",
        "ir_track_id": "ir_0",
        "bt_trend_k_per_min": 0.0,
        "max_cloud_height_m": 8225.0,
        "vx_deg_min": 0.0,
        "vy_deg_min": 0.0,
        "cloud_age_min": 0.0,
        "anvil_extension_km": 10.0,
        "area_growth_px_per_min": 0.0,
        "area_growth_km2_per_min": 0.0,
        "cloud_height_trend_m_per_min": 0.0,
        "motion_quality": "tracked",
        "first_seen_observation_timestamp": "2026-06-25T19:15:00Z",
        "last_seen_observation_timestamp": "2026-06-25T19:15:00Z",
        "last_timestamp": "2026-06-25T19:15:00Z",
        "missing": 0,
        "stale_obs_cycles": 1,
        "_prev_obs_ts_b252": "2026-06-25T19:15:00Z",
        "_prev_tiff_b252": "ir108_20260625191500.tif",
        "ir_only_precursor": 1.0,
        "radar_match_ids": [],
        "first_seen_timestamp": "2026-06-25T19:15:00Z",
    })
    return track


def test_stale_obs_increments_missing_after_threshold(tmp_path, monkeypatch):
    """Nach IR_MAX_STALE_OBS_CYCLES Zyklen mit gleichem tiff/obs_ts muss missing steigen."""
    import importlib
    import ir_cell_tracking as irt

    importlib.reload(irt)
    state_file = tmp_path / "ir_track_state.json"
    state_file.write_text(json.dumps({"next_id": 1, "tracks": {"ir_0": _state_track()}}))
    monkeypatch.setattr(irt, "_SAVE_DIR", str(tmp_path))
    monkeypatch.setattr(irt, "_STATE_FILE", str(state_file))
    monkeypatch.setattr(irt, "_IR_MAX_STALE_OBS_CYCLES_DEFAULT", 2)

    active = irt.update_ir_tracking([_cell()], "2026-06-25_21-25-00")
    saved = json.loads(state_file.read_text())["tracks"]["ir_0"]

    assert active == []
    assert saved["stale_obs_cycles"] == 2
    assert saved["missing"] == 1
    assert saved["motion_quality"] == "stale_obs"


def test_neuer_tiff_resettet_stale_obs_cycles(tmp_path, monkeypatch):
    """Ein neuer tiff_file setzt stale_obs_cycles zurück."""
    import importlib
    import ir_cell_tracking as irt

    importlib.reload(irt)
    state_file = tmp_path / "ir_track_state.json"
    state_file.write_text(json.dumps({"next_id": 1, "tracks": {"ir_0": _state_track()}}))
    monkeypatch.setattr(irt, "_SAVE_DIR", str(tmp_path))
    monkeypatch.setattr(irt, "_STATE_FILE", str(state_file))

    active = irt.update_ir_tracking([_cell("2026-06-25T21:00:00Z", "ir108_20260625210000.tif")], "2026-06-25_21-00-00")
    saved = json.loads(state_file.read_text())["tracks"]["ir_0"]

    assert len(active) == 1
    assert saved["stale_obs_cycles"] == 0
    assert saved["missing"] == 0
    assert saved["motion_quality"] == "tracked"


def test_risk_watch_ignoriert_veralteten_ir_track(monkeypatch):
    """Ein IR-Track mit alter Observation darf den Kurzintervall nicht triggern."""
    import importlib
    import risk_watch as rw
    from datetime import datetime, timezone, timedelta

    importlib.reload(rw)
    monkeypatch.setattr(rw.runtime_config, "get", lambda name, default=None: {"RISK_WATCH_ENABLED": True, "IR_MAX_DATA_AGE_MIN": 30, "IR_WATCH_MIN_SCORE": 0.5, "RISK_WATCH_MIN_RISK_LEVEL": 2}.get(name, default))
    old_obs = (datetime.now(timezone.utc) - timedelta(minutes=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
    mock_get = MagicMock(return_value=None)

    result = rw.risk_watch_active(
        ir_tracks=[{"ir_only_precursor": 1.0, "ir_stage": "ir_pre_cb", "ir_score": 0.8, "observation_timestamp": old_obs}],
        data_age_min=1.0,
        http_get=mock_get,
    )

    assert result is False


def test_risk_watch_frischer_ir_track_triggert(monkeypatch):
    """Ein IR-Track mit frischer Observation soll den Kurzintervall triggern."""
    import importlib
    import risk_watch as rw
    from datetime import datetime, timezone, timedelta

    importlib.reload(rw)
    monkeypatch.setattr(rw.runtime_config, "get", lambda name, default=None: {"RISK_WATCH_ENABLED": True, "IR_MAX_DATA_AGE_MIN": 30, "IR_WATCH_MIN_SCORE": 0.5, "RISK_WATCH_MIN_RISK_LEVEL": 2}.get(name, default))
    fresh_obs = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    mock_get = MagicMock(return_value=None)

    result = rw.risk_watch_active(
        ir_tracks=[{"ir_only_precursor": 1.0, "ir_stage": "ir_pre_cb", "ir_score": 0.8, "observation_timestamp": fresh_obs}],
        data_age_min=1.0,
        http_get=mock_get,
    )

    assert result is True
