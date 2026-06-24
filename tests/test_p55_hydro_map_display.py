"""P55 — Hydro-Karten-Anzeige: Durchfluss-Schwellen (Anzeige-Filter + Markierung), runtime-konfigurierbar."""

import hydro_api


def _setup(monkeypatch, min_q, mark_q):
    monkeypatch.setattr(hydro_api, "_static_index", lambda: {
        "S1": {"lat": 1.0, "lon": 1.0, "station_name": "A", "impact_eligible": True},
        "S2": {"lat": 2.0, "lon": 2.0, "station_name": "B", "impact_eligible": True},
        "S3": {"lat": 3.0, "lon": 3.0, "station_name": "C", "impact_eligible": True},
    })
    monkeypatch.setattr(hydro_api, "_json", lambda path, default=None: {"stations": [
        {"station_id": "S1", "q_m3s": 2.0, "name": "A"},
        {"station_id": "S2", "q_m3s": 10.0, "name": "B"},
        {"station_id": "S3", "q_m3s": None, "name": "C"},
    ]} if "latest" in str(path) or "live" in str(path).lower() else (default if default is not None else {}))
    monkeypatch.setattr(hydro_api, "normalized_impacts", lambda *a, **k: [])
    monkeypatch.setattr(hydro_api, "enabled", lambda: True)
    cfg = {"HYDRO_STATION_OVERRIDES": {}, "HYDRO_MAP_MIN_Q_M3S": min_q, "HYDRO_MAP_MARK_Q_M3S": mark_q}
    monkeypatch.setattr(hydro_api.runtime_config, "get", lambda key, default=None: cfg.get(key, default))


def _ids(fc):
    return {f["properties"]["station_id"] for f in fc["features"]}


def test_map_view_off_shows_all_no_marked(monkeypatch):
    _setup(monkeypatch, 5.0, 8.0)
    fc = hydro_api.station_features(map_view=False)
    assert _ids(fc) == {"S1", "S2", "S3"}
    assert all("marked" not in f["properties"] for f in fc["features"])


def test_min_q_filters_low_discharge_keeps_unknown(monkeypatch):
    _setup(monkeypatch, 5.0, None)
    fc = hydro_api.station_features(map_view=True)
    assert _ids(fc) == {"S2", "S3"}


def test_mark_threshold_sets_marked_flag(monkeypatch):
    _setup(monkeypatch, 0.0, 8.0)
    fc = hydro_api.station_features(map_view=True)
    by = {f["properties"]["station_id"]: f["properties"] for f in fc["features"]}
    assert by["S2"]["marked"] is True
    assert by["S1"]["marked"] is False
    assert by["S3"]["marked"] is False


def test_maps_request_map_mode_and_render_marked():
    from pathlib import Path
    base = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages"
    for name in ("MapView.jsx", "MapFullscreen.jsx"):
        s = (base / name).read_text(encoding="utf-8")
        assert "/api/hydro/stations?map=1" in s, f"{name}: ?map=1 fehlt"
        assert "p.marked" in s, f"{name}: marked-Rendering fehlt"
