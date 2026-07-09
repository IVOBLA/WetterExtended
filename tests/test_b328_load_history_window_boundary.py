"""B328: load_history(since_hours=...) filtert korrekt nach relativer Zeit.
Regressionstest gegen erneute Zeitbomben durch fest verdrahtete absolute
Zeitstempel in Fixtures (siehe test_p69_existing_quality_endpoints_expose_transparency_fields,
das am 2026-07-09 durch genau dieses Problem fehlschlug)."""
from datetime import datetime, timedelta

import pytest


def test_record_innerhalb_fenster_wird_geliefert(monkeypatch, tmp_path):
    at = pytest.importorskip("accuracy_tracker")

    hist_file = tmp_path / "accuracy_history.jsonl"
    recent_ts = (datetime.utcnow() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hist_file.write_text(
        f'{{"timestamp_utc":"{recent_ts}","breakdown_by_forecast_mode":{{}}}}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(at, "HISTORY_FILE", str(hist_file))

    out = at.load_history(since_hours=168)
    assert len(out) == 1, "Ein Record 1h alt muss innerhalb eines 168h-Fensters geliefert werden."


def test_record_ausserhalb_fenster_wird_gefiltert(monkeypatch, tmp_path):
    at = pytest.importorskip("accuracy_tracker")

    hist_file = tmp_path / "accuracy_history.jsonl"
    old_ts = (datetime.utcnow() - timedelta(hours=200)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hist_file.write_text(
        f'{{"timestamp_utc":"{old_ts}","breakdown_by_forecast_mode":{{}}}}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(at, "HISTORY_FILE", str(hist_file))

    out = at.load_history(since_hours=168)
    assert out == [], "Ein Record 200h alt darf bei einem 168h-Fenster nicht geliefert werden."
