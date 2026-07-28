"""B480: Schrittbudget der lokalen Analyse angehoben, Zeitlimit-Invariante gewahrt.

Der lokale Analyselauf war schritt- (max_turns), nicht zeit-limitiert: mit
max_turns=70 (B471) schaffte er nur Abschnitt A + ~5 ACs, verbrauchte dabei aber
nur ~14 % des Zeitlimits. B480 hebt max_turns und timeout_s gemeinsam an, damit
Abschnitt A + alle offenen ACs in einen Lauf passen.

Invariante: timeout_s MUSS unter der systemd-Notbremse TimeoutStartSec=1800 des
Dienstes wetterprojekt-local-analysis.service bleiben, damit der Runner sich
selbst beendet, bevor systemd hart abbricht.

Gelesen wird der committete Default aus config.LOCAL_ANALYSIS_CONFIG — bewusst
NICHT der runtime-gemergte Effektivwert (B467: Runtime-Overrides am Pi wuerden
den Test sonst verfaelschen).
"""
import config

# systemd TimeoutStartSec des Dienstes (wetterprojekt-local-analysis.service).
SYSTEMD_TIMEOUT_START_SEC = 1800


def test_max_turns_raised():
    assert config.LOCAL_ANALYSIS_CONFIG["max_turns"] == 260


def test_timeout_raised():
    assert config.LOCAL_ANALYSIS_CONFIG["timeout_s"] == 1700


def test_timeout_below_systemd_hard_kill():
    """Der Runner-Softtimeout muss vor der systemd-Notbremse greifen."""
    assert config.LOCAL_ANALYSIS_CONFIG["timeout_s"] < SYSTEMD_TIMEOUT_START_SEC


def test_step_budget_has_headroom_for_all_acs():
    """Genug Schritte fuer Abschnitt A + die offenen ACs (nicht mehr ~5)."""
    assert config.LOCAL_ANALYSIS_CONFIG["max_turns"] >= 200
