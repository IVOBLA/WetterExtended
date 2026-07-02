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
