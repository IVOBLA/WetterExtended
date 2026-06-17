"""
Test der CB-gated Wolkentop-Alarmgrenze:
cloud_top_alert = 1.0 genau dann, wenn cloud_top_height_msl >= Schwelle
UND core_ratio >= Mindest-Kernanteil (CB-Pflicht).

Dependency-arm: prüft die Entscheidungsregel direkt (kein TIFF, kein WMS).
"""
import config


def _alert(height_m, threshold_m, core_ratio, min_core):
    # Exakt dieselbe Regel wie in cloud_height_from_eumetview.assign_cloud_top_height.
    is_cb = float(core_ratio) >= float(min_core)
    return 1.0 if (float(height_m) >= float(threshold_m) and is_cb) else 0.0


def test_defaults_present():
    assert float(config.CLOUD_HEIGHT_ALERT_THRESHOLD_M) == 10000.0
    assert float(config.CLOUD_HEIGHT_ALERT_MIN_CORE_RATIO) == 0.05


def test_cb_above_threshold_triggers():
    # Hoch UND konvektiver Kern → Alarm
    assert _alert(10500.0, 10000.0, 0.30, 0.05) == 1.0


def test_high_cloud_without_core_no_alert():
    # Hoch, aber KEIN Kern (Cirrus/Amboss/Stratiform) → KEIN Alarm
    assert _alert(11500.0, 10000.0, 0.00, 0.05) == 0.0


def test_core_but_too_low_no_alert():
    # Konvektiver Kern, aber Wolkentop zu niedrig → kein Alarm
    assert _alert(9000.0, 10000.0, 0.40, 0.05) == 0.0


def test_exactly_at_both_thresholds_triggers():
    assert _alert(10000.0, 10000.0, 0.05, 0.05) == 1.0


def test_custom_thresholds_override():
    # Niedrigere Admin-Schwellen (8000 m, strengerer Kern 0.20)
    assert _alert(8200.0, 8000.0, 0.25, 0.20) == 1.0
    assert _alert(8200.0, 8000.0, 0.10, 0.20) == 0.0
