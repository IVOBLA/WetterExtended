"""B107: Korrekte Open-Meteo 700-hPa-Parameternamen in fetch_outlook_series."""
import sys
import types

# Minimale Mocks
class _StubResponse:
    def __init__(self):
        self.status_code = 200
        self.headers = {}


class _StubHTTPError(Exception):
    def __init__(self, *args, response=None, **kwargs):
        super().__init__(*args)
        self.response = response


sys.modules.setdefault(
    "requests",
    types.SimpleNamespace(
        get=lambda *a, **k: None,
        Response=_StubResponse,
        exceptions=types.SimpleNamespace(
            Timeout=Exception,
            SSLError=Exception,
            ConnectionError=Exception,
            HTTPError=_StubHTTPError,
            RequestException=Exception,
        ),
    ),
)
sys.modules.setdefault(
    "debug_utils",
    types.SimpleNamespace(
        debug_log=lambda *a, **k: None,
        log_api_failure=lambda *a, **k: None,
        log_api_call=lambda *a, **k: None,
    ),
)
sys.modules.setdefault(
    "api_cache",
    types.SimpleNamespace(
        cache_key=lambda *a, **k: "",
        cache_get=lambda *a, **k: None,
        cache_set=lambda *a, **k: None,
    ),
)

import importlib
import pytest


def test_b107_correct_700hpa_param_names():
    """B107: wind_speed_700hPa und wind_direction_700hPa (mit Unterstrich)."""
    import ast
    import pathlib
    src = pathlib.Path("fetch_outlook_series.py").read_text(encoding="utf-8")
    assert "windspeed_700hPa" not in src, (
        "Alter Parameter 'windspeed_700hPa' noch vorhanden (ohne Unterstrich nach 'wind')"
    )
    assert "winddirection_700hPa" not in src, (
        "Alter Parameter 'winddirection_700hPa' noch vorhanden"
    )
    assert "wind_speed_700hPa" in src, "Korrekter Parameter 'wind_speed_700hPa' nicht gefunden"
    assert "wind_direction_700hPa" in src, "Korrekter Parameter 'wind_direction_700hPa' nicht gefunden"
