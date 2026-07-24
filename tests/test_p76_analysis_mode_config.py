"""P76: Betriebsart der taeglichen Analyse und Konfiguration des lokalen Laufs.

Kernzusage: Es gibt GENAU EINEN Schalter. Ein zweiter (etwa ein "enabled" neben
ANALYSIS_MODE) wuerde den verbotenen Zustand "zwei Analysen pro Tag" wieder
darstellbar machen.
"""
import config
import runtime_config


# --------------------------------------------------------------------------
# Der eine Schalter
# --------------------------------------------------------------------------

def test_analysis_mode_exists_and_defaults_to_repo():
    assert config.ANALYSIS_MODE == "repo", "Default muss das bisherige Verhalten sein"


def test_analysis_mode_changed_starts_empty():
    assert config.ANALYSIS_MODE_CHANGED == ""


def test_there_is_no_second_switch():
    """KERNREGRESSION: kein 'enabled' neben ANALYSIS_MODE, kein 'source' daneben."""
    assert "enabled" not in config.LOCAL_ANALYSIS_CONFIG, \
        "Zweiter Schalter — beide Analysen waeren gleichzeitig aktivierbar"
    assert "source" not in config.CLAUDE_CODE_REPORT_CONFIG, \
        "Zweiter Schalter — Quelle muss aus ANALYSIS_MODE folgen"


def test_report_config_keeps_its_original_keys():
    expected = {"enabled", "cron_hour", "cron_minute", "branch", "report_email"}
    assert expected <= set(config.CLAUDE_CODE_REPORT_CONFIG)


# --------------------------------------------------------------------------
# LOCAL_ANALYSIS_CONFIG
# --------------------------------------------------------------------------

def test_local_analysis_config_has_all_required_keys():
    expected = {
        "cron_hour", "cron_minute", "claude_bin", "model", "max_turns",
        "timeout_s", "prompt_path", "result_path", "status_path",
        "settings_path", "allowed_tools",
    }
    assert expected <= set(config.LOCAL_ANALYSIS_CONFIG)


def test_schedule_and_limits_are_plausible():
    cfg = config.LOCAL_ANALYSIS_CONFIG
    assert 0 <= cfg["cron_hour"] <= 23
    assert 0 <= cfg["cron_minute"] <= 59
    assert 1 <= cfg["max_turns"] <= 200
    assert 60 <= cfg["timeout_s"] <= 3600


def test_no_key_is_silently_stripped_by_runtime_config():
    """REGRESSION: max_tokens waere von _FORBIDDEN_KEY_SUBSTRINGS erfasst worden."""
    forbidden = runtime_config.forbidden_keys_in({
        "LOCAL_ANALYSIS_CONFIG": dict(config.LOCAL_ANALYSIS_CONFIG),
        "ANALYSIS_MODE": config.ANALYSIS_MODE,
        "ANALYSIS_MODE_CHANGED": config.ANALYSIS_MODE_CHANGED,
    })
    assert forbidden == [], f"Diese Schluessel wuerden verworfen: {forbidden}"


def test_mode_keys_are_runtime_overridable():
    assert runtime_config.is_editable_override_key("ANALYSIS_MODE")
    assert runtime_config.is_editable_override_key("ANALYSIS_MODE_CHANGED")


def test_config_has_no_auth_field():
    keys = " ".join(config.LOCAL_ANALYSIS_CONFIG).upper()
    for tok in ("TOKEN", "SECRET", "PASSWORD", "APIKEY", "API_KEY", "PRIVATE_KEY"):
        assert tok not in keys


# --------------------------------------------------------------------------
# Werkzeug-Allowlist
# --------------------------------------------------------------------------

def test_allowed_tools_contain_no_writing_tool():
    spec = config.LOCAL_ANALYSIS_CONFIG["allowed_tools"].lower()
    for bad in ("write", "edit", "git push", "git commit", "sudo", "rm ",
                "chmod", "chown", "pip", "npm", "apt", "tee", "python"):
        assert bad not in spec, f"Schreibendes Werkzeug in der Allowlist: {bad}"


def test_allowed_tools_read_files_only_through_read_tool():
    spec = config.LOCAL_ANALYSIS_CONFIG["allowed_tools"].lower()
    for bad in ("bash(cat", "bash(head", "bash(tail", "bash(less", "bash(more"):
        assert bad not in spec, f"Datei-Lesen an Read vorbei: {bad}"
    assert "read" in spec


def test_sqlite_is_readonly_only():
    spec = config.LOCAL_ANALYSIS_CONFIG["allowed_tools"]
    if "sqlite3" in spec:
        assert "sqlite3 -readonly" in spec
