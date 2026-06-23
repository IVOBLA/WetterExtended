"""B237 — Topologie-Diagnose-Bundle wird erzeugt und ist im Debug-Export erlaubt."""

import json
from pathlib import Path

import pytest

import debug_export
import hydro_station_index
from hydro_station_index import build_station_index

FIX = Path(__file__).parent / "fixtures" / "hydro"


@pytest.mark.skipif(not hydro_station_index.SHAPELY_AVAILABLE, reason="Shapely fehlt")
def test_diagnostics_bundle_written_and_bounded(tmp_path):
    build_station_index(
        str(FIX / "hydro_stations_sample.geojson"),
        str(FIX / "basins_sample.geojson"),
        str(FIX / "flowlines_sample.geojson"),
        str(tmp_path),
    )
    f = tmp_path / "hydro_upstream_diagnostics.json"
    assert f.exists(), "hydro_upstream_diagnostics.json fehlt"
    diag = json.loads(f.read_text(encoding="utf-8"))
    for key in ("generated_at", "topology_quality", "counts",
                "source_quality_histogram", "upstream_source_quality_histogram",
                "edge_confidence_histogram", "cycle_nodes", "cycle_sample",
                "not_eligible_sample"):
        assert key in diag, f"Schluessel {key} fehlt"
    assert len(diag["cycle_nodes"]) <= 1000
    assert len(diag["cycle_sample"]) <= 50
    assert len(diag["not_eligible_sample"]) <= 50
    assert f.stat().st_size < 512 * 1024


def test_allowlist_includes_diagnostics_and_coverage():
    assert "hydro_upstream_diagnostics.json" in debug_export._HYDRO_STATIC_EXPORT_ALLOWLIST
    assert "hydro_static_coverage.json" in debug_export._HYDRO_STATIC_EXPORT_ALLOWLIST


def test_export_includes_diagnostics_excludes_heavy_geojson(tmp_path):
    base = tmp_path
    gen = base / "train_data" / "hydro" / "static" / "generated"
    gen.mkdir(parents=True)
    (gen / "hydro_upstream_diagnostics.json").write_text("{}", encoding="utf-8")
    (gen / "station_network_index.json").write_text("{}", encoding="utf-8")
    (gen / "hydro_static_coverage.json").write_text("{}", encoding="utf-8")
    (gen / "station_catchments.geojson").write_text("{}", encoding="utf-8")
    (gen / "hydro_upstream_graph.json").write_text("{}", encoding="utf-8")
    assert debug_export._is_excluded(gen / "hydro_upstream_diagnostics.json", base) is False
    assert debug_export._is_excluded(gen / "hydro_static_coverage.json", base) is False
    assert debug_export._is_excluded(gen / "station_catchments.geojson", base) is True
    assert debug_export._is_excluded(gen / "hydro_upstream_graph.json", base) is True
