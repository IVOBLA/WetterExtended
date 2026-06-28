"""B256: api_call_counts.jsonl kappt große Response-Bodies, kleine bleiben vollständig."""
import json

import config
import debug_utils


def _read_last(path):
    with open(path, encoding="utf-8") as f:
        lines = [l for l in f if l.strip()]
    return json.loads(lines[-1])


def test_large_json_body_truncated(tmp_path, monkeypatch):
    ev = tmp_path / "eval"
    ev.mkdir()
    monkeypatch.setitem(config.SAVE_PATHS, "evaluation", str(ev))

    big = {"features": [{"i": i, "v": "x" * 100} for i in range(5000)]}
    debug_utils.log_api_call(
        "t", "https://example.invalid/big", 200,
        response_payload=big, content_type="application/json",
    )

    rec = _read_last(str(ev / "api_call_counts.jsonl"))
    assert rec["response"]["truncated"] is True
    assert rec["response"]["body_json"] is None
    assert rec["response"]["body_text"].endswith("…[gekürzt]")
    assert len(rec["response"]["body_text"].encode("utf-8")) <= debug_utils.API_LOG_MAX_BODY_BYTES + 64


def test_small_json_body_kept(tmp_path, monkeypatch):
    ev = tmp_path / "eval"
    ev.mkdir()
    monkeypatch.setitem(config.SAVE_PATHS, "evaluation", str(ev))

    small = {"ok": True, "n": 3}
    debug_utils.log_api_call(
        "t", "https://example.invalid/small", 200,
        response_payload=small, content_type="application/json",
    )

    rec = _read_last(str(ev / "api_call_counts.jsonl"))
    assert rec["response"]["truncated"] is False
    assert rec["response"]["body_json"] == {"ok": True, "n": 3}
