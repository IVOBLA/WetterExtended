"""
P28 — Tests für GET /api/objects/history
Prüft:
  - Endpoint antwortet mit HTTP 200
  - Rückgabe ist eine Liste
  - Aktive (live) Zellen werden NICHT zurückgegeben
  - Inaktive Zellen (aus gespeicherten Frame-Dateien) werden zurückgegeben
  - _last_seen_ts ist in jedem Ergebnis vorhanden
  - Neuester Stand pro Zelle wird geliefert (nicht der älteste)
  - Leeres Objekt-Verzeichnis liefert leere Liste (kein Crash)
"""
import json
import os
import pytest
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    """
    Setzt ein temporäres Objekt-Verzeichnis mit 3 Frame-Dateien auf.
    IL001 erscheint in ts1 und ts2, ist in ts2 aber nicht mehr live.
    IL002 erscheint in ts2 und ts3, ist in ts3 live (bleibt in tracking_memory).
    """
    pytest.importorskip("flask")
    import app as app_module

    obj_dir = tmp_path / "objects"
    obj_dir.mkdir()

    now = datetime.utcnow()
    ts1 = (now - timedelta(hours=2)).strftime("%Y-%m-%d_%H-%M-%S")
    ts2 = (now - timedelta(hours=1)).strftime("%Y-%m-%d_%H-%M-%S")
    ts3 = now.strftime("%Y-%m-%d_%H-%M-%S")

    # ts1: IL001 aktiv (total_active_frames=5)
    (obj_dir / f"{ts1}.json").write_text(
        json.dumps([{
            "id": "IL001", "lat": 46.6, "lon": 14.0,
            "missing": 0, "total_active_frames": 5,
            "speed_kmh": 30.0, "direction_deg": 210.0,
        }]),
        encoding="utf-8",
    )
    # ts2: IL001 (total_active_frames=10) + IL002 (neu)
    (obj_dir / f"{ts2}.json").write_text(
        json.dumps([
            {
                "id": "IL001", "lat": 46.61, "lon": 14.01,
                "missing": 0, "total_active_frames": 10,
                "speed_kmh": 28.0, "direction_deg": 215.0,
            },
            {
                "id": "IL002", "lat": 46.7, "lon": 14.2,
                "missing": 0, "total_active_frames": 3,
                "speed_kmh": 45.0, "direction_deg": 270.0,
            },
        ]),
        encoding="utf-8",
    )
    # ts3: nur IL002 (IL001 verschwunden)
    (obj_dir / f"{ts3}.json").write_text(
        json.dumps([{
            "id": "IL002", "lat": 46.71, "lon": 14.21,
            "missing": 0, "total_active_frames": 8,
            "speed_kmh": 46.0, "direction_deg": 268.0,
        }]),
        encoding="utf-8",
    )

    monkeypatch.setitem(app_module.SAVE_PATHS, "objects", str(obj_dir))

    # tracking_memory: nur IL002 ist live
    import object_tracking
    monkeypatch.setattr(
        object_tracking, "tracking_memory",
        {"IL002": {"id": "IL002", "missing": 0}},
    )

    # Cache zurücksetzen
    app_module._history_cache["ts"]   = 0.0
    app_module._history_cache["data"] = None

    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


@pytest.fixture()
def client_empty(tmp_path, monkeypatch):
    """Leeres Objekt-Verzeichnis — kein Crash erwartet."""
    pytest.importorskip("flask")
    import app as app_module

    obj_dir = tmp_path / "objects"
    obj_dir.mkdir()
    monkeypatch.setitem(app_module.SAVE_PATHS, "objects", str(obj_dir))

    import object_tracking
    monkeypatch.setattr(object_tracking, "tracking_memory", {})

    app_module._history_cache["ts"]   = 0.0
    app_module._history_cache["data"] = None

    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_history_returns_200(client):
    resp = client.get("/api/objects/history")
    assert resp.status_code == 200


def test_history_returns_list(client):
    data = client.get("/api/objects/history").get_json()
    assert isinstance(data, list), f"Erwartet list, bekommen: {type(data)}"


def test_history_excludes_live_cells(client):
    """IL002 ist live → darf NICHT in History erscheinen."""
    data = client.get("/api/objects/history").get_json()
    ids = [o["id"] for o in data]
    assert "IL002" not in ids, (
        f"Live-Zelle IL002 darf nicht in History sein. Vorhandene IDs: {ids}"
    )


def test_history_includes_inactive_cells(client):
    """IL001 ist nicht mehr live → muss in History erscheinen."""
    data = client.get("/api/objects/history").get_json()
    ids = [o["id"] for o in data]
    assert "IL001" in ids, (
        f"Inaktive Zelle IL001 muss in History sein. Vorhandene IDs: {ids}"
    )


def test_history_last_seen_ts_present(client):
    """_last_seen_ts muss für alle zurückgegebenen Zellen vorhanden sein."""
    data = client.get("/api/objects/history").get_json()
    assert len(data) > 0, "History ist leer — Test setzt mindestens 1 inaktive Zelle voraus"
    for cell in data:
        assert "_last_seen_ts" in cell, (
            f"_last_seen_ts fehlt bei Zelle {cell.get('id')!r}"
        )


def test_history_most_recent_state(client):
    """IL001 erscheint in ts1 (frames=5) und ts2 (frames=10).
    History muss den NEUESTEN Stand liefern: total_active_frames == 10."""
    data = client.get("/api/objects/history").get_json()
    il001 = next((o for o in data if o["id"] == "IL001"), None)
    assert il001 is not None, "IL001 nicht in History gefunden"
    assert il001["total_active_frames"] == 10, (
        f"Neuester Stand (frames=10) erwartet, bekommen: {il001['total_active_frames']}"
    )


def test_history_empty_directory_no_crash(client_empty):
    """Leeres Objekt-Verzeichnis → HTTP 200, leere Liste."""
    resp = client_empty.get("/api/objects/history")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == [], f"Leere Liste erwartet, bekommen: {data}"


def test_history_hours_parameter(client):
    """hours=0 wird auf 1 geklemmt (kein Crash, HTTP 200)."""
    resp = client.get("/api/objects/history?hours=0")
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)


def test_history_cache_populated(client):
    """Nach dem ersten Aufruf soll der Cache befüllt sein."""
    import app as app_module
    app_module._history_cache["ts"]   = 0.0
    app_module._history_cache["data"] = None

    client.get("/api/objects/history")

    assert app_module._history_cache["data"] is not None, (
        "Cache muss nach erstem Aufruf befüllt sein"
    )
    assert app_module._history_cache["ts"] > 0.0, (
        "Cache-Timestamp muss > 0 sein"
    )
