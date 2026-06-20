import sys
import types
import zipfile

import pytest

pytest.importorskip("simplekml")


def _kml_text(path):
    with zipfile.ZipFile(path) as zf:
        return zf.read("doc.kml").decode("utf-8")


def _install_hydro_api(monkeypatch, *, features=None, impacts=None, broken=False):
    if broken:
        hydro_api = types.SimpleNamespace(
            station_features=lambda: {"type": "FeatureCollection", "features": features or []},
            normalized_impacts=lambda latest=False: (_ for _ in ()).throw(ValueError("kaputtes Hydro-JSON")),
            catchment=lambda station_id: {"features": []},
        )
    else:
        hydro_api = types.SimpleNamespace(
            station_features=lambda: {"type": "FeatureCollection", "features": features or []},
            normalized_impacts=lambda latest=False: impacts or [],
            catchment=lambda station_id: {"features": []},
        )
    monkeypatch.setitem(sys.modules, "hydro_api", hydro_api)


def _station(station_id="S1", *, impact_eligible=True):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [13.1, 46.6]},
        "properties": {
            "station_id": station_id,
            "name": "Pegel A",
            "river": "Gail",
            "q_m3s": 12.3,
            "w_cm": 45,
            "measured_at": "2026-06-20T10:00:00Z",
            "impact_eligible": impact_eligible,
        },
    }


def _impact(**overrides):
    data = {
        "station_id": "S1",
        "cell_id": "C1",
        "status": "pending",
        "impact_eligible": True,
        "relation": "upstream_catchment_hit",
        "reason": ["cell_intersects_upstream_catchment", "plausibler Zusammenhang"],
    }
    data.update(overrides)
    return data


def test_kmz_export_without_hydro_data_succeeds(tmp_path, monkeypatch):
    _install_hydro_api(monkeypatch)
    from kmz_export import save_forecast_as_kmz

    out = tmp_path / "forecast.kmz"
    save_forecast_as_kmz({}, {}, str(out))

    assert out.exists()
    assert "Hydro-Impact" not in _kml_text(out)


def test_kmz_export_with_valid_hydro_impacts_succeeds(tmp_path, monkeypatch):
    _install_hydro_api(monkeypatch, features=[_station()], impacts=[_impact()])
    from kmz_export import save_forecast_as_kmz

    out = tmp_path / "forecast.kmz"
    save_forecast_as_kmz({}, {}, str(out))
    kml = _kml_text(out)

    assert "Hydro-Impact" in kml
    assert "Pegel A" in kml
    assert "plausibler Zusammenhang" in kml
    assert "Keine amtliche Hochwasserwarnung" in kml
    assert "Live-Pegel sind Rohdaten" in kml


def test_kmz_export_with_broken_hydro_json_succeeds_and_skips_hydro(tmp_path, monkeypatch):
    _install_hydro_api(monkeypatch, features=[_station()], broken=True)
    from kmz_export import save_forecast_as_kmz

    out = tmp_path / "forecast.kmz"
    save_forecast_as_kmz({}, {}, str(out))
    kml = _kml_text(out)

    assert out.exists()
    assert "Hydro-Impact" not in kml
    assert "Pegel A" not in kml


def test_kmz_export_impact_ineligible_event_creates_no_hydro_placemark(tmp_path, monkeypatch):
    _install_hydro_api(monkeypatch, features=[_station()], impacts=[_impact(impact_eligible=False)])
    from kmz_export import save_forecast_as_kmz

    out = tmp_path / "forecast.kmz"
    save_forecast_as_kmz({}, {}, str(out))
    kml = _kml_text(out)

    assert "Hydro-Impact" not in kml
    assert "Pegel A" not in kml


def test_kmz_export_event_without_catchment_reason_creates_no_hydro_placemark(tmp_path, monkeypatch):
    _install_hydro_api(monkeypatch, features=[_station()], impacts=[_impact(reason=["plausibler Zusammenhang"])])
    from kmz_export import save_forecast_as_kmz

    out = tmp_path / "forecast.kmz"
    save_forecast_as_kmz({}, {}, str(out))
    kml = _kml_text(out)

    assert "Hydro-Impact" not in kml
    assert "Pegel A" not in kml
