"""
tests/test_b126_accuracy_health_quiet.py

B126: classify_zero_sample_health unterscheidet Schönwetter von Defekt.
  - keine Zellen            → no_cells_quiet (info)
  - Zellen ohne forecast_*  → missing_forecast_fields (warning)
  - Zellen mit forecast_*    → zero_samples_despite_forecast (warning)

Ausführbar: python3 -m pytest tests/test_b126_accuracy_health_quiet.py -v
"""
import os
import sys
import json
import types
import importlib
from datetime import datetime


sys.modules.setdefault("cv2", types.ModuleType("cv2"))
_debug_utils_stub = types.ModuleType("debug_utils")
_debug_utils_stub.debug_log = lambda *args, **kwargs: None
sys.modules.setdefault("debug_utils", _debug_utils_stub)


def _write_objs(d, objs):
    name = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    with open(os.path.join(d, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(objs, f)


def test_no_cells_is_quiet_info(tmp_path):
    at = importlib.import_module("accuracy_tracker")
    _write_objs(str(tmp_path), [])          # leerer Frame = keine Zellen
    res = at.classify_zero_sample_health(str(tmp_path), since_hours=24)
    assert res["event"] == "no_cells_quiet"
    assert res["severity"] == "info"
    assert res["total_cells"] == 0


def test_cells_without_forecast_is_defect(tmp_path):
    at = importlib.import_module("accuracy_tracker")
    _write_objs(str(tmp_path), [{"id": 1, "lat": 46.6, "lon": 14.3}])
    res = at.classify_zero_sample_health(str(tmp_path), since_hours=24)
    assert res["event"] == "missing_forecast_fields"
    assert res["severity"] == "warning"
    assert res["total_cells"] == 1
    assert res["cells_with_forecast"] == 0


def test_cells_with_forecast_is_matching_warn(tmp_path):
    at = importlib.import_module("accuracy_tracker")
    _write_objs(str(tmp_path), [{"id": 1, "lat": 46.6, "lon": 14.3,
                                 "forecast_lat_10": 46.7, "forecast_lon_10": 14.4}])
    res = at.classify_zero_sample_health(str(tmp_path), since_hours=24)
    assert res["event"] == "zero_samples_despite_forecast"
    assert res["severity"] == "warning"
    assert res["cells_with_forecast"] == 1


def test_old_files_ignored(tmp_path):
    at = importlib.import_module("accuracy_tracker")
    # Datei mit altem Zeitstempel (außerhalb 24h) → ignoriert → no_cells_quiet
    old = "2000-01-01_00-00-00.json"
    with open(os.path.join(str(tmp_path), old), "w", encoding="utf-8") as f:
        json.dump([{"id": 9, "lat": 46.6, "lon": 14.3}], f)
    res = at.classify_zero_sample_health(str(tmp_path), since_hours=24)
    assert res["total_cells"] == 0
    assert res["event"] == "no_cells_quiet"
