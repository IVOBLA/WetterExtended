"""
B312: Deterministischer Fallback fuer station_id statt Array-Position.
Verhindert, dass Stationen ohne offizielle ID bei jedem Static-Reimport eine
andere ID bekommen und dadurch gespeicherte Admin-Overrides (enabled,
mark_q_m3s) verwaisen.
"""
import pytest

hsi_import = pytest.importorskip("hydro_static_import")
hsi_index = pytest.importorskip("hydro_station_index")


def test_fallback_id_is_deterministic_same_module():
    a = hsi_import._stable_fallback_station_id(14.1, 46.7, "Testpegel")
    b = hsi_import._stable_fallback_station_id(14.1, 46.7, "Testpegel")
    assert a == b


def test_fallback_id_differs_for_different_stations():
    a = hsi_import._stable_fallback_station_id(14.1, 46.7, "Testpegel A")
    b = hsi_import._stable_fallback_station_id(14.2, 46.8, "Testpegel B")
    assert a != b


def test_fallback_id_stable_across_both_modules():
    # Beide Module muessen fuer dieselbe Station dieselbe Fallback-ID liefern,
    # damit ein Wechsel zwischen den Pipelines keine neue Verwaisung erzeugt.
    a = hsi_import._stable_fallback_station_id(14.5, 46.6, "Drau Pegel")
    b = hsi_index._stable_fallback_station_id(14.5, 46.6, "Drau Pegel")
    assert a == b


def test_hydro_json_to_geojson_uses_stable_id_not_array_position():
    # Zwei Stationen ohne jegliche offizielle ID; Reihenfolge wird vertauscht —
    # die IDs muessen trotzdem gleich bleiben (nicht mehr positionsabhaengig).
    data_order_1 = {"stations": [
        {"name": "Station A", "lon": 14.1, "lat": 46.7},
        {"name": "Station B", "lon": 14.2, "lat": 46.8},
    ]}
    data_order_2 = {"stations": [
        {"name": "Station B", "lon": 14.2, "lat": 46.8},
        {"name": "Station A", "lon": 14.1, "lat": 46.7},
    ]}
    gj1 = hsi_import.hydro_json_to_geojson(data_order_1)
    gj2 = hsi_import.hydro_json_to_geojson(data_order_2)
    ids_by_name_1 = {f["properties"]["station_name"]: f["properties"]["station_id"] for f in gj1["features"]}
    ids_by_name_2 = {f["properties"]["station_name"]: f["properties"]["station_id"] for f in gj2["features"]}
    assert ids_by_name_1["Station A"] == ids_by_name_2["Station A"]
    assert ids_by_name_1["Station B"] == ids_by_name_2["Station B"]
    assert ids_by_name_1["Station A"] != ids_by_name_1["Station B"]


def test_hydro_json_to_geojson_still_prefers_official_id():
    # Offizielle IDs haben weiterhin Vorrang vor dem Fallback.
    data = {"stations": [{"id": "210999", "name": "Amtliche Station", "lon": 14.3, "lat": 46.5}]}
    gj = hsi_import.hydro_json_to_geojson(data)
    assert gj["features"][0]["properties"]["station_id"] == "210999"
