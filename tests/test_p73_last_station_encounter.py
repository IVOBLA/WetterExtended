def test_nearest_station_wind_picks_closest_within_radius(monkeypatch):
    import sys
    import types
    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(get=lambda *a, **k: None))
    import fetch_tawes_gust

    stations = [
        {"name": "Fern", "lat": 47.50, "lon": 14.50, "ff_kmh": 40.0, "ffx_kmh": 60.0, "DD": 90.0},
        {"name": "Nah",  "lat": 46.71, "lon": 14.31, "ff_kmh": 12.0, "ffx_kmh": 18.0, "DD": 225.0},
    ]

    result = fetch_tawes_gust.nearest_station_wind(46.70, 14.30, stations, radius_km=10.0)

    assert result is not None
    assert result["station_name"] == "Nah"
    assert result["wind_kmh"] == 12.0
    assert result["gust_kmh"] == 18.0
    assert result["direction_deg"] == 225.0


def test_nearest_station_wind_returns_none_outside_tight_radius(monkeypatch):
    import sys
    import types
    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(get=lambda *a, **k: None))
    import fetch_tawes_gust

    # ~30 km entfernt -> ausserhalb des engen 10-km-Begegnungsradius,
    # aber innerhalb des alten 30-km-Suchradius von max_gust_near().
    stations = [
        {"name": "Mittel", "lat": 46.97, "lon": 14.30, "ff_kmh": 20.0, "ffx_kmh": 30.0, "DD": 180.0},
    ]

    result = fetch_tawes_gust.nearest_station_wind(46.70, 14.30, stations, radius_km=10.0)

    assert result is None


def test_accumulate_station_encounter_persists_and_survives_absence(monkeypatch):
    """P73: last_station_encounter wird ins tracking_memory geschrieben und
    bleibt erhalten, auch wenn im naechsten Aufruf keine neue Begegnung
    uebergeben wird (nur bei encounter=None wird NICHT ueberschrieben —
    das Beibehalten passiert dadurch, dass accumulate_station_encounter
    fuer diesen Zyklus einfach nichts tut)."""
    import sys
    import types
    import track_statistics

    object_tracking = types.SimpleNamespace(tracking_memory={})
    monkeypatch.setitem(sys.modules, "object_tracking", object_tracking)
    object_tracking.tracking_memory = {
        "CELL1": {"id": "CELL1", "last_station_encounter": None},
    }

    encounter = {
        "timestamp": "2026-07-14_12-00-00", "station_name": "Villach",
        "distance_km": 3.2, "wind_kmh": 22.0, "gust_kmh": 48.0, "direction_deg": 225.0,
    }
    track_statistics.accumulate_station_encounter(
        [{"id": "CELL1", "last_station_encounter": encounter}]
    )

    assert object_tracking.tracking_memory["CELL1"]["last_station_encounter"] == encounter

    # Naechster Zyklus: keine neue Begegnung (encounter=None) -> alter Wert bleibt.
    track_statistics.accumulate_station_encounter(
        [{"id": "CELL1", "last_station_encounter": None}]
    )

    assert object_tracking.tracking_memory["CELL1"]["last_station_encounter"] == encounter


def test_accumulate_station_encounter_ignores_unknown_id(monkeypatch):
    import sys
    import types
    import track_statistics

    object_tracking = types.SimpleNamespace(tracking_memory={})
    monkeypatch.setitem(sys.modules, "object_tracking", object_tracking)
    object_tracking.tracking_memory = {}

    encounter = {
        "timestamp": "2026-07-14_12-00-00", "station_name": "Villach",
        "distance_km": 3.2, "wind_kmh": 22.0, "gust_kmh": 48.0, "direction_deg": 225.0,
    }
    # Darf nicht crashen, wenn die ID nicht (mehr) in tracking_memory existiert.
    track_statistics.accumulate_station_encounter(
        [{"id": "GHOSTCELL", "last_station_encounter": encounter}]
    )

    assert "GHOSTCELL" not in object_tracking.tracking_memory


def test_write_track_end_includes_last_station_encounter(tmp_path, monkeypatch):
    import json
    import track_statistics

    monkeypatch.setattr(track_statistics, "track_ends_path", lambda: str(tmp_path / "track_ends.jsonl"))

    encounter = {
        "timestamp": "2026-07-14_12-00-00", "station_name": "Villach",
        "distance_km": 3.2, "wind_kmh": 22.0, "gust_kmh": 48.0, "direction_deg": 225.0,
    }
    obj = {
        "id": "TESTCELL",
        "first_seen": "2026-07-14_12-00-00",
        "history": [{"timestamp": "2026-07-14_12-05-00"}],
        "lat": 46.7, "lon": 14.3,
        "last_station_encounter": encounter,
    }

    written = track_statistics.write_track_end(obj, "dissipated", "2026-07-14_12-10-00")

    assert written is True
    with open(tmp_path / "track_ends.jsonl", encoding="utf-8") as f:
        record = json.loads(f.readline())
    assert record["last_station_encounter"]["station_name"] == "Villach"
