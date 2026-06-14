"""B132: cache_get gibt bei TTL-Ablauf None zurück (erzwingt Refetch).

Der Stale-While-Error-Fallback bleibt über cache_get_stale verfügbar.
"""
import json
import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.modules.setdefault("debug_utils", types.SimpleNamespace(debug_log=lambda *args, **kwargs: None))


def _write_cache_file(api_cache, key, payload, age_seconds):
    path = api_cache._path_for(key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    old = time.time() - age_seconds
    os.utime(path, (old, old))


def test_expired_returns_none_not_stale(tmp_path, monkeypatch):
    import api_cache
    monkeypatch.setattr(api_cache, "_CACHE_DIR", str(tmp_path))
    api_cache._MEM_CACHE.clear()

    key = "blitzortung_last_strikes_testkey"
    _write_cache_file(api_cache, key, {"v": 1}, age_seconds=3600)  # 1 h alt

    # TTL 60 s → Eintrag ist abgelaufen → MUSS None liefern (kein Stale-Fallback)
    assert api_cache.cache_get(key, ttl_seconds=60) is None


def test_fresh_returns_value(tmp_path, monkeypatch):
    import api_cache
    monkeypatch.setattr(api_cache, "_CACHE_DIR", str(tmp_path))
    api_cache._MEM_CACHE.clear()

    key = "geosphere_tawes_all_testkey"
    _write_cache_file(api_cache, key, {"v": 2}, age_seconds=10)  # 10 s alt
    out = api_cache.cache_get(key, ttl_seconds=600)
    assert out == {"v": 2}


def test_stale_fallback_still_available(tmp_path, monkeypatch):
    """cache_get_stale bleibt als expliziter except-Fallback nutzbar."""
    import api_cache
    monkeypatch.setattr(api_cache, "_CACHE_DIR", str(tmp_path))
    api_cache._MEM_CACHE.clear()

    key = "geosphere_cape_testkey"
    _write_cache_file(api_cache, key, {"v": 3}, age_seconds=3600)  # 1 h alt
    # innerhalb max_stale (24 h) → Stale-Fallback liefert den Wert
    assert api_cache.cache_get_stale(key, max_stale_seconds=24 * 3600) == {"v": 3}
    api_cache._MEM_CACHE.clear()
    # jenseits max_stale → None
    assert api_cache.cache_get_stale(key, max_stale_seconds=60) is None
