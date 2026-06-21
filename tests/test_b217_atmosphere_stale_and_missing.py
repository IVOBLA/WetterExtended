"""B217: Atmosphäre-Bulk nutzt retry_get + Stale-Cache und führt fehlende
AROME/GFS-Werte als *missing* statt als echte 0.0-Messung."""
import sys
import types

import pytest


def _stub_requests():
    sys.modules.setdefault(
        "requests",
        types.SimpleNamespace(
            exceptions=types.SimpleNamespace(Timeout=TimeoutError, HTTPError=Exception),
            get=lambda *a, **k: None,
        ),
    )


def test_bulk_get_uses_stale_cache_on_failure(monkeypatch):
    _stub_requests()
    mod = pytest.importorskip("fetch_atmospheric_snapshot")
    ac = pytest.importorskip("api_cache")

    monkeypatch.setattr(mod, "_nearest_hour_str", lambda: "2026-06-21T12:00")
    monkeypatch.setattr(ac, "cache_key", lambda *a, **k: "ck-b217")
    monkeypatch.setattr(ac, "get_ttl", lambda *a, **k: 1800)
    monkeypatch.setattr(ac, "cache_get", lambda *a, **k: None)  # kein frischer Cache
    stale = [{"hourly": {"time": ["2026-06-21T12:00"], "temperature_2m": [20.0]}}]
    monkeypatch.setattr(ac, "cache_get_stale", lambda *a, **k: stale)

    def boom(*a, **k):
        raise RuntimeError("simulierter HTTP 429")

    monkeypatch.setitem(sys.modules, "http_retry", types.SimpleNamespace(retry_get=boom))

    out = mod._bulk_get(
        "https://api.open-meteo.com/v1/forecast?latitude=46.6&longitude=14.3",
        "Open-Meteo-Atmosphere-AROME-B1",
    )
    assert out == stale, "Bei 429 muss der Stale-Cache statt None/0.0 zurückkommen."


def test_bulk_get_returns_none_without_stale(monkeypatch):
    _stub_requests()
    mod = pytest.importorskip("fetch_atmospheric_snapshot")
    ac = pytest.importorskip("api_cache")

    monkeypatch.setattr(mod, "_nearest_hour_str", lambda: "2026-06-21T12:00")
    monkeypatch.setattr(ac, "cache_key", lambda *a, **k: "ck-b217")
    monkeypatch.setattr(ac, "get_ttl", lambda *a, **k: 1800)
    monkeypatch.setattr(ac, "cache_get", lambda *a, **k: None)
    monkeypatch.setattr(ac, "cache_get_stale", lambda *a, **k: None)

    def boom(*a, **k):
        raise RuntimeError("simulierter HTTP 429")

    monkeypatch.setitem(sys.modules, "http_retry", types.SimpleNamespace(retry_get=boom))

    out = mod._bulk_get(
        "https://api.open-meteo.com/v1/forecast?latitude=46.6&longitude=14.3",
        "Open-Meteo-Atmosphere-GFS-B1",
    )
    assert out is None


def test_missing_flags_set_when_no_data(monkeypatch, tmp_path):
    _stub_requests()
    mod = pytest.importorskip("fetch_atmospheric_snapshot")

    locs = [{"name": "A", "lat": 46.6, "lon": 14.3}]
    monkeypatch.setattr(
        mod.runtime_config, "get",
        lambda key, default=None: locs if key == "ATM_SNAPSHOT_LOCATIONS" else default,
    )
    monkeypatch.setattr(mod, "_nearest_hour_str", lambda: "2026-06-21T12:00")
    monkeypatch.setattr(mod, "_OUT_FILE", str(tmp_path / "atmosphere_latest.json"))
    monkeypatch.setattr(mod, "_QUALITY_FILE", str(tmp_path / "atmosphere_feature_quality.json"))
    # Totalausfall aller Bulk-Quellen -> None (kein Stale)
    monkeypatch.setattr(mod, "_bulk_get_batched", lambda *a, **k: None)
    # Wolkenhöhe-Import stubben (kein Netzwerk im Test)
    monkeypatch.setitem(
        sys.modules, "cloud_height_from_eumetview",
        types.SimpleNamespace(fetch_cloud_height_for_points=lambda pts: {}),
    )

    res = mod.fetch_atmospheric_snapshot()
    loc0 = res["locations"][0]

    assert loc0["t2m_missing"] == 1
    assert loc0["cape_missing"] == 1
    assert loc0["li_missing"] == 1
    # numerischer Default bleibt 0.0, ist aber als missing markiert
    assert loc0["t2m"] == 0.0
    assert loc0["cape"] == 0.0
