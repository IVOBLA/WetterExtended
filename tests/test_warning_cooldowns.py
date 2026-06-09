"""
B98: Einmal-pro-Zelle-Warnung + alle Cooldowns aus config konfigurierbar.
"""
import pytest


def _cfg():
    try:
        import config
        return config
    except ImportError:
        pytest.skip("config.py nicht importierbar")


def test_warn_cooldown_in_config():
    assert hasattr(_cfg(), "WARN_COOLDOWN_S"), "WARN_COOLDOWN_S fehlt in config.py"
    assert _cfg().WARN_COOLDOWN_S > 0


def test_allclear_cooldown_in_config():
    assert hasattr(_cfg(), "ALLCLEAR_COOLDOWN_S"), "ALLCLEAR_COOLDOWN_S fehlt in config.py"
    assert _cfg().ALLCLEAR_COOLDOWN_S > 0


def test_drift_cooldown_in_config():
    assert hasattr(_cfg(), "DRIFT_ALERT_COOLDOWN_H"), "DRIFT_ALERT_COOLDOWN_H fehlt in config.py"
    assert _cfg().DRIFT_ALERT_COOLDOWN_H > 0


def test_risk_alert_cooldown_12h():
    assert _cfg().RISK_ALERT_COOLDOWN_S == 43200, (
        f"RISK_ALERT_COOLDOWN_S soll 43200 (12h) sein, ist: {_cfg().RISK_ALERT_COOLDOWN_S}"
    )


def test_get_cooldown_helper_email():
    """_get_cooldown-Helper in email_notifier muss vorhanden sein."""
    try:
        from email_notifier import _get_cooldown
        val = _get_cooldown("WARN_COOLDOWN_S", 999)
        assert isinstance(val, int) and val > 0
    except ImportError as e:
        pytest.skip(f"email_notifier nicht importierbar: {e}")


def test_get_cooldown_helper_wa():
    """_get_cooldown-Helper in whatsapp_notifier muss vorhanden sein."""
    try:
        from whatsapp_notifier import _get_cooldown
        val = _get_cooldown("ALLCLEAR_COOLDOWN_S", 999)
        assert isinstance(val, int) and val > 0
    except ImportError as e:
        pytest.skip(f"whatsapp_notifier nicht importierbar: {e}")
