import json
import subprocess
import zipfile
from pathlib import Path

import pytest

import tools.import_hydro_static_manual as m


def feature_collection(kind="Polygon"):
    geom = {
        "Polygon": {"type": "Polygon", "coordinates": [[ [13.8,46.62],[14.2,46.62],[14.2,46.88],[13.8,46.88],[13.8,46.62] ]]},
        "LineString": {"type": "LineString", "coordinates": [[13.8,46.7],[14.2,46.8]]},
        "Point": {"type": "Point", "coordinates": [14.0958, 46.7237]},
    }[kind]
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": geom, "properties": {"OBJECTID": 1}}]}


def write_geojson(path: Path, kind="Polygon"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(feature_collection(kind)) + "\n", encoding="utf-8")


def make_ctx(tmp_path, *args):
    ns = m.parse_args(list(args))
    ctx = m.RunContext(ns, static_dir=tmp_path / "static", live_dir=tmp_path / "live")
    m.ensure_dirs(ctx)
    return ctx


def test_tiny_161_163_byte_files_are_invalid(tmp_path):
    p161 = tmp_path / "basins.geojson"; p161.write_text("{" + " " * 159 + "}")
    p163 = tmp_path / "flowlines.geojson"; p163.write_text("{" + " " * 161 + "}")
    with pytest.raises(ValueError): m.validate_geojson(p161, "basins")
    with pytest.raises(ValueError): m.validate_geojson(p163, "flowlines")


def test_layer_parser_accepts_common_ogr_formats():
    text = """
Layer: DRAINAGEBASIN (Multi Polygon)
Layer name: WATERCOURSELINK
1: DRAINAGEBASIN
"""
    assert m.parse_ogr_layers(text) == ["DRAINAGEBASIN", "WATERCOURSELINK", "DRAINAGEBASIN"]


def test_flowline_layers_only_accept_linestring_geometries():
    assert m.is_layer_geometry_allowed("Line String", "flowlines")
    assert m.is_layer_geometry_allowed("MultiLineString", "flowlines")
    assert not m.is_layer_geometry_allowed("Polygon", "flowlines")
    assert not m.is_layer_geometry_allowed("", "flowlines")


def test_ogr2ogr_command_uses_spat_srs_epsg4326(tmp_path):
    cmd = m.ogr2ogr_command(tmp_path / "out.geojson", "in.gdb", "DRAINAGEBASIN", m.KAERNTEN_BBOX)
    assert "-spat_srs" in cmd
    assert "EPSG:4326" in cmd
    assert "-spat" in cmd


def test_existing_valid_basins_not_overwritten_when_conversion_breaks(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path, "--basins-only", "--force")
    write_geojson(ctx.basins_geojson, "Polygon")
    old = ctx.basins_geojson.read_text(encoding="utf-8")
    z = ctx.download_dir / "basins.zip"
    with zipfile.ZipFile(z, "w") as zf: zf.writestr("x.txt", "x")
    monkeypatch.setattr(m, "download_if_needed", lambda *a, **k: z)
    monkeypatch.setattr(m, "extract_zip", lambda p: "broken.gdb")
    monkeypatch.setattr(m, "select_layer", lambda *a, **k: "DRAINAGEBASIN")
    monkeypatch.setattr(m, "run_cmd", lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "broken"))
    with pytest.raises(RuntimeError): m.import_basins(ctx)
    assert ctx.basins_geojson.read_text(encoding="utf-8") == old


def test_existing_valid_flowlines_not_overwritten_when_conversion_breaks(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path, "--flowlines-only", "--force")
    write_geojson(ctx.flowlines_geojson, "LineString")
    old = ctx.flowlines_geojson.read_text(encoding="utf-8")
    z = ctx.download_dir / "flows.zip"
    with zipfile.ZipFile(z, "w") as zf: zf.writestr("x.txt", "x")
    monkeypatch.setattr(m, "download_if_needed", lambda *a, **k: z)
    monkeypatch.setattr(m, "extract_zip", lambda p: "broken.gdb")
    monkeypatch.setattr(m, "select_layer", lambda *a, **k: "WATERCOURSELINK")
    monkeypatch.setattr(m, "run_cmd", lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "broken"))
    with pytest.raises(RuntimeError): m.import_flowlines(ctx)
    assert ctx.flowlines_geojson.read_text(encoding="utf-8") == old


def test_no_network_uses_valid_local_cache_without_request(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path, "--no-network")
    z = ctx.download_dir / "AT_DRAINAGEBASIN_GDB.zip"
    with zipfile.ZipFile(z, "w") as zf: zf.writestr("x.txt", "x")
    monkeypatch.setattr(m, "valid_zip", lambda p: p == z)
    monkeypatch.setattr(m, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    assert m.download_if_needed(ctx, m.BASINS_URL, "basins") == z
    assert ctx.downloads["basins"]["status"] == "cached"


def test_dry_run_does_not_change_files(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path, "--basins-only", "--dry-run", "--force")
    monkeypatch.setattr(m, "download_if_needed", lambda *a, **k: ctx.download_dir / "x.zip")
    monkeypatch.setattr(m, "extract_zip", lambda p: "x.gdb")
    monkeypatch.setattr(m, "select_layer", lambda *a, **k: "DRAINAGEBASIN")
    m.import_basins(ctx)
    assert not ctx.basins_geojson.exists()


def test_coverage_file_written_and_requires_basins_and_flowlines(tmp_path):
    ctx = make_ctx(tmp_path)
    write_geojson(ctx.basins_geojson, "Polygon")
    cov = m.write_coverage(ctx)
    assert (ctx.generated_dir / "hydro_static_coverage.json").exists()
    assert cov["coverage_ok"] is False
    assert cov["basin_features_feldkirchen"] > 0
    assert cov["flowline_features_feldkirchen"] == 0


def test_valid_cache_avoids_unnecessary_foreign_requests(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path, "--stations-only")
    write_geojson(ctx.stations_geojson, "Point")
    monkeypatch.setattr(m, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    m.import_stations(ctx)
