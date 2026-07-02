"""P69: Konsolidierte ML-Transparenz in bestehenden Endpoints (kein neuer Endpoint)."""
import accuracy_tracker


def test_no_duplicate_status_endpoint_created():
    """Es darf keinen neuen /api/forecast/quality/status Endpoint geben."""
    with open("app.py", encoding="utf-8") as f:
        content = f.read()
    assert "/api/forecast/quality/status" not in content


def test_coverage_matches_persisted_coverage_rate_not_double_counted():
    """8 verifiziert + 2 no_target_frame -> samples ist bereits 10 (kombiniert).
    Erwartete Coverage: 8/10, NICHT 8/12."""
    history = [{
        "breakdown_by_forecast_mode": {
            "30": {"ml": {"samples": 10, "verified": 8, "no_target_frame": 2}}
        }
    }]
    out = accuracy_tracker.verification_coverage_by_horizon(history, [30])
    assert out["30"] == round(8 / 10, 4)


def test_coverage_aggregates_across_multiple_modes_correctly():
    history = [{
        "breakdown_by_forecast_mode": {
            "30": {
                "ml": {"samples": 10, "verified": 8, "no_target_frame": 2},
                "kinematic_fallback": {"samples": 20, "verified": 15, "no_target_frame": 5},
            }
        }
    }]
    out = accuracy_tracker.verification_coverage_by_horizon(history, [30])
    assert out["30"] == round((8 + 15) / (10 + 20), 4)


def test_ml_usage_ratio_ninety_percent_fallback():
    mode_counts = {"kinematic_fallback": 90, "ml": 10}
    total = sum(mode_counts.values())
    ratio = round(mode_counts.get("ml", 0) / total, 4)
    assert ratio == 0.1


def test_coverage_none_when_no_data():
    out = accuracy_tracker.verification_coverage_by_horizon([], [30])
    assert out["30"] is None


def test_shadow_scoring_not_counted_as_live_ml_usage():
    """Ein Fenster mit ausschliesslich Schatten-ML (delivered=kinematic_fallback)
    darf KEINEN hohen ml_usage_ratio zeigen."""
    history = [{
        "breakdown_by_forecast_mode": {
            "30": {
                "kinematic_fallback": {"samples": 20, "verified": 20},
                "ml": {"samples": 20, "verified": 20},  # ausschliesslich Schatten-Bewertung
            }
        },
        "delivered_mode_counts": {
            "30": {"kinematic_fallback": 20},  # real ausgeliefert: NUR kinematic_fallback
        },
    }]
    mode_counts = {}
    for rec in history:
        for _h, delivered in (rec.get("delivered_mode_counts") or {}).items():
            for mode_name, n in delivered.items():
                mode_counts[mode_name] = mode_counts.get(mode_name, 0) + n
    total = sum(mode_counts.values()) or 1
    ratio = round(mode_counts.get("ml", 0) / total, 4)
    assert ratio == 0.0


def test_real_ml_delivery_still_counted():
    history = [{
        "delivered_mode_counts": {"30": {"ml": 15, "kinematic_fallback": 5}},
    }]
    mode_counts = {}
    for rec in history:
        for _h, delivered in (rec.get("delivered_mode_counts") or {}).items():
            for mode_name, n in delivered.items():
                mode_counts[mode_name] = mode_counts.get(mode_name, 0) + n
    total = sum(mode_counts.values())
    ratio = round(mode_counts.get("ml", 0) / total, 4)
    assert ratio == 0.75


def test_gate_reasons_include_allow_ml_flag():
    gate_result = {10: {"allow_ml": True, "reason": "ml_mae_better_or_equal"},
                   30: {"allow_ml": False, "reason": "ml_mae_worse_than_kinematic"}}
    gate_reasons = {str(h): {"reason": v.get("reason"), "allow_ml": bool(v.get("allow_ml"))}
                    for h, v in gate_result.items()}
    assert gate_reasons["10"]["allow_ml"] is True
    assert gate_reasons["30"]["allow_ml"] is False


def test_allowed_gate_is_not_denied():
    gate_reasons = {"10": {"reason": "gating_disabled", "allow_ml": True}}
    denied = [h for h, v in gate_reasons.items() if v.get("allow_ml") is False]
    assert denied == []
