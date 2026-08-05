"""B491: forecast_outliers im Diagnose-Export enthielt kein forecast_mode/match_type/
lineage_status, obwohl diese Felder in forecast_error_details.jsonl bereits vorliegen.
Ohne sie war nicht feststellbar, ob ein Positions-Bias am kinematischen Fallback oder
am ML-Pfad liegt (KI-Befund 31.07.2026)."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.diagnose_forecast_quality import build_diagnosis  # noqa: E402


def test_forecast_outliers_expose_mode_and_lineage(tmp_path):
    eval_dir = tmp_path / "train_data" / "evaluation"
    eval_dir.mkdir(parents=True)
    # B505: _read_jsonl() filtert dieses Fenster ueber forecast_created_at_utc
    # relativ zu datetime.now(timezone.utc) (hours=24 im Aufruf unten). Ein
    # hartcodiertes absolutes Datum faellt zwangslaeufig irgendwann aus diesem
    # Fenster — deshalb hier relativ zu "jetzt" berechnet, damit der Test dauerhaft
    # unabhaengig vom tatsaechlichen Ausfuehrungsdatum gruen bleibt.
    forecast_created = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    verified_at = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = {
        "cell_id": "WX-TEST-0001", "forecast_error_km": 25.0,
        "forecast_lat": 46.6, "forecast_lon": 14.5,
        "actual_lat": 46.4, "actual_lon": 14.3,
        "horizon_min": 60, "forecast_created_at_utc": forecast_created,
        "verified_at_utc": verified_at,
        "forecast_mode": "kinematic", "match_type": "lineage",
        "lineage_status": "continued",
    }
    (eval_dir / "forecast_error_details.jsonl").write_text(json.dumps(row) + "\n")
    diagnosis = build_diagnosis(tmp_path, hours=24, evaluation_dir=eval_dir)
    assert diagnosis["forecast_outliers"], "kein Outlier im Testfall erkannt"
    o = diagnosis["forecast_outliers"][0]
    assert o["forecast_mode"] == "kinematic"
    assert o["match_type"] == "lineage"
    assert o["lineage_status"] == "continued"
