"""
B317: hydro_fetch.py verwendet einen gesenkten Default-Timeout (10s statt 15s) fuer
info.ktn.gv.at. Der bestehende Circuit-Breaker (B149) und Fallback-Pfad bleiben
unveraendert wirksam.
"""
import importlib
import importlib.util
import sys
import types

import pytest

hf = pytest.importorskip("hydro_fetch")


def test_default_timeout_is_ten_seconds(monkeypatch):
    monkeypatch.delenv("HYDRO_LIVE_TIMEOUT_SECONDS", raising=False)
    importlib.reload(hf)
    assert hf.REQUEST_TIMEOUT_SECONDS == 10.0


def test_timeout_still_overridable_via_env(monkeypatch):
    monkeypatch.setenv("HYDRO_LIVE_TIMEOUT_SECONDS", "7")
    importlib.reload(hf)
    assert hf.REQUEST_TIMEOUT_SECONDS == 7.0
    monkeypatch.delenv("HYDRO_LIVE_TIMEOUT_SECONDS", raising=False)
    importlib.reload(hf)


def test_fetch_hydro_live_passes_timeout_to_retry_get(monkeypatch):
    monkeypatch.delenv("HYDRO_LIVE_TIMEOUT_SECONDS", raising=False)
    importlib.reload(hf)
    captured = {}

    def _fake_retry_get(url, **kwargs):
        captured.update(kwargs)
        raise TimeoutError("simulated timeout")

    monkeypatch.setitem(sys.modules, "http_retry", types.SimpleNamespace(retry_get=_fake_retry_get))
    monkeypatch.setattr(hf, "hydro_enabled", lambda *_a, **_k: True)
    monkeypatch.setattr(hf, "load_latest_hydro_live", lambda **_k: None)
    try:
        hf.fetch_hydro_live(force=True)
    except Exception:
        pass
    assert captured.get("timeout") == (5.0, 10.0)
    assert captured.get("max_retries") == 1


def test_effective_timeout_is_not_clamped_to_fifteen_seconds(monkeypatch):
    """B319: Reproduziert exakt den Codex-Review-Fund — prueft die TATSAECHLICHE,
    von http_retry._normalize_timeout() normalisierte Ausgabe, nicht nur den rohen
    an retry_get() uebergebenen Parameter. Vor B319 haette dieser Test mit
    (5, 15) statt (5.0, 10.0) fehlgeschlagen, da _normalize_timeout() einen
    Skalar auf max(t, 15) angehoben haette."""
    monkeypatch.delenv("HYDRO_LIVE_TIMEOUT_SECONDS", raising=False)
    importlib.reload(hf)
    if importlib.util.find_spec("requests") is None:
        pytest.skip("requests ist in dieser Testumgebung nicht installiert")
    import http_retry
    captured = {}

    def _fake_retry_get(url, **kwargs):
        captured.update(kwargs)
        raise TimeoutError("simulated timeout")

    monkeypatch.setitem(sys.modules, "http_retry", types.SimpleNamespace(retry_get=_fake_retry_get))
    monkeypatch.setattr(hf, "hydro_enabled", lambda *_a, **_k: True)
    monkeypatch.setattr(hf, "load_latest_hydro_live", lambda **_k: None)
    try:
        hf.fetch_hydro_live(force=True)
    except Exception:
        pass

    raw_timeout = captured.get("timeout")
    effective = http_retry._normalize_timeout(raw_timeout)
    assert effective == (5.0, 10.0), (
        f"Effektiver Timeout ist {effective}, erwartet (5.0, 10.0) — "
        f"pruefe ob timeout als Tupel statt Skalar uebergeben wird."
    )
