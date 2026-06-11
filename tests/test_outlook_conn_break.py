# tests/test_outlook_conn_break.py
"""B127: Verbindungsfehler -> kein MIN-Retry, früher Circuit-Stopp."""

import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.skipif(importlib.util.find_spec("requests") is None, reason="requests fehlt")
def test_connection_error_does_not_try_min_variant(tmp_path, monkeypatch):
    monkeypatch.setenv("API_CIRCUIT_BREAKER_FILE", str(tmp_path / "cb.json"))
    import requests
    import api_circuit_breaker
    importlib.reload(api_circuit_breaker)
    api_circuit_breaker._STATE.clear()

    import fetch_outlook_series as fos
    importlib.reload(fos)

    calls = {"n": 0}

    def _boom(lats, lons, hourly):
        calls["n"] += 1
        raise requests.exceptions.ConnectionError("Max retries exceeded")

    monkeypatch.setattr(fos, "_request", _boom)
    monkeypatch.setattr(fos, "_is_fresh", lambda: False)
    # Fallback-Datei leer -> _load_fallback liefert points:[]
    monkeypatch.setattr(fos, "_OUT_FILE", str(tmp_path / "ts.json"))

    res = fos.fetch_outlook_series(force=True)
    assert isinstance(res, dict)
    # Pro Batch nur EIN Request (FULL), nicht zwei (FULL+MIN):
    # Anzahl Requests darf die Batch-Anzahl nicht überschreiten.
    n_batches = (len(list(fos.ATM_SNAPSHOT_LOCATIONS)) + fos._BATCH_SIZE - 1) // fos._BATCH_SIZE
    assert calls["n"] <= n_batches, (
        f"Es wurden {calls['n']} Requests gemacht, erwartet <= {n_batches} "
        "(kein MIN-Retry bei Verbindungsfehler)."
    )


@pytest.mark.skipif(importlib.util.find_spec("requests") is None, reason="requests fehlt")
def test_open_circuit_stops_immediately(tmp_path, monkeypatch):
    monkeypatch.setenv("API_CIRCUIT_BREAKER_FILE", str(tmp_path / "cb.json"))
    monkeypatch.setenv("CIRCUIT_THRESHOLD_CONN", "1")  # nach 1 Fehler öffnen
    import requests
    import api_circuit_breaker
    importlib.reload(api_circuit_breaker)
    api_circuit_breaker._STATE.clear()

    import fetch_outlook_series as fos
    importlib.reload(fos)

    calls = {"n": 0}

    def _boom(lats, lons, hourly):
        calls["n"] += 1
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(fos, "_request", _boom)
    monkeypatch.setattr(fos, "_is_fresh", lambda: False)
    monkeypatch.setattr(fos, "_OUT_FILE", str(tmp_path / "ts.json"))

    fos.fetch_outlook_series(force=True)
    # Mit Schwelle 1 öffnet der Circuit nach dem ersten Batch -> genau 1 Request.
    assert calls["n"] == 1, f"Erwartet 1 Request (sofortiger Stopp), war {calls['n']}"
