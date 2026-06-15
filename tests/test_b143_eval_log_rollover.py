"""B143: Alters-Rotation für evaluation-JSONL (keine Kürzung des 24h-Fensters)."""
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if "debug_utils" not in sys.modules:
    debug_utils_stub = types.ModuleType("debug_utils")
    debug_utils_stub.debug_log = lambda *args, **kwargs: None
    sys.modules["debug_utils"] = debug_utils_stub

import cleanup_old_data


def _setup(monkeypatch, tmp_path):
    eval_dir = tmp_path / "train_data" / "evaluation"
    eval_dir.mkdir(parents=True)
    monkeypatch.setattr(cleanup_old_data, "SAVE_PATHS", {"evaluation": str(eval_dir)})
    return eval_dir


def _z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def test_prune_drops_old_keeps_recent(monkeypatch, tmp_path):
    eval_dir = _setup(monkeypatch, tmp_path)
    now = datetime.now(timezone.utc)
    p = eval_dir / "api_call_counts.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": _z(now - timedelta(hours=60)), "service": "old"}) + "\n")   # > 48h
        f.write(json.dumps({"ts": _z(now - timedelta(hours=10)), "service": "recent"}) + "\n") # < 48h
        f.write("nicht-parsebar\n")                                                            # behalten

    removed = cleanup_old_data._prune_eval_jsonl_by_age("api_call_counts.jsonl", 48)
    assert removed == 1
    lines = p.read_text(encoding="utf-8").splitlines()
    assert any("recent" in l for l in lines)
    assert not any("old" in l for l in lines)
    assert any(l == "nicht-parsebar" for l in lines), "nicht parsebare Zeilen müssen behalten werden"


def test_prune_keeps_full_24h_window(monkeypatch, tmp_path):
    eval_dir = _setup(monkeypatch, tmp_path)
    now = datetime.now(timezone.utc)
    p = eval_dir / "api_call_counts.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for h in range(0, 24):  # jede Stunde der letzten 24h
            f.write(json.dumps({"ts": _z(now - timedelta(hours=h)), "service": f"h{h}"}) + "\n")

    cleanup_old_data._prune_eval_jsonl_by_age("api_call_counts.jsonl", 48)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 24, "Das 24h-Fenster darf NICHT gekürzt werden"


def test_prune_disabled_when_zero(monkeypatch, tmp_path):
    eval_dir = _setup(monkeypatch, tmp_path)
    p = eval_dir / "api_call_counts.jsonl"
    p.write_text(json.dumps({"ts": "2000-01-01T00:00:00Z"}) + "\n", encoding="utf-8")
    assert cleanup_old_data._prune_eval_jsonl_by_age("api_call_counts.jsonl", 0) == 0
    assert p.read_text(encoding="utf-8")  # unverändert


def test_prune_handles_ts_utc_key(monkeypatch, tmp_path):
    eval_dir = _setup(monkeypatch, tmp_path)
    now = datetime.now(timezone.utc)
    p = eval_dir / "api_health.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts_utc": _z(now - timedelta(hours=72))}) + "\n")
        f.write(json.dumps({"ts_utc": _z(now - timedelta(hours=1))}) + "\n")
    removed = cleanup_old_data._prune_eval_jsonl_by_age("api_health.jsonl", 48)
    assert removed == 1
