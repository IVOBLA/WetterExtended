import sys
import types


def _tracking_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "debug_utils", types.SimpleNamespace(debug_log=lambda *a, **k: None))
    sys.modules.pop("ir_cell_tracking", None)
    import ir_cell_tracking as mod
    return mod


def _cell(lat=46.0, lon=14.0, area_px=10, cloud_height_m=9000, ts="2026-06-18_00-00-00"):
    return {
        "lat": lat,
        "lon": lon,
        "bt_min_k": 210.0,
        "bt_mean_k": 220.0,
        "area_px": area_px,
        "overshooting_top": False,
        "cloud_height_m": cloud_height_m,
        "cape": 500.0,
        "arome_li": -2.0,
        "timestamp": ts,
        "tiff_file": f"{ts}.tif",
    }


def test_new_ir_track_gets_precursor_semantics(monkeypatch):
    mod = _tracking_module(monkeypatch)
    saved = []
    monkeypatch.setattr(mod, "_load_state", lambda: {"tracks": {}, "next_id": 0})
    monkeypatch.setattr(mod, "_save_state", lambda state: saved.append(state))

    tracks = mod.update_ir_tracking([_cell()], "2026-06-18_00-00-00")

    assert len(tracks) == 1
    t = tracks[0]
    assert t["_type"] == "ir_precursor_cell"
    assert t["status"] == "ir_precursor"
    assert t["radar_confirmed"] is False
    assert t["is_potential_new_cell"] is True
    assert t["display_as_precursor"] is True
    assert t["ir_only_precursor"] == 1.0


def test_existing_old_track_is_migrated(monkeypatch):
    mod = _tracking_module(monkeypatch)
    old = {"ir_id": "ir_1", "lat": 46.0, "lon": 14.0, "ir_only_precursor": 1.0, "missing": 0}
    monkeypatch.setattr(mod, "_load_state", lambda: {"tracks": {"ir_1": old}, "next_id": 2})

    tracks = mod.load_active_ir_tracks()

    assert tracks[0]["_type"] == "ir_precursor_cell"
    assert tracks[0]["status"] == "ir_precursor"
    assert tracks[0]["radar_confirmed"] is False
    assert tracks[0]["display_as_precursor"] is True


def test_mark_radar_matched_sets_confirmed_semantics(monkeypatch):
    mod = _tracking_module(monkeypatch)
    track = {"ir_id": "ir_1", "lat": 46.0, "lon": 14.0, "ir_only_precursor": 1.0}
    state = {"tracks": {"ir_1": track}, "next_id": 2}
    saved = []
    monkeypatch.setattr(mod, "_load_state", lambda: state)
    monkeypatch.setattr(mod, "_save_state", lambda state: saved.append(state))

    mod.mark_radar_matched_tracks(["ir_1"])

    assert track["status"] == "radar_confirmed"
    assert track["radar_confirmed"] is True
    assert track["is_potential_new_cell"] is False
    assert track["display_as_precursor"] is False
    assert track["ir_only_precursor"] == 0.0
    assert saved


def test_area_and_height_growth_are_computed(monkeypatch):
    mod = _tracking_module(monkeypatch)
    prev = _cell(area_px=10, cloud_height_m=8000)
    prev.update({"ir_id": "ir_1", "last_timestamp": "2026-06-18_00-00-00", "missing": 0, "ir_only_precursor": 1.0})
    state = {"tracks": {"ir_1": prev}, "next_id": 2}
    monkeypatch.setattr(mod, "_load_state", lambda: state)
    monkeypatch.setattr(mod, "_save_state", lambda state: None)

    tracks = mod.update_ir_tracking([_cell(area_px=25, cloud_height_m=9500, ts="2026-06-18_00-15-00")], "2026-06-18_00-15-00")

    assert tracks[0]["area_growth_px_per_min"] > 0
    assert tracks[0]["area_growth_km2_per_min"] > 0
    assert tracks[0]["cloud_height_trend_m_per_min"] > 0
    assert tracks[0]["motion_quality"] == "tracked"


def test_radar_confirmed_ir_not_displayed_as_precursor_payload(monkeypatch):
    import app as app_module
    import ir_cell_tracking
    import runtime_config

    monkeypatch.setattr(app_module, "_objects_for_ts", lambda ts: [])
    monkeypatch.setattr(runtime_config, "get", lambda name, default=None: default)
    monkeypatch.setattr(ir_cell_tracking, "load_active_ir_tracks", lambda: [{
        "ir_id": "ir_1", "radar_confirmed": True, "status": "radar_confirmed", "ir_only_precursor": 0.0
    }])

    resp = app_module.app.test_client().get("/api/objects?include_ir=1")
    data = resp.get_json()
    assert data[0]["_type"] == "ir_precursor_cell"
    assert data[0]["display_as_precursor"] is False
