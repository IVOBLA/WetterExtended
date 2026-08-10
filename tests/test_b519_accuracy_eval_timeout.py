"""B519: accuracy_eval selbstbegrenzend — killbarer Subprozess-Timeout + Statusmarker."""
import json
import os
import time
import importlib

import accuracy_tracker as at


# --- top-level Worker-Funktionen (picklebar fuer fork/spawn) -------------------
def _fast_ok(horizons, since_hours=24):
    return {"horizons": [{"horizon": h, "samples": 1, "verified": 1, "mae_km": 1.0} for h in horizons]}


def _slow(horizons, since_hours=24):
    time.sleep(30)  # laenger als der Test-Timeout
    return {"horizons": []}


def _boom(horizons, since_hours=24):
    raise RuntimeError("kaputt")


def test_b519_ok_returns_result_and_writes_status(tmp_path, monkeypatch):
    monkeypatch.setitem(at.SAVE_PATHS, "evaluation", str(tmp_path))
    state, result = at.evaluate_all_bounded([10, 20], since_hours=24, timeout_s=20, fn=_fast_ok)
    assert state == "ok"
    assert isinstance(result, dict) and len(result["horizons"]) == 2
    p = at.write_accuracy_eval_status("ok", duration_s=1.2)
    assert os.path.exists(p)
    assert json.load(open(p))["state"] == "ok"


def test_b519_overrun_terminates_child_within_grace(tmp_path, monkeypatch):
    monkeypatch.setitem(at.SAVE_PATHS, "evaluation", str(tmp_path))
    t0 = time.monotonic()
    state, result = at.evaluate_all_bounded([10], since_hours=24, timeout_s=2, fn=_slow)
    elapsed = time.monotonic() - t0
    assert state == "overrun"
    assert result is None
    assert elapsed < 20, f"overrun-Rueckkehr zu langsam: {elapsed:.1f}s"


def test_b519_child_error_is_reported_not_hung(tmp_path, monkeypatch):
    monkeypatch.setitem(at.SAVE_PATHS, "evaluation", str(tmp_path))
    state, payload = at.evaluate_all_bounded([10], since_hours=24, timeout_s=20, fn=_boom)
    assert state == "failed"
    assert "RuntimeError" in str(payload)


def test_b519_status_writer_atomic(tmp_path, monkeypatch):
    monkeypatch.setitem(at.SAVE_PATHS, "evaluation", str(tmp_path))
    p = at.write_accuracy_eval_status("overrun", duration_s=99.0, horizons=[10, 20])
    rec = json.load(open(p))
    assert rec["state"] == "overrun" and rec["duration_s"] == 99.0
    assert not os.path.exists(p + ".tmp")
