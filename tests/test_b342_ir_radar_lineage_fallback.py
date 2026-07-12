"""B342: Silent-Fallback bei IR->Radar-Score-Matching wird jetzt persistiert
(nicht nur debug_log)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cell_lineage


def test_record_lineage_fallback_error_writes_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr(cell_lineage, "_state_dir", lambda: tmp_path)
    exc = RuntimeError("boom")
    cell_lineage.record_lineage_fallback_error(exc, timestamp="2026-07-11_21-00-00")

    out_file = tmp_path / cell_lineage._IR_LINEAGE_FALLBACK_FILE
    assert out_file.exists()
    rec = json.loads(out_file.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert rec["exception_type"] == "RuntimeError"
    assert "boom" in rec["exception_message"]
    assert rec["timestamp"] == "2026-07-11_21-00-00"


def test_main_calls_fallback_logger_on_exception():
    with open("main.py", encoding="utf-8") as f:
        src = f.read()
    assert "record_lineage_fallback_error" in src, "main.py muss den Fallback-Logger aufrufen"
