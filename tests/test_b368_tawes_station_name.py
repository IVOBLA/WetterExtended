"""B368: Stationsname muss aus dem Metadata-Endpunkt aufgeloest werden,
statt immer auf f"Station {id}" zurueckzufallen."""
import sys
import types


def _install_requests_stub(monkeypatch, current_response=None, metadata_response=None):
    calls = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload
            self.status_code = 200
            self.headers = {"content-type": "application/json"}

        def json(self):
            return self._payload

    def _fake_get(url, *a, **k):
        calls.append(url)
        if url.endswith("/metadata"):
            return _Resp(metadata_response or {})
        return _Resp(current_response or {})

    monkeypatch.setitem(
        sys.modules, "requests", types.SimpleNamespace(get=_fake_get)
    )
    monkeypatch.setitem(
        sys.modules, "http_retry",
        types.SimpleNamespace(retry_get=lambda url, **k: _fake_get(url)),
    )
    return calls


def _import_fetch_tawes_gust(monkeypatch, current_response=None, metadata_response=None):
    _install_requests_stub(monkeypatch, current_response, metadata_response)
    sys.modules.pop("fetch_tawes_gust", None)
    import fetch_tawes_gust

    return fetch_tawes_gust


def _disable_tawes_caches(monkeypatch, fetch_tawes_gust):
    monkeypatch.setattr(fetch_tawes_gust, "cache_get", lambda *a, **k: None)
    monkeypatch.setattr(fetch_tawes_gust, "cache_set", lambda *a, **k: None)


def test_station_name_resolved_from_metadata_endpoint(monkeypatch):
    current_response = {
        "features": [
            {
                "type": "Feature",
                "geometry": {"coordinates": [13.83, 46.62]},
                "properties": {
                    "station": "11086",
                    "parameters": {
                        "TL": {"name": "Lufttemperatur", "data": [20.0]},
                    },
                },
            }
        ]
    }
    metadata_response = {
        "stations": [
            {"id": "11086", "name": "Villach", "state": "Kaernten", "altitude": 501},
        ]
    }
    fetch_tawes_gust = _import_fetch_tawes_gust(monkeypatch, current_response, metadata_response)
    _disable_tawes_caches(monkeypatch, fetch_tawes_gust)

    stations = fetch_tawes_gust.fetch_tawes_stations()

    assert len(stations) == 1
    assert stations[0]["name"] == "Villach"
    assert stations[0]["station_id"] == "11086"


def test_station_name_falls_back_when_metadata_unavailable(monkeypatch):
    current_response = {
        "features": [
            {
                "type": "Feature",
                "geometry": {"coordinates": [13.83, 46.62]},
                "properties": {"station": "99999", "parameters": {}},
            }
        ]
    }
    metadata_response = {"stations": []}  # keine Namen verfuegbar
    fetch_tawes_gust = _import_fetch_tawes_gust(monkeypatch, current_response, metadata_response)
    _disable_tawes_caches(monkeypatch, fetch_tawes_gust)

    stations = fetch_tawes_gust.fetch_tawes_stations()

    assert len(stations) == 1
    assert stations[0]["name"] == "Station 99999"  # sicherer Fallback, kein Crash


def test_fetch_station_name_map_returns_empty_dict_on_http_error(monkeypatch):
    fetch_tawes_gust = _import_fetch_tawes_gust(monkeypatch)
    _disable_tawes_caches(monkeypatch, fetch_tawes_gust)

    def _raise(*a, **k):
        raise ConnectionError("boom")

    monkeypatch.setitem(
        sys.modules, "http_retry",
        types.SimpleNamespace(retry_get=_raise),
    )

    result = fetch_tawes_gust._fetch_station_name_map()
    assert result == {}
