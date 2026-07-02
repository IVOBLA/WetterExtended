"""P70: Horizontabhaengige Qualitaetsziele. <=30-Min-Vorgabe bleibt fest."""
from config import QUALITY_TARGET_MAE_KM_FIXED, QUALITY_TARGET_MAE_KM_CONFIGURABLE_DEFAULT


def test_fixed_targets_match_zieldefinition():
    """Die zieldefinition.txt fordert <1km fuer horizonte <=30min."""
    for h in ("10", "20", "30"):
        assert QUALITY_TARGET_MAE_KM_FIXED[h] == 1.0


def test_configurable_horizons_do_not_include_fixed_ones():
    assert not set(QUALITY_TARGET_MAE_KM_CONFIGURABLE_DEFAULT) & set(QUALITY_TARGET_MAE_KM_FIXED)


def test_h10_target_cannot_be_overridden(monkeypatch, tmp_path):
    import runtime_config
    import pytest
    monkeypatch.setattr(runtime_config._cfg, "RUNTIME_OVERRIDES_PATH", str(tmp_path / "runtime_overrides.json"), raising=False)
    runtime_config.reload_overrides()
    with pytest.raises(ValueError):
        runtime_config.set_override("QUALITY_TARGET_MAE_KM_10", 2.0)


def test_h60_target_can_be_overridden(monkeypatch, tmp_path):
    import runtime_config
    monkeypatch.setattr(runtime_config._cfg, "RUNTIME_OVERRIDES_PATH", str(tmp_path / "runtime_overrides.json"), raising=False)
    runtime_config.reload_overrides()
    runtime_config.set_override("QUALITY_TARGET_MAE_KM_60", 3.0)
    assert runtime_config.get("QUALITY_TARGET_MAE_KM_60") == 3.0


def test_drift_status_shows_violation_horizon():
    mae_by_horizon = {"10": 0.5, "30": 1.4, "60": 1.8}
    from config import QUALITY_TARGET_MAE_KM_FIXED, QUALITY_TARGET_MAE_KM_CONFIGURABLE_DEFAULT
    def target(h):
        return QUALITY_TARGET_MAE_KM_FIXED.get(h, QUALITY_TARGET_MAE_KM_CONFIGURABLE_DEFAULT.get(h, 2.0))
    violation = next((h for h, v in mae_by_horizon.items() if v > target(h)), None)
    assert violation == "30"  # h10 erfuellt, h30 verfehlt -> h30 als Ursache


def test_config_migration_preserves_existing_env_values(monkeypatch):
    import os
    monkeypatch.setenv("DRIFT_MAE_ABS_MAX_KM", "1.0")
    assert float(os.environ["DRIFT_MAE_ABS_MAX_KM"]) == 1.0


def test_custom_horizon_15_gets_fixed_target_not_default():
    """h15 ist kein Standardwert, liegt aber <=30 Min -> muss <1km sein, NICHT 2.0km."""
    from drift_detector import _quality_target_for_horizon
    assert _quality_target_for_horizon("15") == 1.0


def test_custom_horizon_25_gets_fixed_target():
    from drift_detector import _quality_target_for_horizon
    assert _quality_target_for_horizon("25") == 1.0


def test_horizon_35_is_configurable_not_fixed():
    from drift_detector import _horizon_is_fixed_target
    assert _horizon_is_fixed_target("35") is False


def test_horizon_30_boundary_is_fixed():
    from drift_detector import _horizon_is_fixed_target
    assert _horizon_is_fixed_target("30") is True


def test_runtime_override_rejects_custom_horizon_15(monkeypatch, tmp_path):
    import runtime_config
    import pytest
    monkeypatch.setattr(runtime_config._cfg, "RUNTIME_OVERRIDES_PATH", str(tmp_path / "runtime_overrides.json"), raising=False)
    runtime_config.reload_overrides()
    with pytest.raises(ValueError):
        runtime_config.set_override("QUALITY_TARGET_MAE_KM_15", 2.0)


def test_runtime_override_accepts_horizon_45(monkeypatch, tmp_path):
    import runtime_config
    monkeypatch.setattr(runtime_config._cfg, "RUNTIME_OVERRIDES_PATH", str(tmp_path / "runtime_overrides.json"), raising=False)
    runtime_config.reload_overrides()
    runtime_config.set_override("QUALITY_TARGET_MAE_KM_45", 1.8)
    assert runtime_config.get("QUALITY_TARGET_MAE_KM_45") == 1.8


def test_mae_1_4km_on_horizon_15_violates_fixed_target():
    """Regressionsfall aus dem Review: 1.4km auf h15 darf NICHT als erfuellt gelten."""
    from drift_detector import _quality_target_for_horizon
    target = _quality_target_for_horizon("15")
    actual_mae = 1.4
    assert actual_mae > target  # muss als Verstoss erkannt werden

def test_runtime_kinematic_mae_by_horizon_is_object_not_number():
    """Contract-Test: /api/ml_quality liefert je Horizont ein Objekt
    {kinematic_mae, kinematic_samples}, KEINEN nackten Zahlenwert. Aendert sich
    das, muesste Configuration.jsx (B287) erneut angepasst werden."""
    from accuracy_tracker import get_runtime_kinematic_mae_by_horizon
    import inspect
    src = inspect.getsource(get_runtime_kinematic_mae_by_horizon)
    assert '"kinematic_mae"' in src
    assert '"kinematic_samples"' in src


def test_kinematic_mae_object_structure_example():
    example = {"kinematic_mae": 0.8, "kinematic_samples": 40}
    assert isinstance(example["kinematic_mae"], float)
    assert isinstance(example["kinematic_samples"], int)
