"""
tests/test_b123_install_model_gate.py

B123: install.sh besitzt ein ML-Feature/Model-Kompatibilitäts-Gate vor Phase 9.
Belegt (grep-basiert auf install.sh + funktional auf model_training):
  1. install.sh enthält die Phase 8.9 vor Phase 9.
  2. Das Gate nutzt die kanonischen model_training-Funktionen (kein Duplikat).
  3. full-Branch löscht, upgrade-Branch quarantänisiert.
  4. _check_model_compatibility erkennt Feature-Mismatch (Wiederverwendung).

Ausführbar: python3 -m pytest tests/test_b123_install_model_gate.py -v
"""
import os
import json
import importlib
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_install_sh():
    path = os.path.join(_ROOT, "install.sh")
    assert os.path.exists(path), "install.sh fehlt"
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_phase_89_exists_before_phase_9():
    txt = _read_install_sh()
    assert "PHASE 8.9 — ML-Modell/Feature-Kompatibilität" in txt
    i89 = txt.index("PHASE 8.9 — ML-Modell/Feature-Kompatibilität")
    i9 = txt.index("PHASE 9 — Tests (letzter Schritt, beide Modi)")
    assert i89 < i9, "Phase 8.9 muss VOR Phase 9 stehen"


def test_gate_uses_canonical_functions():
    txt = _read_install_sh()
    assert "_check_model_compatibility" in txt
    assert "_current_models_dir" in txt
    assert "_quarantine_incompatible_current" in txt


def test_full_deletes_upgrade_quarantines():
    txt = _read_install_sh()
    # full-Branch löscht
    assert 'if [[ "$MODE" == "full" ]]; then' in txt
    assert "rm -rf \"$_COMPAT_REAL\"" in txt
    # upgrade-Branch quarantänisiert (kein rm der realen Modelle)
    assert "_quarantine_incompatible_current('install.sh B123" in txt


def test_check_model_compatibility_detects_mismatch(tmp_path):
    mt = importlib.import_module("model_training")
    from config import ML_NUM_FEATURES
    meta = {"horizons_trained": mt._get_training_horizons(),
            "feature_count": ML_NUM_FEATURES + 7}
    (tmp_path / "training_meta.json").write_text(json.dumps(meta))
    res = mt._check_model_compatibility(str(tmp_path))
    assert res["compatible"] is False
    assert "feature" in res["reason"].lower() or "Feature" in res["reason"]


def test_check_model_compatibility_accepts_matching(tmp_path):
    mt = importlib.import_module("model_training")
    from config import ML_NUM_FEATURES
    meta = {"horizons_trained": mt._get_training_horizons(),
            "feature_count": ML_NUM_FEATURES}
    (tmp_path / "training_meta.json").write_text(json.dumps(meta))
    res = mt._check_model_compatibility(str(tmp_path))
    assert res["compatible"] is True
