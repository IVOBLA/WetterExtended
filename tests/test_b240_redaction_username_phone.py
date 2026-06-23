"""B240: Benutzername (USERNAME/LOGIN) und Telefonnummer (TWILIO_TO) werden maskiert."""
import export_security as es


def test_is_sensitive_key_username_login_twilio():
    assert es.is_sensitive_key("BLITZ_USERNAME") is True
    assert es.is_sensitive_key("DB_LOGIN") is True
    assert es.is_sensitive_key("TWILIO_TO") is True


def test_non_secret_keys_remain_visible():
    # Regression: harmlose Schlüssel + B119-Allowlist bleiben unmaskiert
    assert es.is_sensitive_key("CITY") is False
    assert es.is_sensitive_key("MAX_TOKENS") is False
    assert es.is_sensitive_key("USER_AGENT") is False


def test_redact_text_masks_env_username_and_phone():
    env = "BLITZ_USERNAME=HorstBla\nTWILIO_TO=+4369912345678\nCITY=Klagenfurt\n"
    out = es.redact_text(env)
    assert "HorstBla" not in out
    assert "+4369912345678" not in out
    assert es.REDACTION_VALUE in out
    assert "Klagenfurt" in out  # Nicht-Secret bleibt


def test_redact_obj_masks_username_and_phone():
    obj = {"BLITZ_USERNAME": "HorstBla", "TWILIO_TO": "+4369912345678", "CITY": "Villach"}
    out = es.redact_obj(obj)
    assert out["BLITZ_USERNAME"] == es.REDACTION_VALUE
    assert out["TWILIO_TO"] == es.REDACTION_VALUE
    assert out["CITY"] == "Villach"


def test_existing_secrets_still_masked():
    obj = {"GITHUB_TOKEN": "ghp_x", "API_KEY": "abc", "SMTP_PASS": "p"}
    out = es.redact_obj(obj)
    assert all(v == es.REDACTION_VALUE for v in out.values())
