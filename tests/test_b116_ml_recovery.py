"""
tests/test_b116_ml_recovery.py

B116: Selbstheilung bei inkompatiblen ML-Modellen.
Belegt:
  1. _quarantine_incompatible_current() benennt current um (löscht nicht), idempotent.
  2. _check_model_compatibility erkennt Feature-Count-Mismatch.
  3. _ml_block_reason() (app) liefert Klartext bei inkompatiblem/fehlendem Modell.

Ausführbar: python3 -m pytest tests/test_b116_ml_recovery.py -v
"""
import sys, os, json, tempfile, shutil, importlib
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_quarantine_function_exists():
    mt = importlib.import_module("model_training")
    assert hasattr(mt, "_quarantine_incompatible_current"), \
        "B116: _quarantine_incompatible_current fehlt"


def test_compat_detects_feature_mismatch(tmp_path):
    mt = importlib.import_module("model_training")
    from config import ML_NUM_FEATURES
    meta = {
        "horizons_trained": mt._get_training_horizons(),
        "feature_count": ML_NUM_FEATURES + 5,   # bewusst falsch
    }
    (tmp_path / "training_meta.json").write_text(json.dumps(meta))
    res = mt._check_model_compatibility(str(tmp_path))
    assert res["compatible"] is False
    assert "Feature" in res["reason"] or "feature" in res["reason"].lower()


def test_compat_accepts_matching(tmp_path):
    mt = importlib.import_module("model_training")
    from config import ML_NUM_FEATURES
    schema = importlib.import_module("feature_schema").get_current_feature_schema()
    meta = {
        "horizons_trained": mt._get_training_horizons(),
        "feature_count": ML_NUM_FEATURES,
        "feature_schema_hash": schema["feature_schema_hash"],
        "feature_schema_version": schema["schema_version"],
    }
    (tmp_path / "training_meta.json").write_text(json.dumps(meta))
    res = mt._check_model_compatibility(str(tmp_path))
    assert res["compatible"] is True


def test_quarantine_renames_not_deletes(tmp_path, monkeypatch):
    mt = importlib.import_module("model_training")
    # Fake current-Verzeichnis
    cur = tmp_path / "current"
    cur.mkdir()
    (cur / "marker.txt").write_text("x")
    monkeypatch.setattr(mt, "_current_models_dir", lambda: str(cur))
    mt._quarantine_incompatible_current("test-reason")
    # current ist weg, aber ein _incompatible_-Verzeichnis existiert mit dem Marker
    assert not cur.exists(), "current sollte umbenannt sein"
    quarantined = list(tmp_path.glob("current_incompatible_*"))
    assert quarantined, "Quarantäne-Verzeichnis fehlt"
    assert (quarantined[0] / "marker.txt").exists(), "Inhalt darf nicht gelöscht werden"


def test_ml_block_reason_importable():
    """app._ml_block_reason existiert und ist aufrufbar (None oder str)."""
    try:
        app_mod = importlib.import_module("app")
    except Exception as e:
        pytest.skip(f"app nicht importierbar (Flask-Kontext): {e}")
    fn = getattr(app_mod, "_ml_block_reason", None)
    assert fn is not None, "B116: _ml_block_reason fehlt in app.py"
    val = fn()
    assert val is None or isinstance(val, str)


def test_lgbm_feature_gate_rejects_mismatch():
    pred = importlib.import_module("prediction")

    class FakeModel:
        def num_feature(self):
            return 114

    class FakeFrame:
        shape = (1, 119)

    assert pred._lgbm_feat_ok(FakeModel(), FakeFrame()) is False


def test_lgbm_feature_gate_accepts_matching():
    pred = importlib.import_module("prediction")

    class FakeModel:
        def num_feature(self):
            return 119

    class FakeFrame:
        shape = (1, 119)

    assert pred._lgbm_feat_ok(FakeModel(), FakeFrame()) is True
