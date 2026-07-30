"""P96 — Autonomes Tuning: Whitelist + Config-Infrastruktur.

Prueft, dass die Whitelist korrekt definiert ist und alle Invarianten einhaelt.
"""
import config


def test_kill_switch_exists_and_defaults_to_off():
    assert hasattr(config, "AUTONOMOUS_TUNING_ENABLED")
    assert config.AUTONOMOUS_TUNING_ENABLED is False, "Kill-Switch muss default AUS sein"


def test_whitelist_exists_and_is_non_empty():
    assert hasattr(config, "AUTONOMOUS_TUNING_PARAMS")
    assert isinstance(config.AUTONOMOUS_TUNING_PARAMS, dict)
    assert len(config.AUTONOMOUS_TUNING_PARAMS) >= 3


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
    """Jeder Whitelist-Key muss von prediction.py via _runtime_*_value gelesen werden."""
    import pathlib
    pred = pathlib.Path(config.__file__).parent / "prediction.py"
    src = pred.read_text(encoding="utf-8")
    for name in config.AUTONOMOUS_TUNING_PARAMS:
        assert f'"{name}"' in src, \
            f"{name} wird nicht von prediction.py gelesen — Whitelist-Eintrag wirkungslos"


def test_no_safety_critical_params_in_whitelist():
    """Warnschwellen, Benachrichtigungen, Erkennungsschwellwerte gehoeren nicht hinein."""
    forbidden_substrings = ("WARN", "ALERT", "NOTIFY", "MAIL", "WHATSAPP",
                            "THRESHOLD_DBZ", "CELL_MIN", "CELL_MAX",
                            "UPSCALE_FACTOR", "ANALYSIS_MODE", "TOKEN", "SECRET")
    for name in config.AUTONOMOUS_TUNING_PARAMS:
        for frag in forbidden_substrings:
            assert frag not in name.upper(), \
                f"Sicherheitskritischer Parameter in Whitelist: {name}"


def test_kill_switch_is_runtime_overridable():
    """Der Kill-Switch muss ueber runtime_overrides.json schaltbar sein."""
    import runtime_config
    assert "AUTONOMOUS_TUNING_ENABLED" not in runtime_config.forbidden_keys_in(
        {"AUTONOMOUS_TUNING_ENABLED": True})
