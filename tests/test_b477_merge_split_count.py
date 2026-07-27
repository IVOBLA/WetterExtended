"""B477 — Merges duerfen nicht mehr als Splits gezaehlt werden."""
import importlib.util
from pathlib import Path

import pytest

SA = Path(__file__).resolve().parents[1] / "stats_aggregator.py"
TS = "2026-06-01_12-00-00"


@pytest.fixture
def sa():
    spec = importlib.util.spec_from_file_location("sa_b477", SA)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rec(**kw):
    d = {"first_seen": TS}
    d.update(kw)
    return d


def test_merge_counts_only_as_merge(sa):
    years, grid = {}, {}
    sa._accumulate_record(_rec(end_reason="merged_into:C1", children=["C1"]), years, grid)
    y = years["2026"]
    assert y["merges"] == 1
    assert y["splits"] == 0, "Ein Merge (children==1) darf kein Split sein"


def test_split_needs_more_than_one_child(sa):
    years, grid = {}, {}
    sa._accumulate_record(_rec(end_reason="split_into:['A','B']", children=["A", "B"]), years, grid)
    y = years["2026"]
    assert y["splits"] == 1
    assert y["merges"] == 0


def test_mixed_counts_are_independent(sa):
    years, grid = {}, {}
    for _ in range(3):
        sa._accumulate_record(_rec(end_reason="merged_into:X", children=["X"]), years, grid)
    for _ in range(2):
        sa._accumulate_record(_rec(end_reason="split_into:['A','B']", children=["A", "B"]), years, grid)
    sa._accumulate_record(_rec(end_reason="dissipated"), years, grid)
    y = years["2026"]
    assert (y["merges"], y["splits"], y["cells_total"]) == (3, 2, 6)
