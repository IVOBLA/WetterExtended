import json
from pathlib import Path

import hydro_api


def _patch_station(monkeypatch, risk_path=None):
    monkeypatch.setattr(hydro_api, "HYDRO_FLOOD_RISK", risk_path or Path("/tmp/does-not-exist-p67b.json"))
    monkeypatch.setattr(hydro_api, "_static_index", lambda: {
        "S1": {"station_id": "S1", "lat": 46.0, "lon": 14.0, "impact_eligible": True, "impact_eligible_auto": True}
    })

    def fake_json(path, default):
        if path == hydro_api.LIVE_LATEST:
            return {"stations": [{"station_id": "S1", "q_m3s": 1.0}]}
        if risk_path is not None and path == risk_path:
            return json.loads(risk_path.read_text(encoding="utf-8"))
        return default

    monkeypatch.setattr(hydro_api, "_json", fake_json)
    monkeypatch.setattr(hydro_api, "normalized_impacts", lambda latest_only=False, include_disabled=False: [])
    monkeypatch.setattr(hydro_api.runtime_config, "get", lambda k, d=None: None)


def test_station_features_merges_flood_expected_true_from_valid_cache(tmp_path, monkeypatch):
    risk = tmp_path / "latest_hydro_flood_risk.json"
    risk.write_text(json.dumps({"stations": [{"station_id": "S1", "flood_expected": True}]}), encoding="utf-8")
    _patch_station(monkeypatch, risk)
    monkeypatch.setattr(hydro_api, "_is_flood_risk_cache_valid_for_live", lambda risk_doc, live: True)

    props = hydro_api.station_features()["features"][0]["properties"]

    assert props["flood_expected"] is True


def test_station_features_omits_flood_expected_from_stale_cache(tmp_path, monkeypatch):
    risk = tmp_path / "latest_hydro_flood_risk.json"
    risk.write_text(json.dumps({"stations": [{"station_id": "S1", "flood_expected": True}]}), encoding="utf-8")
    _patch_station(monkeypatch, risk)
    monkeypatch.setattr(hydro_api, "_is_flood_risk_cache_valid_for_live", lambda risk_doc, live: False)

    props = hydro_api.station_features()["features"][0]["properties"]

    assert props["flood_expected"] is None


def test_station_features_sets_flood_expected_none_without_cache(monkeypatch):
    _patch_station(monkeypatch)

    props = hydro_api.station_features()["features"][0]["properties"]

    assert props["flood_expected"] is None


def test_frontend_hydro_flood_icon_inline_svg_and_marker_usage():
    for path in (Path("frontend/src/pages/MapView.jsx"), Path("frontend/src/pages/MapFullscreen.jsx")):
        text = path.read_text(encoding="utf-8")
        assert "HYDRO_FLOOD_ICON" in text
        assert "L.divIcon" in text
        assert "<svg" in text
        assert "#dc2626" in text
        assert "<Marker" in text
        assert "icon={HYDRO_FLOOD_ICON}" in text
        assert "? (" in text
        assert "<CircleMarker" in text


def test_frontend_prevents_double_circle_and_icon_for_flood_warning():
    mv = Path("frontend/src/pages/MapView.jsx").read_text(encoding="utf-8")
    mf = Path("frontend/src/pages/MapFullscreen.jsx").read_text(encoding="utf-8")

    for text in (mv, mf):
        assert "const hasFloodWarning = flood.flood_expected === true || p.flood_expected === true" in text
        assert "{hasFloodWarning ? (" in text
        assert ") : (" in text
        assert "</Marker>" in text
        assert "</CircleMarker>" in text


def test_no_new_asset_file_required_for_hydro_flood_icon():
    asset_refs = [
        "hydro-flood-icon.png",
        "hydro-flood-icon.svg",
        "flood-icon.png",
        "flood-icon.svg",
    ]
    for ref in asset_refs:
        assert not Path(ref).exists()
    for path in (Path("frontend/src/pages/MapView.jsx"), Path("frontend/src/pages/MapFullscreen.jsx")):
        text = path.read_text(encoding="utf-8")
        assert all(ref not in text for ref in asset_refs)
