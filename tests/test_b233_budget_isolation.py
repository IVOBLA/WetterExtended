# tests/test_b233_budget_isolation.py
"""B233 — api_budget_guard._BUDGET_FILE wird pro Test ins tmp umgelenkt, damit
Phase-9-Tests nicht das echte train_data/evaluation/api_budget.json hochzaehlen."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_budget_file_redirected_to_tmp(tmp_path):
    import api_budget_guard as abg
    expected = str(tmp_path / "train_data" / "evaluation" / "api_budget.json")
    assert abg._BUDGET_FILE == expected


def test_record_request_writes_only_to_isolated_path(tmp_path):
    prod = os.path.join("train_data", "evaluation", "api_budget.json")
    existed_before = os.path.exists(prod)
    before_bytes = None
    before_stat = None
    if existed_before:
        with open(prod, "rb") as fh:
            before_bytes = fh.read()
        st = os.stat(prod)
        before_stat = (st.st_mtime_ns, st.st_size)

    import api_budget_guard as abg
    abg.record_request("t")
    assert os.path.exists(abg._BUDGET_FILE)
    assert os.path.abspath(abg._BUDGET_FILE) != os.path.abspath(prod)
    assert str(tmp_path) in os.path.abspath(abg._BUDGET_FILE)

    with open(abg._BUDGET_FILE, encoding="utf-8") as fh:
        state = json.load(fh)
    assert sum(int(v) for v in state.get("counts", {}).values()) >= 1

    if existed_before:
        with open(prod, "rb") as fh:
            assert fh.read() == before_bytes
        st = os.stat(prod)
        assert (st.st_mtime_ns, st.st_size) == before_stat
    else:
        assert not os.path.exists(prod)
