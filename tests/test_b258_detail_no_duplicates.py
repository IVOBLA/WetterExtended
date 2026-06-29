"""B258 — forecast_error_details.jsonl: keine Duplikate bei mehrfachen
evaluate_for_horizon-Aufrufen durch persistente detail_keys_seen."""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _import_accuracy_tracker(monkeypatch, tmp_path):
    import importlib
    monkeypatch.chdir(tmp_path)
    # Isolation der SAVE_PATHS
    at = importlib.import_module("accuracy_tracker")
    monkeypatch.setattr(at, "EVAL_DIR", str(tmp_path / "eval"), raising=False)
    monkeypatch.setattr(at, "DETAILS_FILE",
                        str(tmp_path / "eval" / "forecast_error_details.jsonl"),
                        raising=False)
    monkeypatch.setattr(at, "HISTORY_FILE",
                        str(tmp_path / "eval" / "accuracy_history.jsonl"),
                        raising=False)
    monkeypatch.setitem(at.SAVE_PATHS, "objects", str(tmp_path / "objects"))
    monkeypatch.setitem(at.SAVE_PATHS, "evaluation", str(tmp_path / "eval"))
    (tmp_path / "objects").mkdir(parents=True, exist_ok=True)
    (tmp_path / "eval").mkdir(parents=True, exist_ok=True)
    return at


def _write_object_pair(obj_dir: Path, ts_forecast: datetime, ts_target: datetime,
                       horizon: int, cell_id: str = "WX-TEST-1"):
    """Schreibt Forecast-Frame und Ziel-Frame für einen Horizont."""
    def _ts(dt): return dt.strftime("%Y-%m-%d_%H-%M-%S")
    def _obj(oid): return {
        "id": oid, "cell_id": oid, "x": 10.0, "y": 20.0, "lat": 46.70, "lon": 14.10,
        f"forecast_x_{horizon}": 10.0, f"forecast_y_{horizon}": 20.0,
        f"forecast_lat_{horizon}": 46.70, f"forecast_lon_{horizon}": 14.10,
        f"forecast_mode_{horizon}": "kinematic",
        f"kinematic_source_{horizon}": "ewma_3f",
    }
    fc_file = obj_dir / f"{_ts(ts_forecast)}.json"
    tgt_file = obj_dir / f"{_ts(ts_target)}.json"
    fc_file.write_text(json.dumps([_obj(cell_id)]), encoding="utf-8")
    tgt_file.write_text(json.dumps([{"id": cell_id, "cell_id": cell_id,
                                     "x": 10.0, "y": 20.0, "lat": 46.70, "lon": 14.10}]),
                        encoding="utf-8")


def test_no_duplicates_on_second_scheduler_run(monkeypatch, tmp_path):
    """Zweiter evaluate_for_horizon-Aufruf schreibt keine Duplikate."""
    at = _import_accuracy_tracker(monkeypatch, tmp_path)
    t0 = datetime.utcnow() - timedelta(minutes=30)
    _write_object_pair(tmp_path / "objects", t0, t0 + timedelta(minutes=10), 10)

    # Erster Aufruf (wie erster Scheduler-Run)
    at.evaluate_for_horizon(10, since_hours=24)
    details_after_first = Path(at.DETAILS_FILE).read_text(encoding="utf-8").strip()
    lines_first = [l for l in details_after_first.splitlines() if l.strip()]
    count_first = len(lines_first)
    assert count_first >= 1, "Erster Lauf muss mindestens 1 Detail-Eintrag schreiben"

    # Zweiter Aufruf (wie nächster Scheduler-Run) — darf KEINE Duplikate schreiben
    at.evaluate_for_horizon(10, since_hours=24)
    details_after_second = Path(at.DETAILS_FILE).read_text(encoding="utf-8").strip()
    lines_second = [l for l in details_after_second.splitlines() if l.strip()]
    count_second = len(lines_second)

    assert count_second == count_first, (
        f"Zweiter Scheduler-Run schrieb {count_second - count_first} Duplikate "
        f"(vor: {count_first}, nach: {count_second})"
    )


def test_load_detail_keys_returns_correct_set(monkeypatch, tmp_path):
    """_load_detail_keys liest bestehende Schlüssel aus JSONL korrekt."""
    at = _import_accuracy_tracker(monkeypatch, tmp_path)
    details_path = tmp_path / "eval" / "forecast_error_details.jsonl"
    now = datetime.utcnow()

    rec = {
        "forecast_created_at_utc": (now - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target_timestamp_utc": (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verified_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "horizon_min": 10,
        "object_id": "WX-1", "cell_id": "WX-1",
        "forecast_lat": 46.7, "forecast_lon": 14.3,
        "actual_lat": 46.71, "actual_lon": 14.31,
        "match_type": "id",
    }
    details_path.parent.mkdir(parents=True, exist_ok=True)
    details_path.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    loaded_keys = at._load_detail_keys(str(details_path), since_hours=24)
    assert len(loaded_keys) == 1, f"Erwartet 1 Schlüssel, erhalten {len(loaded_keys)}"


def test_load_detail_keys_excludes_old_entries(monkeypatch, tmp_path):
    """Einträge außerhalb des since_hours-Fensters werden nicht in die Keys geladen."""
    at = _import_accuracy_tracker(monkeypatch, tmp_path)
    details_path = tmp_path / "eval" / "forecast_error_details.jsonl"
    old_time = (datetime.utcnow() - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")

    rec = {
        "forecast_created_at_utc": old_time,
        "target_timestamp_utc": old_time,
        "verified_at_utc": old_time,
        "horizon_min": 10, "object_id": "WX-OLD", "cell_id": "WX-OLD",
        "forecast_lat": 46.7, "forecast_lon": 14.3,
        "actual_lat": 46.71, "actual_lon": 14.31, "match_type": "id",
    }
    details_path.parent.mkdir(parents=True, exist_ok=True)
    details_path.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    loaded_keys = at._load_detail_keys(str(details_path), since_hours=24)
    assert len(loaded_keys) == 0, "Alter Eintrag (> 24h) darf nicht geladen werden"


def test_missing_details_file_returns_empty_set(monkeypatch, tmp_path):
    at = _import_accuracy_tracker(monkeypatch, tmp_path)
    nonexistent = str(tmp_path / "does_not_exist.jsonl")
    keys = at._load_detail_keys(nonexistent, since_hours=24)
    assert keys == set()
