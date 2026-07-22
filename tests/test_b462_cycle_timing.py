"""B462: Zyklusdauer wird persistiert (letzte + gleitender Mittelwert)."""
import json
import ast
from datetime import datetime, timezone
from pathlib import Path
import os


def _load_record_cycle_timing():
    """Lädt nur den Helper, ohne die optionalen Laufzeit-Abhängigkeiten von main."""
    source = Path("main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    helper = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_record_cycle_timing"
    )
    namespace = {
        "SAVE_PATHS": {},
        "os": os,
        "json": json,
        "datetime": datetime,
        "timezone": timezone,
    }
    exec(compile(ast.Module(body=[helper], type_ignores=[]), "main.py", "exec"), namespace)
    return namespace


def test_record_cycle_timing_writes_and_averages(monkeypatch, tmp_path):
    main = _load_record_cycle_timing()
    monkeypatch.setitem(main["SAVE_PATHS"], "status", str(tmp_path))
    main["_record_cycle_timing"](12.5, cells_active=True)
    main["_record_cycle_timing"](7.5, cells_active=True)
    doc = json.loads((tmp_path / "cycle_timing.json").read_text(encoding="utf-8"))
    assert doc["last_duration_s"] == 7.5
    assert doc["avg_duration_s"] == 10.0
    assert doc["max_duration_s"] == 12.5
    assert doc["sample_count"] == 2
    assert doc["cells_active"] is True
    assert doc["recent_durations_s"] == [12.5, 7.5]


def test_record_cycle_timing_caps_history_at_20(monkeypatch, tmp_path):
    main = _load_record_cycle_timing()
    monkeypatch.setitem(main["SAVE_PATHS"], "status", str(tmp_path))
    for i in range(25):
        main["_record_cycle_timing"](float(i), cells_active=False)
    doc = json.loads((tmp_path / "cycle_timing.json").read_text(encoding="utf-8"))
    assert doc["sample_count"] == 20
    assert doc["recent_durations_s"][0] == 5.0   # 0..4 verdraengt
    assert doc["recent_durations_s"][-1] == 24.0
