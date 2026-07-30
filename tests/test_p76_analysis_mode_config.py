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
    assert 1 <= cfg["max_turns"] <= 500
    assert 60 <= cfg["timeout_s"] <= 3600
    # B480-Invariante: timeout_s muss unter TimeoutStartSec=1800 der systemd-Unit
    # bleiben, damit der Runner sich selbst beendet bevor systemd hart abbricht.
    assert cfg["timeout_s"] < 1800, "timeout_s muss < TimeoutStartSec=1800 sein"


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

def test_allowed_tools_is_the_positive_list():
    spec = config.LOCAL_ANALYSIS_CONFIG["allowed_tools"]
    assert spec == "Read,Grep,Glob,Bash(python3 tools/ro_query.py *)"


def test_allowed_tools_have_exactly_one_bash_rule():
    spec = config.LOCAL_ANALYSIS_CONFIG["allowed_tools"]
    assert spec.count("Bash(") == 1
    assert "tools/ro_query.py" in spec


def test_allowed_tools_contain_no_wildcard_shell_rule():
    spec = config.LOCAL_ANALYSIS_CONFIG["allowed_tools"].lower()
    for bad in ("bash(journalctl", "bash(sqlite3", "bash(systemctl", "bash(ls",
                "bash(stat", "bash(df", "bash(free", "bash(uptime",
                "bash(cat", "bash(head", "bash(tail", "write", "edit"):
        assert bad not in spec, f"Platzhalter-/Schreibregel in der Allowlist: {bad}"
