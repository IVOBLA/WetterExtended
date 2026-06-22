import json
import subprocess
import types
import zipfile
from pathlib import Path

import hydro_static_import as h


def test_ogr_layer_parser_accepts_layer_prefix(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd[:1] == ["ogrinfo"]
        return types.SimpleNamespace(stdout="INFO: Open of `x.gdb'\nLayer: DRAINAGEBASIN\nLayer: OTHER\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert h._ogr_layers("x.gdb")[:2] == ["DRAINAGEBASIN", "OTHER"]


def test_basin_properties_are_normalized_from_official_fields(tmp_path):
    path = tmp_path / "basins.geojson"
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": None, "properties": {"HYDROID": "H-1"}},
            {"type": "Feature", "geometry": None, "properties": {"INSPIREID_IDENTIFIER_LOCALID": "I-2"}},
        ],
    }), encoding="utf-8")

    assert h.normalize_basin_properties(str(path))
    props = [f["properties"] for f in json.loads(path.read_text(encoding="utf-8"))["features"]]
    assert props[0]["catchment_id"] == props[0]["basin_id"] == props[0]["id"] == "H-1"
    assert props[1]["catchment_id"] == props[1]["basin_id"] == props[1]["id"] == "I-2"


def test_convert_to_geojson_uses_detected_layer_bbox_and_normalizes(monkeypatch, tmp_path):
    src = tmp_path / "x.gdb"
    src.mkdir()
    dst = tmp_path / "basins.geojson"
    monkeypatch.setattr(h.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(h, "_ogr_layers", lambda dataset: ["DRAINAGEBASIN"])
    monkeypatch.setattr(h.config, "HYDRO_STATIC_BBOX", {"west": 12.6, "south": 46.36, "east": 15.2, "north": 47.18})

    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        dst.write_text(json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": None, "properties": {"OBJECTID": 7}}]}), encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert h.convert_to_geojson(str(src), str(dst), "basins")
    assert calls[0][-1] == "DRAINAGEBASIN"
    assert "-spat" in calls[0]
    props = json.loads(dst.read_text(encoding="utf-8"))["features"][0]["properties"]
    assert props["catchment_id"] == props["basin_id"] == props["id"] == "7"


def test_cached_zip_must_be_valid(monkeypatch, tmp_path):
    monkeypatch.setattr(h.config, "HYDRO_DRAINAGEBASIN_GDB_URL", "https://example.invalid/AT_DRAINAGEBASIN_GDB.zip")
    p = tmp_path / "source/_downloads/AT_DRAINAGEBASIN_GDB.zip"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"not a zip")

    def fail(*args, **kwargs):
        raise RuntimeError("network attempted because cache invalid")

    monkeypatch.setitem(__import__("sys").modules, "http_retry", types.SimpleNamespace(retry_get=fail))
    monkeypatch.setitem(__import__("sys").modules, "external_response_logger", types.SimpleNamespace(persist_requests_response=lambda *a, **k: None, persist_external_response=lambda *a, **k: None))
    info = h.download_basins(str(tmp_path))
    assert info["status"] == "failed"
    assert "network attempted" in info["error"]


def test_valid_cached_zip_is_not_reloaded(monkeypatch, tmp_path):
    monkeypatch.setattr(h.config, "HYDRO_DRAINAGEBASIN_GDB_URL", "https://example.invalid/AT_DRAINAGEBASIN_GDB.zip")
    p = tmp_path / "source/_downloads/AT_DRAINAGEBASIN_GDB.zip"
    p.parent.mkdir(parents=True)
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("a.txt", "ok")
    monkeypatch.setitem(__import__("sys").modules, "http_retry", types.SimpleNamespace(retry_get=lambda *a, **k: (_ for _ in ()).throw(AssertionError("network"))))
    assert h.download_basins(str(tmp_path))["status"] == "cached"


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


def _poly_feature(w, s, e, n, props=None):
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}, "properties": props or {}}


def _line_feature(coords, props=None):
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}, "properties": props or {}}


def test_empty_basins_geojson_is_validation_error(tmp_path):
    path = tmp_path / "basins.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    try:
        h.validate_geojson_output(str(path), "basins")
    except ValueError as exc:
        assert "leer/zu klein" in str(exc) or "keine Features" in str(exc)
    else:
        raise AssertionError("empty basins must fail")


def test_wrong_extent_is_validation_error(tmp_path):
    path = tmp_path / "basins.geojson"
    path.write_text(json.dumps(_fc([_poly_feature(-23, 58, -18, 63, {"OBJECTID": 1})])), encoding="utf-8")
    try:
        h.validate_geojson_output(str(path), "basins")
    except ValueError as exc:
        assert "Kärnten-BBOX" in str(exc)
    else:
        raise AssertionError("wrong extent must fail")


def test_feldkirchen_coverage_ok_with_basin_and_flowline(tmp_path):
    paths = h.ensure_static_dirs(str(tmp_path))
    Path(paths["basins_source"]).write_text(json.dumps(_fc([_poly_feature(13.8, 46.62, 14.2, 46.88, {"HYDROID": "FK-1"})])), encoding="utf-8")
    Path(paths["flowlines_source"]).write_text(json.dumps(_fc([_line_feature([[13.82, 46.65], [14.15, 46.8]], {"name": "Tiebel"})])), encoding="utf-8")

    result = h.check_coverage("feldkirchen", str(tmp_path))

    assert result["coverage_ok"] is True
    assert result["basin_features_feldkirchen"] == 1
    assert result["flowline_features_feldkirchen"] == 1
    assert "Tiebel" in result["sample_river_names"]
    assert (Path(paths["generated"]) / "hydro_static_coverage.json").exists()


def test_missing_flowlines_reports_only_flowline_error(tmp_path):
    paths = h.ensure_static_dirs(str(tmp_path))
    Path(paths["basins_source"]).write_text(json.dumps(_fc([_poly_feature(13.8, 46.62, 14.2, 46.88, {"HYDROID": "FK-1"})])), encoding="utf-8")

    result = h.check_coverage("feldkirchen", str(tmp_path))

    assert result["coverage_ok"] is False
    assert result["basin_features_feldkirchen"] == 1
    assert any("flowlines" in e for e in result["errors"])
    assert "feldkirchen_basins_missing" not in result["errors"]
