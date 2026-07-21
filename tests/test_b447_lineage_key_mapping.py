"""B447: contributing_lineage_ids wird aus den echten Zell-Schlüsseln befüllt."""

import pytest

shapely = pytest.importorskip("shapely")
if not hasattr(shapely, "__version__"):
    pytest.skip("echtes Shapely ist nicht installiert", allow_module_level=True)

from shapely.geometry import Polygon

import hydro_flood_ml
import hydro_impact


def _station():
    return {
        "station_id": "2001049",
        "name": "Testpegel",
        "lat": 46.6,
        "lon": 13.8,
        "catchment_area_km2": 100.0,
    }


def _cell_ueber_station():
    """Zellobjekt im echten Schema: cell_id/id/parents/lineage, kein lineage_id."""
    return {
        "cell_id": "WX-20260720-0601",
        "id": "GH3CNRA2",
        "lineage": "continued",
        "parents": ["GH3CNRA2"],
        "lat": 46.6,
        "lon": 13.8,
        "contour_geo": [
            [13.7, 46.5],
            [13.9, 46.5],
            [13.9, 46.7],
            [13.7, 46.7],
            [13.7, 46.5],
        ],
        "nowcast_rain_rate_1h": 20.0,
    }


@pytest.fixture(autouse=True)
def _catchment(monkeypatch):
    catchment = Polygon([(13.6, 46.4), (14.0, 46.4), (14.0, 46.8), (13.6, 46.8)])
    monkeypatch.setattr(
        hydro_impact,
        "load_station_catchment_index",
        lambda force_reload=False: {
            "2001049": {"station_id": "2001049", "geometry": catchment}
        },
    )
    monkeypatch.setattr(
        hydro_flood_ml.runtime_config,
        "get",
        lambda name, default=None: 0.0
        if name == "HYDRO_MIN_OVERLAP_AREA_KM2"
        else default,
    )


def test_contributing_lineage_ids_nicht_leer():
    row = hydro_flood_ml.build_feature_row(
        _station(), live={}, cells=[_cell_ueber_station()]
    )
    lids = row.get("contributing_lineage_ids")
    assert isinstance(lids, list)
    assert lids, "contributing_lineage_ids ist leer — Lineage-Bezug weiterhin tot"
    assert "WX-20260720-0601" in lids


def test_cell_ohne_lineage_id_key_wird_verarbeitet():
    cell = _cell_ueber_station()
    assert "lineage_id" not in cell and "parent_cell_ids" not in cell
    row = hydro_flood_ml.build_feature_row(_station(), live={}, cells=[cell])
    assert row.get("contributing_lineage_ids")


def test_fallback_auf_id_wenn_cell_id_fehlt():
    cell = _cell_ueber_station()
    del cell["cell_id"]
    row = hydro_flood_ml.build_feature_row(_station(), live={}, cells=[cell])
    lids = row.get("contributing_lineage_ids") or []
    assert "GH3CNRA2" in lids
