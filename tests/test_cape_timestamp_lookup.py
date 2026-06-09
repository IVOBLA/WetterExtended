import importlib
import sys
import types
from datetime import datetime, timezone


class _FakePoint:
    def __init__(self, *coords):
        if len(coords) == 1:
            self.coords = tuple(coords[0])
        else:
            self.coords = tuple(coords)

    def distance(self, other):
        return sum((a - b) ** 2 for a, b in zip(self.coords, other.coords)) ** 0.5


def _module_is_available(name):
    was_missing = name not in sys.modules
    try:
        importlib.import_module(name)
    except Exception:
        if was_missing:
            sys.modules.pop(name, None)
        return False
    return True


def _install_missing_import_doubles():
    if not _module_is_available("requests") and "requests" not in sys.modules:
        requests = types.ModuleType("requests")
        requests.get = None
        sys.modules["requests"] = requests

    if not _module_is_available("shapely") and "shapely" not in sys.modules:
        shapely = types.ModuleType("shapely")
        geometry = types.ModuleType("shapely.geometry")
        geometry.Point = _FakePoint
        shapely.geometry = geometry
        sys.modules["shapely"] = shapely
        sys.modules["shapely.geometry"] = geometry

    if not _module_is_available("debug_utils") and "debug_utils" not in sys.modules:
        debug_utils = types.ModuleType("debug_utils")
        debug_utils.debug_log = lambda *args, **kwargs: None
        debug_utils.log_http_response = lambda *args, **kwargs: None
        debug_utils.log_api_failure = lambda *args, **kwargs: None
        debug_utils.log_api_call = lambda *args, **kwargs: None
        sys.modules["debug_utils"] = debug_utils


def _import_assign_cape_from_forecast():
    module_names = ("requests", "shapely", "shapely.geometry", "debug_utils")
    previous_modules = {name: sys.modules.get(name) for name in module_names}
    _install_missing_import_doubles()

    try:
        from assign_cape_from_forecast import (  # noqa: PLC0415
            _find_nearest_cape_ts,
            _parse_cape_ts,
            assign_cape,
        )
    finally:
        for name, module in previous_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    return _find_nearest_cape_ts, _parse_cape_ts, assign_cape


_find_nearest_cape_ts, _parse_cape_ts, assign_cape = _import_assign_cape_from_forecast()


def test_parse_cape_ts_accepts_geojson_iso_variants():
    expected = datetime(2026, 6, 2, 4, 0, tzinfo=timezone.utc)
    for raw in (
        "2026-06-02T04:00+00:00",
        "2026-06-02T04:00:00+00:00",
        "2026-06-02T04:00:00Z",
        "2026-06-02T04:00Z",
        "2026-06-02 04:00:00+00:00",
    ):
        assert _parse_cape_ts(raw) == expected


def test_find_nearest_cape_ts_respects_two_hour_tolerance():
    target = datetime(2026, 6, 2, 4, 0, tzinfo=timezone.utc)
    available = [
        datetime(2026, 6, 2, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 6, 2, 6, 0, tzinfo=timezone.utc),
        datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc),
    ]
    assert _find_nearest_cape_ts(target, available) == available[1]
    # T08:00 ist 4h entfernt → None (über Toleranz)
    assert _find_nearest_cape_ts(
        target,
        [datetime(2026, 6, 2, 8, 0, tzinfo=timezone.utc)],
    ) is None

    # T06:00 ist genau 2h entfernt → akzeptiert (an der Grenze)
    result_edge = _find_nearest_cape_ts(
        target,
        [datetime(2026, 6, 2, 6, 0, tzinfo=timezone.utc)],
        max_tolerance_h=2.0,
    )
    assert result_edge == datetime(2026, 6, 2, 6, 0, tzinfo=timezone.utc)

    # T07:00 ist 3h entfernt → abgelehnt
    assert _find_nearest_cape_ts(
        target,
        [datetime(2026, 6, 2, 7, 0, tzinfo=timezone.utc)],
        max_tolerance_h=2.0,
    ) is None


def test_assign_cape_uses_nearest_forecast_timestamp(monkeypatch, tmp_path):
    geojson_path = tmp_path / "cape.geojson"
    geojson_path.write_text(
        """
        {
          "timestamps": [
            "2026-06-02T00:00:00+00:00",
            "2026-06-02T06:00:00+00:00",
            "2026-06-02T12:00:00+00:00"
          ],
          "features": [
            {
              "geometry": {"coordinates": [14.0, 46.0]},
              "properties": {"parameters": {"cape": {"data": [10, 20, 30]}}}
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "assign_cape_from_forecast.fetch_or_use_latest_geojson",
        lambda timestamp, cape_url: str(geojson_path),
    )

    objects = [{"lat": 46.0, "lon": 14.0}]
    result = assign_cape(objects, "2026-06-02_06-41-00")

    assert result[0]["cape"] == 20
