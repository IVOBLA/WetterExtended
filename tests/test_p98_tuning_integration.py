"""P98 — Autonomes Tuning: Sandbox + Scheduler-Integration."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_service_has_train_data_write_access():
    t = (REPO / "wetterprojekt-local-analysis.service").read_text(encoding="utf-8")
    assert "ReadWritePaths=/home/ki-pi/wetterprojekt/train_data" in t
    assert "ReadWritePaths=/home/ki-pi/wetterprojekt/train_data/evaluation" not in t


def test_service_still_has_env_protection():
    t = (REPO / "wetterprojekt-local-analysis.service").read_text(encoding="utf-8")
    assert "InaccessiblePaths=" in t and ".env" in t


def test_dispatch_calls_verify_before_analysis():
    t = (REPO / "tools/nightly_analysis_dispatch.sh").read_text(encoding="utf-8")
    v = t.index('tuning_apply.py" --verify')
    s = t.index("systemctl start wetterprojekt-local-analysis.service")
    assert v < s


def test_dispatch_calls_apply_after_analysis():
    t = (REPO / "tools/nightly_analysis_dispatch.sh").read_text(encoding="utf-8")
    s = t.index("systemctl start wetterprojekt-local-analysis.service")
    a = t.index('tuning_apply.py" --apply')
    assert a > s


def test_dispatch_tuning_calls_are_non_fatal():
    t = (REPO / "tools/nightly_analysis_dispatch.sh").read_text(encoding="utf-8")
    for call in ("--verify", "--apply"):
        idx = t.index(f'tuning_apply.py" {call}')
        line_end = t.index("\n", idx)
        assert "|| true" in t[idx:line_end]
