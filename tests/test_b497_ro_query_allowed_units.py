import pytest

from tools.ro_query import ALLOWED_UNITS, QueryError, check_unit


def test_nightly_analysis_dispatcher_is_allowed():
    assert "wetterprojekt-nightly-analysis.service" in ALLOWED_UNITS


def test_deleted_local_analysis_timer_is_not_allowed():
    assert "wetterprojekt-local-analysis.timer" not in ALLOWED_UNITS


def test_existing_analysis_units_remain_allowed():
    assert "wetterprojekt-local-analysis.service" in ALLOWED_UNITS
    assert "wetterprojekt-debug-export-branch.timer" in ALLOWED_UNITS


def test_deleted_local_analysis_timer_is_rejected():
    with pytest.raises(QueryError):
        check_unit("wetterprojekt-local-analysis.timer")
