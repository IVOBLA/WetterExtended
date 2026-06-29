"""B257 — tools/diagnose_forecast_quality.py: liest accuracy_history im
neuen verschachtelten Format (horizons-Array) UND im alten Flat-Format."""
import importlib
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _import_dfq():
    try:
        return importlib.import_module("tools.diagnose_forecast_quality")
    except Exception as exc:
        pytest.skip(f"tools.diagnose_forecast_quality nicht importierbar: {exc}")


def _write_history(path: Path, entries: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _now_utc():
    return datetime.now(timezone.utc)


def test_new_nested_format_is_read_correctly(tmp_path):
    dfq = _import_dfq()
    hist = tmp_path / "accuracy_history.jsonl"
    now = _now_utc()
    entry = {
        "timestamp_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "since_hours": 24,
        "tolerance_km": 1.0,
        "horizons": [
            {"horizon": 10, "mae_km": 1.2, "samples": 5, "hit_rate": 0.8},
            {"horizon": 20, "mae_km": 2.1, "samples": 4, "hit_rate": 0.75},
        ],
    }
    _write_history(hist, [entry])

    rows = dfq._read_accuracy_history_horizons(hist, hours=24)
    assert len(rows) == 2, f"Erwartet 2 Horizont-Einträge, erhalten {len(rows)}"
    h10 = next((r for r in rows if r.get("horizon") == 10), None)
    assert h10 is not None, "Horizont 10 nicht gefunden"
    assert h10["mae_km"] == pytest.approx(1.2)
    assert h10["samples"] == 5


def test_old_flat_format_still_works(tmp_path):
    dfq = _import_dfq()
    hist = tmp_path / "accuracy_history.jsonl"
    now = _now_utc()
    entry = {
        "timestamp_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "horizon": 10,
        "mae_km": 0.9,
        "samples": 8,
    }
    _write_history(hist, [entry])

    rows = dfq._read_accuracy_history_horizons(hist, hours=24)
    assert len(rows) == 1
    assert rows[0]["horizon"] == 10
    assert rows[0]["mae_km"] == pytest.approx(0.9)


def test_old_entries_outside_window_excluded(tmp_path):
    dfq = _import_dfq()
    hist = tmp_path / "accuracy_history.jsonl"
    old = (_now_utc() - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {
        "timestamp_utc": old,
        "horizons": [{"horizon": 10, "mae_km": 5.0, "samples": 3}],
    }
    _write_history(hist, [entry])

    rows = dfq._read_accuracy_history_horizons(hist, hours=24)
    assert len(rows) == 0, "Alter Eintrag (außerhalb 24h) darf nicht enthalten sein"


def test_entry_without_horizons_ignored(tmp_path):
    dfq = _import_dfq()
    hist = tmp_path / "accuracy_history.jsonl"
    now = _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    # Kein horizon-Feld, kein horizons-Array
    entry = {"timestamp_utc": now, "since_hours": 24}
    _write_history(hist, [entry])

    rows = dfq._read_accuracy_history_horizons(hist, hours=24)
    assert len(rows) == 0, "Eintrag ohne horizon-Daten darf nicht enthalten sein"


def test_model_usage_populated_with_nested_format(tmp_path):
    """model_usage in build_diagnosis darf nicht 'not_available' zeigen
    wenn Horizon-Daten im neuen Format vorhanden sind."""
    dfq = _import_dfq()
    ev = tmp_path / "train_data" / "evaluation"
    ev.mkdir(parents=True)
    now = _now_utc()
    hist_entry = {
        "timestamp_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "since_hours": 24,
        "horizons": [
            {"horizon": 10, "mae_km": 1.5, "samples": 10, "hit_rate": 0.7},
        ],
    }
    _write_history(ev / "accuracy_history.jsonl", [hist_entry])
    (ev / "forecast_error_details.jsonl").write_text("", encoding="utf-8")

    result = dfq.build_diagnosis(tmp_path, hours=24, evaluation_dir=ev)
    model_usage = result.get("model_usage", {})
    assert model_usage.get("status") != "not_available", \
        f"model_usage zeigt 'not_available' obwohl Daten vorhanden: {model_usage}"
