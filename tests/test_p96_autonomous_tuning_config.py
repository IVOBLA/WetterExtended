"""P96 — Autonomes Tuning: Whitelist + Config-Infrastruktur (12 Parameter)."""
import config


def test_kill_switch_exists_and_defaults_to_off():
    assert hasattr(config, "AUTONOMOUS_TUNING_ENABLED")
    assert config.AUTONOMOUS_TUNING_ENABLED is False, "Kill-Switch muss default AUS sein"


def test_whitelist_exists_and_has_12_params():
    assert hasattr(config, "AUTONOMOUS_TUNING_PARAMS")
    assert isinstance(config.AUTONOMOUS_TUNING_PARAMS, dict)
    assert len(config.AUTONOMOUS_TUNING_PARAMS) == 12


def test_every_param_has_required_fields():
    for name, spec in config.AUTONOMOUS_TUNING_PARAMS.items():
        for field in ("min", "max", "step", "unit", "effect"):
            assert field in spec, f"{name}: Feld '{field}' fehlt"


def test_bounds_are_sane():
    for name, spec in config.AUTONOMOUS_TUNING_PARAMS.items():
        assert spec["min"] < spec["max"], f"{name}: min >= max"
        assert spec["step"] > 0, f"{name}: step <= 0"
        assert spec["step"] <= (spec["max"] - spec["min"]), \
            f"{name}: step groesser als gesamte Range"


def test_whitelisted_params_are_runtime_readable():
    """Jeder Whitelist-Key muss von prediction.py oder accuracy_tracker.py gelesen werden."""
    import pathlib
    root = pathlib.Path(config.__file__).parent
    sources = {}
    for fn in ("prediction.py", "accuracy_tracker.py"):
        p = root / fn
        if p.exists():
            sources[fn] = p.read_text(encoding="utf-8")
    for name in config.AUTONOMOUS_TUNING_PARAMS:
        found = any(f'"{name}"' in src for src in sources.values())
        assert found, f"{name} wird weder von prediction.py noch accuracy_tracker.py gelesen"


def test_no_safety_critical_params_in_whitelist():
    forbidden_substrings = ("WARN", "ALERT", "NOTIFY", "MAIL", "WHATSAPP",
                            "THRESHOLD_DBZ", "CELL_MIN", "CELL_MAX",
                            "UPSCALE_FACTOR", "ANALYSIS_MODE", "TOKEN", "SECRET",
                            "ENABLED", "FORCE_KINEMATIC")
    for name in config.AUTONOMOUS_TUNING_PARAMS:
        for frag in forbidden_substrings:
            assert frag not in name.upper(), \
                f"Sicherheitskritischer Parameter in Whitelist: {name} (enthaelt {frag})"


def test_kill_switch_is_runtime_overridable():
    import runtime_config
    assert "AUTONOMOUS_TUNING_ENABLED" not in runtime_config.forbidden_keys_in(
        {"AUTONOMOUS_TUNING_ENABLED": True})


def test_expected_params_present():
    expected = {
        "KINEMATIC_EWMA_ALPHA", "KINEMATIC_ACCEL_MAX_FRACTION",
        "KINEMATIC_MIN_INTERVAL_DISP_PX", "ML_RUNTIME_GATING_MARGIN",
        "ML_FORECAST_MAX_BEARING_DEVIATION_DEG",
        "FORECAST_CROSS_HORIZON_MAX_BEARING_JUMP_DEG",
        "STEERING_BLEND_WEIGHT", "STEERING_BLEND_MIN_WIND_KMH",
        "STEERING_BLEND_MIN_ANGLE_DEG", "STEERING_NEW_CELL_SPEED_FRAC",
        "OF_MAX_FRAME_INTERVAL_MIN", "VERIFICATION_NN_MAX_MATCH_KM",
    }
    actual = set(config.AUTONOMOUS_TUNING_PARAMS.keys())
    missing = expected - actual
    assert not missing, f"Fehlende Parameter: {missing}"
