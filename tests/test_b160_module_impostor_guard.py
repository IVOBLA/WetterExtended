"""
tests/test_b160_module_impostor_guard.py

B160: conftest._preload_critical_modules() entfernt SimpleNamespace-Impostoren für
requests/http_retry aus sys.modules und lädt die ECHTEN Module nach, sodass
test_b149_* (http_retry._SESSION), test_b151_* (http_retry.requests) und
test_nowcast_out_of_coverage_b131 (retry_get) nicht durch einen geleakten Stub aus
test_eumetview_parser.py kontaminiert werden.

Ausführbar: python3 -m pytest tests/test_b160_module_impostor_guard.py -v
"""
import os
import sys
import types
import importlib.util

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_conftest():
    path = os.path.join(os.path.dirname(__file__), "conftest.py")
    spec = importlib.util.spec_from_file_location("conftest_b160_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_http_retry_impostor_is_replaced():
    pytest.importorskip("requests")
    cf = _load_conftest()
    _orig = sys.modules.get("http_retry")
    sys.modules["http_retry"] = types.SimpleNamespace(retry_get=lambda *a, **k: None)
    try:
        cf._preload_critical_modules()
        hr = sys.modules.get("http_retry")
        assert not cf._is_module_impostor(hr), "http_retry darf kein SimpleNamespace-Impostor sein"
        assert hasattr(hr, "_SESSION"), "echtes http_retry besitzt _SESSION"
        assert hasattr(hr, "requests"), "echtes http_retry besitzt das requests-Modul"
        assert callable(getattr(hr, "retry_get", None)), "retry_get muss aufrufbar sein"
    finally:
        if _orig is not None:
            sys.modules["http_retry"] = _orig


def test_requests_impostor_is_replaced():
    pytest.importorskip("requests")
    cf = _load_conftest()
    _orig = sys.modules.get("requests")
    sys.modules["requests"] = types.SimpleNamespace()
    try:
        cf._preload_critical_modules()
        rq = sys.modules.get("requests")
        assert not cf._is_module_impostor(rq), "requests darf kein SimpleNamespace-Impostor sein"
        assert hasattr(rq, "Session"), "echtes requests besitzt Session"
        assert hasattr(rq, "exceptions"), "echtes requests besitzt exceptions"
    finally:
        if _orig is not None:
            sys.modules["requests"] = _orig


def test_real_http_retry_has_session_after_import():
    pytest.importorskip("requests")
    import http_retry
    assert hasattr(http_retry, "_SESSION"), "_SESSION muss im echten Modul vorhanden sein"
    assert callable(http_retry.retry_get), "retry_get muss aufrufbar sein"
