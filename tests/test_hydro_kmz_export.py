import pytest
pytest.importorskip("simplekml")
import zipfile


def test_kmz_contains_hydro_layer(tmp_path, monkeypatch):
    import hydro_api
    monkeypatch.setattr(hydro_api, 'station_features', lambda: {'type':'FeatureCollection','features':[{'type':'Feature','geometry':{'type':'Point','coordinates':[13.1,46.6]},'properties':{'station_id':'S1','name':'Pegel A','river':'Gail','status':'pending'}}]})
    monkeypatch.setattr(hydro_api, 'normalized_impacts', lambda latest=False: [{'station_id':'S1','cell_id':'C1','status':'pending'}])
    from kmz_export import save_forecast_as_kmz
    out = tmp_path / 'forecast.kmz'
    save_forecast_as_kmz({}, {}, str(out))
    with zipfile.ZipFile(out) as zf:
        kml = zf.read('doc.kml').decode('utf-8')
    assert 'Hydro-Impact' in kml
    assert 'Pegel A' in kml
