"""B293: Diagnose-Status muss bei kleiner Stichprobe insufficient_data liefern."""
import importlib.util
import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "diagnose_forecast_quality", os.path.join(_ROOT, "tools", "diagnose_forecast_quality.py")
)
dfq = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dfq)


def _write_details(tmp_path, rows):
    ev = tmp_path / "train_data" / "evaluation"
    ev.mkdir(parents=True, exist_ok=True)
    with open(ev / "forecast_error_details.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    (ev / "accuracy_history.jsonl").write_text("", encoding="utf-8")
    return ev


def test_few_verified_forecasts_yield_insufficient_data(tmp_path):
    rows = [{"forecast_error_km": 1.67, "horizon_min": 10, "no_target_frame": False} for _ in range(3)]
    rows += [{"no_target_frame": True, "horizon_min": 10} for _ in range(3)]
    ev = _write_details(tmp_path, rows)
    out = dfq.build_diagnosis(tmp_path, hours=24, evaluation_dir=ev)
    assert out["status"] == "insufficient_data"


def test_high_missing_ratio_yields_insufficient_data(tmp_path):
    rows = [{"forecast_error_km": 5.0, "horizon_min": 10, "no_target_frame": False} for _ in range(40)]
    rows += [{"no_target_frame": True, "horizon_min": 10} for _ in range(60)]  # 60% missing
    ev = _write_details(tmp_path, rows)
    out = dfq.build_diagnosis(tmp_path, hours=24, evaluation_dir=ev)
    assert out["status"] == "insufficient_data"


def test_sufficient_data_yields_ok(tmp_path):
    rows = [{"forecast_error_km": 4.6, "horizon_min": 10, "no_target_frame": False} for _ in range(100)]
    ev = _write_details(tmp_path, rows)
    out = dfq.build_diagnosis(tmp_path, hours=24, evaluation_dir=ev)
    assert out["status"] == "ok"
