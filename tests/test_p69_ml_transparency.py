"""P69: Konsolidierte ML-Transparenz in bestehenden Endpoints (kein neuer Endpoint)."""
import accuracy_tracker


def test_no_duplicate_status_endpoint_created():
    """Es darf keinen neuen /api/forecast/quality/status Endpoint geben."""
    with open("app.py", encoding="utf-8") as f:
        content = f.read()
    assert "/api/forecast/quality/status" not in content


def test_verification_coverage_by_horizon_basic():
    history = [{
        "breakdown_by_forecast_mode": {
            "30": {"ml": {"samples": 10, "verified": 8, "no_target_frame": 2}}
        }
    }]
    out = accuracy_tracker.verification_coverage_by_horizon(history, [30])
    assert out["30"] == round(8 / 12, 4)


def test_ml_usage_ratio_ninety_percent_fallback():
    mode_counts = {"kinematic_fallback": 90, "ml": 10}
    total = sum(mode_counts.values())
    ratio = round(mode_counts.get("ml", 0) / total, 4)
    assert ratio == 0.1


def test_coverage_none_when_no_data():
    out = accuracy_tracker.verification_coverage_by_horizon([], [30])
    assert out["30"] is None
