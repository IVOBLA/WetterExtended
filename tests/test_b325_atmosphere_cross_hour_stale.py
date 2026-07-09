"""B325: Atmosphaeren-Stale-Cache findet Snapshot der Vorstunde, wenn der
aktuelle Stunden-Cache-Key noch nicht existiert (typischer Fall: erster
fehlgeschlagener Request einer neuen Stunde, z.B. HTTP 503)."""
import sys
import types
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest


def _stub_requests():
    sys.modules.setdefault(
        "requests",
        types.SimpleNamespace(
            exceptions=types.SimpleNamespace(Timeout=TimeoutError, HTTPError=Exception),
            get=lambda *a, **k: None,
        ),
    )


def test_stale_across_hours_findet_vorstunde(monkeypatch):
    _stub_requests()
    mod = pytest.importorskip("fetch_atmospheric_snapshot")
    ac = pytest.importorskip("api_cache")

    now = datetime.now(ZoneInfo(mod._TZ))
    prev_hour = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:00")

    monkeypatch.setattr(ac, "cache_key", lambda ns, url, hour: f"{ns}|{hour}")

    prev_data = [{"hourly": {"time": [prev_hour], "temperature_2m": [12.3]}}]

    def _fake_stale(key, max_stale_seconds=24 * 3600):
        return prev_data if key.endswith(prev_hour) else None

    monkeypatch.setattr(ac, "cache_get_stale", _fake_stale)

    out = mod._stale_get_recent_hours("openmeteo:atmo_arome", "https://example/url",
                                       max_stale_seconds=24 * 3600, max_hours_back=3)

    assert out == prev_data, (
        "Cross-Hour-Stale-Fallback muss den gueltigen Snapshot der Vorstunde "
        "finden, auch wenn fuer die aktuelle Stunde noch kein Cache-Eintrag existiert."
    )


def test_stale_across_hours_none_wenn_ueberall_leer(monkeypatch):
    _stub_requests()
    mod = pytest.importorskip("fetch_atmospheric_snapshot")
    ac = pytest.importorskip("api_cache")

    monkeypatch.setattr(ac, "cache_key", lambda ns, url, hour: f"{ns}|{hour}")
    monkeypatch.setattr(ac, "cache_get_stale", lambda *a, **k: None)

    out = mod._stale_get_recent_hours("openmeteo:atmo_arome", "https://example/url",
                                       max_stale_seconds=24 * 3600, max_hours_back=3)
    assert out is None


def test_bulk_get_faellt_bei_503_auf_vorstunde_zurueck(monkeypatch):
    """Integrationstest: _bulk_get() faellt bei einem HTTP-Fehler in der
    ersten Anfrage einer neuen Stunde auf den Snapshot der Vorstunde zurueck,
    statt 'kein Stale-Cache verfuegbar' zu melden."""
    _stub_requests()
    mod = pytest.importorskip("fetch_atmospheric_snapshot")
    ac = pytest.importorskip("api_cache")

    now = datetime.now(ZoneInfo(mod._TZ))
    current_hour = now.strftime("%Y-%m-%dT%H:00")
    prev_hour = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:00")

    monkeypatch.setattr(mod, "_nearest_hour_str", lambda: current_hour)
    monkeypatch.setattr(ac, "cache_key", lambda ns, url, hour: f"{ns}|{hour}")
    monkeypatch.setattr(ac, "cache_get", lambda *a, **k: None)  # kein frischer Cache

    prev_data = [{"hourly": {"time": [prev_hour], "temperature_2m": [9.9]}}]

    def _fake_stale(key, max_stale_seconds=24 * 3600):
        return prev_data if key.endswith(prev_hour) else None

    monkeypatch.setattr(ac, "cache_get_stale", _fake_stale)

    def boom(*a, **k):
        raise RuntimeError("simulierter HTTP 503")

    monkeypatch.setitem(sys.modules, "http_retry", types.SimpleNamespace(retry_get=boom))

    out = mod._bulk_get(
        "https://api.open-meteo.com/v1/forecast?models=icon_d2",
        "Open-Meteo-Atmosphere-AROME-B1",
    )
    assert out == prev_data, (
        "Bei 503 am Stundenwechsel muss der gueltige Snapshot der Vorstunde "
        "verwendet werden statt None (B325)."
    )


def test_bulk_get_liefert_none_wenn_auch_vorstunden_leer(monkeypatch):
    _stub_requests()
    mod = pytest.importorskip("fetch_atmospheric_snapshot")
    ac = pytest.importorskip("api_cache")

    monkeypatch.setattr(mod, "_nearest_hour_str", lambda: "2026-07-08T19:00")
    monkeypatch.setattr(ac, "cache_key", lambda ns, url, hour: f"{ns}|{hour}")
    monkeypatch.setattr(ac, "cache_get", lambda *a, **k: None)
    monkeypatch.setattr(ac, "cache_get_stale", lambda *a, **k: None)

    def boom(*a, **k):
        raise RuntimeError("simulierter HTTP 503")

    monkeypatch.setitem(sys.modules, "http_retry", types.SimpleNamespace(retry_get=boom))

    out = mod._bulk_get(
        "https://api.open-meteo.com/v1/forecast?models=icon_d2",
        "Open-Meteo-Atmosphere-GFS-B1",
    )
    assert out is None
