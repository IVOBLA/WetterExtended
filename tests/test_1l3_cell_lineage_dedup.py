import importlib
import zipfile
from pathlib import Path

import pytest

from cell_lineage_dedup import dedupe_ir_precursors_for_payload

try:
    from kmz_export import save_forecast_as_kmz
except ModuleNotFoundError as exc:
    if exc.name != "simplekml":
        raise
    save_forecast_as_kmz = None


CID = "WX-20260618-0001"


def _radar(cell_id=CID):
    return {"id": "radar_1", "cell_id": cell_id, "lat": 46.6, "lon": 14.3}


def _ir(cell_id=CID, **extra):
    data = {
        "ir_id": "ir_1",
        "ir_track_id": "ir_1",
        "_type": "ir_precursor_cell",
        "cell_id": cell_id,
        "lat": 46.61,
        "lon": 14.31,
        "bt_min_k": 221.5,
        "bt_mean_k": 228.0,
        "bt_trend_k_per_min": -0.4,
        "cloud_height_m": 11200,
        "cloud_height_trend_m_per_min": 80,
        "area_growth_km2_per_min": 2.5,
        "overshooting_top": True,
        "cloud_age_min": 25,
        "lineage_match_score": 0.91,
        "lineage_match_decision": "accepted",
        "lineage_match_reason": "score",
    }
    data.update(extra)
    return data


def test_payload_hides_radar_confirmed_ir_precursor():
    objects, visible_ir = dedupe_ir_precursors_for_payload(
        [_radar()],
        [_ir(radar_confirmed=True, display_as_precursor=False, ir_only_precursor=0.0)],
    )

    assert len(objects) == 1
    assert visible_ir == []
    assert objects[0]["cell_id"] == CID
    assert objects[0]["ir_track_id"] == "ir_1"
    assert objects[0]["ir_bt_min_k"] == 221.5
    assert objects[0]["ir_cloud_height_m"] == 11200
    assert objects[0]["lineage_status"] == "radar_confirmed"
    assert objects[0]["lineage_match_score"] == 0.91


def test_payload_hides_ir_with_duplicate_cell_id():
    objects, visible_ir = dedupe_ir_precursors_for_payload(
        [_radar()],
        [_ir(radar_confirmed=False, display_as_precursor=True, ir_only_precursor=1.0)],
    )

    assert len(objects) == 1
    assert visible_ir == []
    assert objects[0]["ir_bt_min_k"] == 221.5


def test_payload_keeps_unmatched_ir_precursor():
    _, visible_ir = dedupe_ir_precursors_for_payload(
        [_radar()],
        [_ir("WX-20260618-0002", radar_confirmed=False, display_as_precursor=True, ir_only_precursor=1.0)],
    )

    assert len(visible_ir) == 1
    assert visible_ir[0]["cell_id"] == "WX-20260618-0002"


def test_payload_backward_compatible_old_ir_cell():
    _, visible_ir = dedupe_ir_precursors_for_payload(
        [_radar()],
        [{"ir_id": "old_ir", "_type": "ir_cell", "ir_only_precursor": 1.0}],
    )

    assert len(visible_ir) == 1
    assert visible_ir[0]["ir_id"] == "old_ir"


def test_frontend_guard_expression_or_helper():
    for file_name in ("frontend/src/pages/MapView.jsx", "frontend/src/pages/MapFullscreen.jsx"):
        text = Path(file_name).read_text()
        assert "display_as_precursor" in text
        assert "radar_confirmed" in text
        assert "ir_only_precursor ?? 0" in text
        assert "radarCellIds" in text
        assert "!radarCellIds.has(String(o.cell_id))" in text


def _kml_text(kmz_path):
    with zipfile.ZipFile(kmz_path, "r") as zf:
        name = next(n for n in zf.namelist() if n.endswith(".kml"))
        return zf.read(name).decode("utf-8")


@pytest.mark.skipif(save_forecast_as_kmz is None, reason="simplekml nicht installiert")
def test_kmz_skips_duplicate_ir_precursor(tmp_path):
    out = tmp_path / "forecast.kmz"
    save_forecast_as_kmz(
        {}, {}, output_path=str(out), current_objects=[_radar()],
        ir_tracks=[_ir(radar_confirmed=False, display_as_precursor=True, ir_only_precursor=1.0)],
    )

    kml = _kml_text(out)
    assert kml.count(CID) >= 1
    assert "ir_1 (222K)" not in kml
    assert "bt_min_k" in kml
    assert "221.5" in kml
    assert "cloud_height_m" in kml


@pytest.mark.skipif(save_forecast_as_kmz is None, reason="simplekml nicht installiert")
def test_kmz_keeps_unmatched_ir_precursor(tmp_path):
    out = tmp_path / "forecast.kmz"
    save_forecast_as_kmz(
        {}, {}, output_path=str(out), current_objects=[_radar()],
        ir_tracks=[_ir("WX-20260618-0002", radar_confirmed=False, display_as_precursor=True, ir_only_precursor=1.0)],
    )

    kml = _kml_text(out)
    assert "ir_1 (222K)" in kml
    assert "WX-20260618-0002" in kml


def test_api_objects_include_ir_no_duplicate_cell_id(monkeypatch):
    pytest.importorskip("flask")
    app_module = importlib.import_module("app")
    monkeypatch.setattr(app_module, "_objects_for_ts", lambda ts=None: [_radar()])

    import ir_cell_tracking
    monkeypatch.setattr(
        ir_cell_tracking,
        "load_active_ir_tracks",
        lambda: [_ir(radar_confirmed=False, display_as_precursor=True, ir_only_precursor=1.0)],
    )

    data = app_module.app.test_client().get("/api/objects?include_ir=1").get_json()
    visible = []
    for obj in data:
        cid = obj.get("cell_id")
        typ = obj.get("_type")
        if cid and (
            typ != "ir_precursor_cell"
            or (
                float(obj.get("ir_only_precursor", 0) or 0) == 1.0
                and obj.get("display_as_precursor", True) is not False
                and obj.get("radar_confirmed") is not True
            )
        ):
            visible.append(cid)
    assert visible.count(CID) == 1
    assert data[0]["ir_bt_min_k"] == 221.5
