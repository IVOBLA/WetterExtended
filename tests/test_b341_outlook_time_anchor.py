"""B341: compute_outlook() verwirft bereits verstrichene Stunden und
ankert offset_h relativ zur aktuellen Uhrzeit statt am Serien-Index."""
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _build_series(points_hours):
    """points_hours: Liste von 'valid'-Strings fuer EINEN Grid-Punkt."""
    return {
        "points": [
            {
                "lat": 46.6, "lon": 14.3,
                "series": [{"valid": v, "cape": 500, "lifted_index": -2} for v in points_hours],
            }
        ]
    }


def test_stale_hours_are_dropped_and_offset_renumbered(tmp_path, monkeypatch):
    import convective_outlook

    now = datetime.now()
    # Serie: Stunde 1 und 2 liegen in der Vergangenheit (429-Fallback-Fall),
    # Stunde 3 liegt in der Zukunft.
    past1 = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
    past2 = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    future1 = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    series = _build_series([None, past1, past2, future1])  # Index 0 ungenutzt (h startet bei 1)

    series_file = tmp_path / "atmosphere_timeseries.json"
    series_file.write_text(json.dumps(series), encoding="utf-8")
    monkeypatch.setattr(convective_outlook, "_SERIES_FILE", str(series_file))
    monkeypatch.setattr(convective_outlook, "_bbox_limits", lambda: (46.6, 46.6, 14.3, 14.3))
    monkeypatch.setattr(convective_outlook, "_load_attractor", lambda: {})
    monkeypatch.setattr(convective_outlook, "_attractor_prior", lambda *a, **k: 0.0)
    monkeypatch.setattr(convective_outlook, "_cell_severity", lambda *a, **k: (0, None, {}))

    result = convective_outlook.compute_outlook()

    valids = [h["valid"] for h in result["hours"]]
    assert past1 not in valids and past2 not in valids, "vergangene Stunden duerfen nicht ausgegeben werden"
    if result["hours"]:
        assert result["hours"][0]["offset_h"] == 1, "offset_h muss nach dem Filtern ab 1 neu durchnummeriert werden"


def test_fully_stale_series_returns_stale_flag(tmp_path, monkeypatch):
    import convective_outlook

    now = datetime.now()
    past1 = (now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")
    past2 = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
    series = _build_series([None, past1, past2])

    series_file = tmp_path / "atmosphere_timeseries.json"
    series_file.write_text(json.dumps(series), encoding="utf-8")
    monkeypatch.setattr(convective_outlook, "_SERIES_FILE", str(series_file))
    monkeypatch.setattr(convective_outlook, "_bbox_limits", lambda: (46.6, 46.6, 14.3, 14.3))
    monkeypatch.setattr(convective_outlook, "_load_attractor", lambda: {})

    result = convective_outlook.compute_outlook()
    assert result["hours"] == []
    assert result.get("stale") is True
