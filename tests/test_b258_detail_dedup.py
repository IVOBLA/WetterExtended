"""B258: forecast_error_details-Keys bleiben über Läufe hinweg dedupliziert (kein Re-Append)."""
import accuracy_tracker as at


def _rec():
    return {
        "forecast_created_at_utc": "2026-06-26T03:05:00Z",
        "target_timestamp_utc": "2026-06-26T03:15:00Z",
        "horizon_min": 10,
        "object_id": "OBJ1", "cell_id": "WX-TEST-0001",
        "forecast_lat": 46.40, "forecast_lon": 13.40,
        "actual_lat": 46.41, "actual_lon": 13.41,
        "match_type": "id",
    }


def test_no_reappend_across_runs(tmp_path):
    path = str(tmp_path / "forecast_error_details.jsonl")

    # Lauf 1: leere Datei → Key wird neu angehängt
    seen1 = at._load_detail_keys(path)
    assert at._append_detail_once(path, _rec(), seen1) is True

    # Lauf 2: neuer Lauf lädt Keys aus Datei → kein erneutes Anhängen
    seen2 = at._load_detail_keys(path)
    assert at._append_detail_once(path, _rec(), seen2) is False

    with open(path, encoding="utf-8") as f:
        lines = [l for l in f if l.strip()]
    assert len(lines) == 1


def test_distinct_forecast_still_appended(tmp_path):
    path = str(tmp_path / "forecast_error_details.jsonl")
    seen = at._load_detail_keys(path)
    assert at._append_detail_once(path, _rec(), seen) is True

    other = _rec()
    other["horizon_min"] = 20  # anderer Horizont → eigener Key
    seen2 = at._load_detail_keys(path)
    assert at._append_detail_once(path, other, seen2) is True

    with open(path, encoding="utf-8") as f:
        lines = [l for l in f if l.strip()]
    assert len(lines) == 2
