"""B331: get_latest_wms_time() darf bei anhaltendem Parse-/Abruffehler nicht
bei jedem Aufruf einen neuen HTTP-Request-Burst ausloesen — ein Negativ-Cache
muss wiederholte Fetches innerhalb der TTL unterdruecken."""
import sys
import types

import pytest


def _stub_requests():
    sys.modules["requests"] = types.SimpleNamespace(
        exceptions=types.SimpleNamespace(Timeout=TimeoutError, HTTPError=Exception),
        get=lambda *a, **k: None,
    )
    sys.modules.setdefault("numpy", types.SimpleNamespace())


def test_wiederholter_aufruf_innerhalb_ttl_loest_keinen_neuen_fetch_aus(monkeypatch):
    _stub_requests()
    mod = pytest.importorskip("cloud_height_from_eumetview")

    cache_store = {}
    call_count = []

    def _boom(*a, **k):
        call_count.append(1)
        raise RuntimeError("simulierter Parse-Fehler")

    monkeypatch.setitem(sys.modules, "http_retry", types.SimpleNamespace(retry_get=_boom))
    monkeypatch.setattr(mod, "get_active_ir108_layer", lambda *a, **k: "ir108_fes")
    monkeypatch.setattr(mod, "cache_get", lambda key, ttl_seconds=600: cache_store.get(key))
    monkeypatch.setattr(mod, "cache_set", lambda key, value: cache_store.__setitem__(key, value))
    monkeypatch.setattr(mod, "_caps_fallback", lambda reason: f"fallback:{reason}")
    monkeypatch.setattr(mod, "log_http_response", lambda *a, **k: None)
    monkeypatch.setattr(mod, "log_api_failure", lambda *a, **k: None)

    # Erster Aufruf: echter Fetch-Versuch, schlaegt fehl.
    out1 = mod.get_latest_wms_time()
    assert out1 == "fallback:exception-RuntimeError"
    assert len(call_count) == 1

    # Zweiter Aufruf unmittelbar danach: Negativ-Cache muss greifen,
    # KEIN erneuter retry_get()-Aufruf.
    out2 = mod.get_latest_wms_time()
    assert out2 == "fallback:exception-RuntimeError"
    assert len(call_count) == 1, (
        "Der zweite Aufruf innerhalb der Negativ-Cache-TTL darf keinen "
        "neuen HTTP-Request ausloesen."
    )


def test_erfolgreicher_fetch_nach_fehler_ueberschreibt_negativ_cache_nicht_faelschlich(monkeypatch):
    """Nach einem Erfolg darf der naechste Aufruf den Erfolgs-Cache treffen,
    nicht den (inzwischen veralteten) Negativ-Cache."""
    _stub_requests()
    mod = pytest.importorskip("cloud_height_from_eumetview")

    monkeypatch.setattr(mod, "get_active_ir108_layer", lambda *a, **k: "ir108_fes")

    ck = mod.cache_key("eumetview:capabilities", "ir108_fes", mod._WMS_VERSION)

    class _FakeResp:
        ok = True
        status_code = 200
        content = b"<WMS_Capabilities></WMS_Capabilities>"

    def _fake_retry_get(*a, **k):
        return _FakeResp()

    monkeypatch.setitem(sys.modules, "http_retry", types.SimpleNamespace(retry_get=_fake_retry_get))
    monkeypatch.setattr(mod, "log_http_response", lambda *a, **k: None)
    monkeypatch.setattr(mod, "cache_get", lambda key, ttl_seconds=600: "2026-07-10T08:00:00Z" if key == ck else None)

    out = mod.get_latest_wms_time()
    assert out == "2026-07-10T08:00:00Z"
