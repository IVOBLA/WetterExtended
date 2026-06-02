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


sys.modules.setdefault("requests", types.SimpleNamespace(get=None))
_shapely = types.ModuleType("shapely")
_geometry = types.ModuleType("shapely.geometry")
_geometry.Point = _FakePoint
sys.modules.setdefault("shapely", _shapely)
sys.modules.setdefault("shapely.geometry", _geometry)

sys.modules.setdefault(
    "debug_utils",
    types.SimpleNamespace(
        debug_log=lambda *args, **kwargs: None,
        log_http_response=lambda *args, **kwargs: None,
        log_api_failure=lambda *args, **kwargs: None,
    ),
)

from assign_cape_from_forecast import (
    _find_nearest_cape_ts,
    _parse_cape_ts,
    assign_cape,
)


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


def test_find_nearest_cape_ts_respects_three_hour_tolerance():
    target = datetime(2026, 6, 2, 4, 0, tzinfo=timezone.utc)
    available = [
        datetime(2026, 6, 2, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 6, 2, 6, 0, tzinfo=timezone.utc),
        datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc),
    ]
    assert _find_nearest_cape_ts(target, available) == available[1]
    assert _find_nearest_cape_ts(
        target,
        [datetime(2026, 6, 2, 8, 0, tzinfo=timezone.utc)],
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
