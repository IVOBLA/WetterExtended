import sys
import types
from datetime import datetime, timezone


class _DummyHTTPError(Exception):
    def __init__(self, *args, response=None):
        super().__init__(*args)
        self.response = response


sys.modules.setdefault(
    "requests",
    types.SimpleNamespace(exceptions=types.SimpleNamespace(HTTPError=_DummyHTTPError)),
)
sys.modules.setdefault(
    "debug_utils",
    types.SimpleNamespace(
        debug_log=lambda *args, **kwargs: None,
        log_api_failure=lambda *args, **kwargs: None,
        log_http_response=lambda *args, **kwargs: None,
        log_api_call=lambda *args, **kwargs: None,
    ),
)
for _name in ("debug_log", "log_api_failure", "log_http_response", "log_api_call"):
    if not hasattr(sys.modules["debug_utils"], _name):
        setattr(sys.modules["debug_utils"], _name, lambda *args, **kwargs: None)
if not hasattr(sys.modules["requests"], "exceptions"):
    sys.modules["requests"].exceptions = types.SimpleNamespace(HTTPError=_DummyHTTPError)

sys.modules.setdefault(
    "api_cache",
    types.SimpleNamespace(
        cache_key=lambda *args, **kwargs: ":".join(map(str, args)),
        cache_get=lambda *args, **kwargs: None,
        cache_set=lambda *args, **kwargs: None,
        get_ttl=lambda *args, **kwargs: 0,
    ),
)

if not hasattr(sys.modules["api_cache"], "get_ttl"):
    sys.modules["api_cache"].get_ttl = lambda *args, **kwargs: 0

import fetch_geosphere_nowcast as nowcast


def test_b92_nowcast_slots_only_include_completed_slots():
    slots = nowcast._build_nowcast_slots(datetime(2026, 6, 8, 14, 21, tzinfo=timezone.utc))

    assert slots == [
        {
            "start_str": "2026-06-08T14:00",
            "end_str": "2026-06-08T14:15",
            "cache_sfx": "2026-06-08T14:00",
        },
        {
            "start_str": "2026-06-08T13:45",
            "end_str": "2026-06-08T14:00",
            "cache_sfx": "2026-06-08T13:45",
        },
    ]


def test_b88_nowcast_url_keeps_literal_lat_lon_comma():
    url = nowcast._build_nowcast_url(
        47.001,
        13.907,
        {"start_str": "2026-06-08T14:15", "end_str": "2026-06-08T14:30"},
    )

    assert "lat_lon=47.001,13.907" in url
    assert "%2C" not in url
    assert "parameters=rr&parameters=ff&parameters=ffx" in url
    assert "start=2026-06-08T14:15&end=2026-06-08T14:30" in url


def test_b92_b93_assign_nowcast_uses_completed_slot_and_single_bulk_request(monkeypatch):
    calls = []

    class DummyDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 8, 14, 21, 19, tzinfo=tz)

    class DummyResponse:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "features": [
                    {
                        "properties": {
                            "parameters": {
                                "rr": {"data": [1.5]},
                                "ff": {"data": [10.0]},
                                "ffx": {"data": [20.0]},
                            }
                        }
                    },
                    {
                        "properties": {
                            "parameters": {
                                "rr": {"data": [2.0]},
                                "ff": {"data": [5.0]},
                                "ffx": {"data": [8.0]},
                            }
                        }
                    },
                ]
            }

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return DummyResponse()

    monkeypatch.setattr(nowcast, "datetime", DummyDatetime)
    monkeypatch.setattr(nowcast, "cache_get", lambda *args, **kwargs: None)
    monkeypatch.setattr(nowcast, "cache_set", lambda *args, **kwargs: None)
    monkeypatch.setattr(nowcast.requests, "get", fake_get, raising=False)

    objects = nowcast.assign_nowcast_to_objects(
        [
            {"lat": 47.0014, "lon": 13.9066},
            {"lat": 47.1212, "lon": 14.3523},
        ],
        "ignored",
    )

    assert len(calls) == 1
    url = calls[0][0]
    assert "start=2026-06-08T14:00&end=2026-06-08T14:15" in url
    assert "lat_lon=47.001,13.907" in url
    assert "lat_lon=47.121,14.352" in url
    assert objects[0]["nowcast_rr_mm15"] == 1.5
    assert objects[0]["nowcast_ff_kmh"] == 36.0
    assert objects[0]["nowcast_ffx_kmh"] == 72.0
    assert objects[1]["nowcast_rr_mm15"] == 2.0
    assert objects[1]["nowcast_ff_kmh"] == 18.0
    assert objects[1]["nowcast_ffx_kmh"] == 28.8
