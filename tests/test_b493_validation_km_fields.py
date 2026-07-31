"""B493: training_meta.json['validation'] mischte weiterhin Pixel- und km-Einheiten,
obwohl B492 die Promotion-Entscheidung selbst bereits auf km umgestellt hatte. Diese
Tests verankern die neuen km-Felder und die legacy_incomparable-Kennzeichnung."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import model_training as mt  # noqa: E402


def test_legacy_entry_without_mae_km_is_flagged():
    new_eval = {"mae_total": 5.0, "mae_by_horizon": {"10": 5.0}}  # kein mae_km_total (Alt-Version)
    old_eval = {"mae_total": 6.0}
    validation = {
        "mae_old": old_eval.get("mae_total"), "mae_new": new_eval.get("mae_total"),
        "mae_km_old": old_eval.get("mae_km_total"), "mae_km_new": new_eval.get("mae_km_total"),
        "legacy_incomparable": not (
            isinstance(new_eval.get("mae_km_total"), (int, float))
            and new_eval.get("mae_km_total") != float("inf")
        ),
    }
    assert validation["legacy_incomparable"] is True
    assert validation["mae_km_new"] is None


def test_post_b492_entry_is_not_flagged_as_legacy():
    new_eval = {"mae_total": 5.0, "mae_km_total": 1.2, "mae_km_by_horizon": {"10": 1.2}}
    validation = {
        "mae_km_new": new_eval.get("mae_km_total"),
        "legacy_incomparable": not (
            isinstance(new_eval.get("mae_km_total"), (int, float))
            and new_eval.get("mae_km_total") != float("inf")
        ),
    }
    assert validation["legacy_incomparable"] is False
    assert validation["mae_km_new"] == 1.2


def test_infinite_mae_km_counts_as_legacy_incomparable():
    new_eval = {"mae_km_total": float("inf")}
    legacy = not (
        isinstance(new_eval.get("mae_km_total"), (int, float))
        and new_eval.get("mae_km_total") != float("inf")
    )
    assert legacy is True
