"""P82: Der Debug-Export wird in Betriebsart "local" nicht mehr gepusht.

Kernzusagen:
  * "repo" (Default): Push wie bisher.
  * "local": kein Push — der Branch wuerde von niemandem gelesen.
  * Der Admin-Panel-Export wird IN BEIDEN Faellen abgelegt (B429 bleibt gueltig).
  * Ein defektes runtime_overrides.json darf den Push niemals verhindern.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "tools" / "publish_latest_debug_export_branch.py"


@pytest.fixture
def publisher(monkeypatch):
    spec = importlib.util.spec_from_file_location("publish_branch_p82", TOOL)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def _src():
    return TOOL.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Betriebsart-Ermittlung
# --------------------------------------------------------------------------

def test_analysis_mode_helper_exists(publisher):
    assert hasattr(publisher, "analysis_mode")


def test_config_default_is_repo():
    """B467: Die VORGABE in config.py — nicht der effektive Wert.

    Die alte Fassung pruefte analysis_mode() ohne Attrappe und schlug auf jedem
    Geraet fehl, das in runtime_overrides.json bereits auf "local" steht. Tests
    duerfen niemals vom Laufzeitzustand der Zielumgebung abhaengen.
    """
    import config
    assert config.ANALYSIS_MODE == "repo"


def test_runtime_override_is_respected(publisher, monkeypatch):
    import runtime_config
    monkeypatch.setattr(runtime_config, "reload_overrides", lambda: None)
    monkeypatch.setattr(runtime_config, "get", lambda name, default=None: "local")
    assert publisher.analysis_mode(REPO_ROOT) == "local"


def test_missing_override_falls_back_to_the_config_default(publisher, monkeypatch):
    import runtime_config
    monkeypatch.setattr(runtime_config, "reload_overrides", lambda: None)
    monkeypatch.setattr(runtime_config, "get", lambda name, default=None: default)
    assert publisher.analysis_mode(REPO_ROOT) == "repo"


def test_broken_runtime_config_falls_back_to_repo(publisher, monkeypatch):
    """Ein defektes runtime_overrides.json darf den Push nie stillschweigend abschalten."""
    import runtime_config

    def _boom():
        raise RuntimeError("runtime_overrides.json ist kaputt")

    monkeypatch.setattr(runtime_config, "reload_overrides", _boom)
    assert publisher.analysis_mode(REPO_ROOT) == "repo"


def test_missing_repo_dir_never_raises(publisher, tmp_path):
    """Auch mit unsinnigem Pfad liefert der Helper einen gueltigen Wert statt zu werfen."""
    assert publisher.analysis_mode(tmp_path / "gibtsnicht") in ("repo", "local")


def test_mode_is_lowercased_and_stripped(publisher, monkeypatch):
    import runtime_config
    monkeypatch.setattr(runtime_config, "reload_overrides", lambda: None)
    monkeypatch.setattr(runtime_config, "get",
                        lambda name, default=None: "  LOCAL  ")
    assert publisher.analysis_mode(REPO_ROOT) == "local"


# --------------------------------------------------------------------------
# Reihenfolge im Ablauf
# --------------------------------------------------------------------------

def test_admin_panel_export_happens_before_the_mode_check():
    """B429 bleibt gueltig: der Download muss auch ohne Push existieren."""
    src = _src()
    body = src.split("def publish(", 1)[1]
    i_persist = body.index("persist_for_admin_panel(parts, export_manifest")
    i_mode = body.index('analysis_mode(args.repo_dir) == "local"')
    assert i_persist < i_mode, "Modus-Pruefung liegt vor der Persistenz"


def test_mode_check_returns_before_building_the_branch_repo():
    """Ohne Push braucht auch das temporaere Branch-Repo nicht gebaut zu werden."""
    body = _src().split("def publish(", 1)[1]
    i_mode = body.index('analysis_mode(args.repo_dir) == "local"')
    i_write = body.index("manifest = write_branch_repo(")
    assert i_mode < i_write


def test_local_mode_logs_why_it_skips():
    body = _src().split("def publish(", 1)[1]
    seg = body[body.index('analysis_mode(args.repo_dir) == "local"'):]
    seg = seg[:400]
    assert "kein Push" in seg
    assert "Admin-Panel-Export" in seg


def test_push_command_is_still_present_for_repo_mode():
    """REGRESSION: der bisherige Pfad darf nicht verschwinden."""
    assert '"push", "--force", "origin", refspec' in _src()


def test_dry_run_path_is_untouched():
    src = _src()
    assert "Dry-run: kein Push." in src
    assert "Dry-run: keine Persistenz für das Admin-Panel." in src
