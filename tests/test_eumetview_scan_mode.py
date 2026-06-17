"""
Tests für cloud_height_from_eumetview.get_active_ir108_layer (FES/RSS-Resolver).
Dependency-arm: kein Netzwerk — Caps-Root wird injiziert, Cache wird umgangen.
"""
import importlib.util
import sys
import types
import xml.etree.ElementTree as ET

if importlib.util.find_spec("requests") is None:
    sys.modules["requests"] = types.SimpleNamespace()
if importlib.util.find_spec("numpy") is None:
    sys.modules["numpy"] = types.SimpleNamespace()
sys.modules["debug_utils"] = types.SimpleNamespace(
    debug_log=lambda *a, **k: None,
    log_api_failure=lambda *a, **k: None,
    log_api_call=lambda *a, **k: None,
    log_http_response=lambda *a, **k: None,
)

import runtime_config
import cloud_height_from_eumetview as ch


def _cfg(values):
    def _g(name, default=None):
        return values.get(name, default)
    return _g


def _root_with(name):
    return ET.fromstring(
        f"<WMS_Capabilities><Layer><Layer><Name>{name}</Name>"
        f"</Layer></Layer></WMS_Capabilities>"
    )


def _bypass_cache(monkeypatch):
    monkeypatch.setattr(ch, "cache_get", lambda *a, **k: None)
    monkeypatch.setattr(ch, "cache_set", lambda *a, **k: None)


def test_fes_default_returns_fes_without_caps(monkeypatch):
    monkeypatch.setattr(runtime_config, "get", _cfg({
        "EUMETVIEW_SCAN_MODE": "FES",
        "EUMETVIEW_FES_LAYER_IR108": "msg_fes:ir108",
    }))

    def _boom():
        raise AssertionError("Im FES-Modus darf kein GetCapabilities geholt werden")

    assert ch.get_active_ir108_layer(caps_root_provider=_boom) == "msg_fes:ir108"


def test_rss_without_free_confirmed_falls_back(monkeypatch):
    _bypass_cache(monkeypatch)
    monkeypatch.setattr(runtime_config, "get", _cfg({
        "EUMETVIEW_SCAN_MODE": "RSS",
        "EUMETVIEW_FES_LAYER_IR108": "msg_fes:ir108",
        "EUMETVIEW_LICENSE_STATUS": "unconfirmed",
    }))

    def _boom():
        raise AssertionError("Ohne free_confirmed darf kein Caps-Fetch erfolgen")

    assert ch.get_active_ir108_layer(caps_root_provider=_boom) == "msg_fes:ir108"


def test_rss_paid_allowed_conflict_falls_back(monkeypatch):
    _bypass_cache(monkeypatch)
    monkeypatch.setattr(runtime_config, "get", _cfg({
        "EUMETVIEW_SCAN_MODE": "RSS",
        "EUMETVIEW_FES_LAYER_IR108": "msg_fes:ir108",
        "EUMETVIEW_LICENSE_STATUS": "free_confirmed",
        "EUMETVIEW_PAID_ALLOWED": True,
    }))
    assert ch.get_active_ir108_layer(
        caps_root_provider=lambda: _root_with("msg_rss:ir108")
    ) == "msg_fes:ir108"


def test_rss_layer_present_returns_rss(monkeypatch):
    _bypass_cache(monkeypatch)
    monkeypatch.setattr(runtime_config, "get", _cfg({
        "EUMETVIEW_SCAN_MODE": "RSS",
        "EUMETVIEW_FES_LAYER_IR108": "msg_fes:ir108",
        "EUMETVIEW_RSS_LAYER_IR108": None,
        "EUMETVIEW_LICENSE_STATUS": "free_confirmed",
        "EUMETVIEW_PAID_ALLOWED": False,
    }))
    assert ch.get_active_ir108_layer(
        caps_root_provider=lambda: _root_with("msg_rss:ir108")
    ) == "msg_rss:ir108"


def test_rss_layer_absent_falls_back(monkeypatch):
    _bypass_cache(monkeypatch)
    monkeypatch.setattr(runtime_config, "get", _cfg({
        "EUMETVIEW_SCAN_MODE": "RSS",
        "EUMETVIEW_FES_LAYER_IR108": "msg_fes:ir108",
        "EUMETVIEW_RSS_LAYER_IR108": None,
        "EUMETVIEW_LICENSE_STATUS": "free_confirmed",
        "EUMETVIEW_PAID_ALLOWED": False,
    }))
    assert ch.get_active_ir108_layer(
        caps_root_provider=lambda: _root_with("foo:bar")
    ) == "msg_fes:ir108"


def test_explicit_rss_layer_name_used(monkeypatch):
    _bypass_cache(monkeypatch)
    monkeypatch.setattr(runtime_config, "get", _cfg({
        "EUMETVIEW_SCAN_MODE": "RSS",
        "EUMETVIEW_FES_LAYER_IR108": "msg_fes:ir108",
        "EUMETVIEW_RSS_LAYER_IR108": "msg_rss:ir108_hr",
        "EUMETVIEW_LICENSE_STATUS": "free_confirmed",
        "EUMETVIEW_PAID_ALLOWED": False,
    }))
    assert ch.get_active_ir108_layer(
        caps_root_provider=lambda: _root_with("msg_rss:ir108_hr")
    ) == "msg_rss:ir108_hr"
