"""P78: systemd-Units und install.sh-Integration der lokalen Analyse.

Geprueft wird ausschliesslich der Inhalt der ausgelieferten Dateien — es wird
nichts installiert, aktiviert oder gestartet.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE = REPO_ROOT / "wetterprojekt-local-analysis.service"
TIMER = REPO_ROOT / "wetterprojekt-local-analysis.timer"
INSTALL = REPO_ROOT / "install.sh"


def _svc():
    return SERVICE.read_text(encoding="utf-8")


def _tmr():
    return TIMER.read_text(encoding="utf-8")


def _inst():
    return INSTALL.read_text(encoding="utf-8")


def _phase():
    return _inst().split("PHASE 7h — Lokale Analyse", 1)[1].split("PHASE 7f", 1)[0]


# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------

def test_units_exist():
    assert SERVICE.is_file() and TIMER.is_file()


def test_service_is_oneshot_and_calls_the_runner():
    t = _svc()
    assert "Type=oneshot" in t
    assert "tools/run_local_analysis.py" in t
    assert "--repo-dir" in t


def test_service_path_contains_local_bin():
    """systemd erbt ~/.bashrc nicht — ohne diesen PATH wird die CLI nicht gefunden."""
    line = next(l for l in _svc().splitlines() if l.startswith("Environment=PATH="))
    assert "/.local/bin" in line


def test_service_is_sandboxed():
    t = _svc()
    for directive in ("NoNewPrivileges=yes", "PrivateTmp=yes",
                      "ProtectSystem=strict", "ProtectKernelTunables=yes"):
        assert directive in t, f"Sandbox-Direktive fehlt: {directive}"


def test_service_write_access_is_limited_to_the_result_directory():
    """B466: strict + ReadWritePaths — Quellcode und Modelle sind unbeschreibbar."""
    t = _svc()
    assert "ProtectSystem=full" not in t, "full laesst /home schreibbar"
    rw = [l.split("=", 1)[1].lstrip("-")
          for l in t.splitlines() if l.startswith("ReadWritePaths=")]
    assert any(p.endswith("train_data/evaluation") for p in rw), \
        "Ergebnisverzeichnis fehlt in ReadWritePaths"
    for p in rw:
        assert not p.rstrip("/").endswith("wetterprojekt"), \
            "Das gesamte Projektverzeichnis darf nicht beschreibbar sein"


def test_service_allows_the_cli_to_write_its_own_state():
    """Ohne ~/.claude scheitert die Anmeldung der CLI im Timer-Kontext."""
    rw = " ".join(l for l in _svc().splitlines() if l.startswith("ReadWritePaths="))
    assert ".claude" in rw


def test_service_makes_env_file_inaccessible():
    """Kernel-erzwungene Sperre — unabhaengig von den Deny-Regeln der CLI."""
    line = next((l for l in _svc().splitlines()
                 if l.startswith("InaccessiblePaths=")), None)
    assert line is not None, "InaccessiblePaths fehlt"
    assert ".env" in line
    assert line.startswith("InaccessiblePaths=-"), \
        "Minus-Praefix fehlt — fehlende .env wuerde den Start scheitern lassen"


def test_service_never_runs_as_root():
    line = next(l for l in _svc().splitlines() if l.startswith("User="))
    assert line.split("=", 1)[1].strip() != "root"


def test_service_has_hard_timeout():
    assert "TimeoutStartSec=" in _svc()


def test_timer_wakes_twice_per_hour():
    """Die Uhrzeit steht in der Konfiguration, nicht in der Unit."""
    t = _tmr()
    assert "OnCalendar=*-*-* *:00/30:00" in t
    assert "Persistent=true" in t
    assert "Unit=wetterprojekt-local-analysis.service" in t
    assert "WantedBy=timers.target" in t


def test_timer_has_randomized_delay():
    assert "RandomizedDelaySec=" in _tmr()


# --------------------------------------------------------------------------
# install.sh
# --------------------------------------------------------------------------

def test_install_has_local_analysis_flag_default_on():
    assert "ENABLE_LOCAL_ANALYSIS=true" in _inst()


def test_install_parses_no_local_analysis():
    t = _inst()
    assert "--no-local-analysis)" in t
    assert "ENABLE_LOCAL_ANALYSIS=false" in t


def test_install_documents_the_flag_in_usage():
    assert "--no-local-analysis" in _inst().split("USAGE")[1]


def test_install_has_phase_7h():
    t = _inst()
    assert "PHASE 7h — Lokale Analyse" in t
    assert 'LOCAL_ANALYSIS_TIMER="wetterprojekt-local-analysis.timer"' in t


def test_install_reports_the_analysis_mode():
    seg = _phase()
    assert "ANALYSIS_MODE" in seg
    assert "Betriebsart" in seg


def test_install_warns_about_the_external_routine_in_local_mode():
    """Die externe Routine kann der Pi nicht abschalten — das muss dastehen."""
    seg = _phase()
    assert "zwei Analysen" in seg
    assert "Claude-App" in seg


def test_install_checks_for_the_cli_and_gives_manual_hint():
    """zieldefinition.txt Z. 44: Was install.sh nicht kann, muss es dem Nutzer sagen."""
    seg = _phase()
    assert "claude.ai/install.sh" in seg
    assert "interaktiv anmelden" in seg
    assert "note_manual" in seg


def test_install_runs_check_only_not_a_real_analysis():
    seg = _phase()
    assert "--check-only" in seg
    assert "--force" not in seg, "install.sh darf keinen echten Analyse-Lauf starten"


def test_install_supports_both_modes_unchanged():
    """REGRESSION: --mode=full und --mode=upgrade muessen erhalten bleiben."""
    assert "--mode <full|upgrade>" in _inst()


def test_pytest_phase_still_only_warns():
    """REGRESSION: Phase 9 darf die Installation nie abbrechen."""
    assert "brechen die Installation NIEMALS ab" in _inst()
