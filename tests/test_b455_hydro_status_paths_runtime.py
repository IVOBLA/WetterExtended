"""B455: Statusschreiber folgen einem zur Laufzeit gepatchten HYDRO_ML_DIR.

Setup-Muster aus tests/test_b411_hydro_retention.py uebernommen.
"""
from pathlib import Path

import hydro_flood_ml as h

REAL_ML_DIR = Path("train_data/hydro/ml")


def _snapshot():
    if not REAL_ML_DIR.exists():
        return None
    return sorted(
        (p.name, p.stat().st_mtime_ns, p.stat().st_size)
        for p in REAL_ML_DIR.rglob("*") if p.is_file()
    )


def test_status_writers_follow_patched_hydro_ml_dir(monkeypatch, tmp_path):
    before = _snapshot()
    monkeypatch.setattr(h, "HYDRO_SAMPLE_DB_PATH", tmp_path / "s.sqlite3")
    monkeypatch.setattr(h, "HYDRO_ML_DIR", tmp_path)
    monkeypatch.setattr(h, "HYDRO_MODEL_CANDIDATES_DIR", tmp_path / "candidates")
    monkeypatch.setattr(h, "HYDRO_MODEL_HISTORY_DIR", tmp_path / "history")

    with h._sample_db() as con:
        con.execute(
            "INSERT INTO sample_failures VALUES(?,?,?,?,?)",
            ("f", "s", "2000-01-01T00:00:00Z", "old", "{}"),
        )

    h.hydro_ml_maintenance()
    h.sample_db_integrity()

    assert h._training_meta_path() == tmp_path / "hydro_flood_training_meta.json"
    assert h._maintenance_status_path() == tmp_path / "hydro_ml_maintenance_latest.json"
    assert h._sample_db_integrity_path() == tmp_path / "hydro_sample_db_integrity.json"
    assert (tmp_path / "hydro_ml_maintenance_latest.json").exists()
    assert (tmp_path / "hydro_sample_db_integrity.json").exists()
    assert _snapshot() == before, (
        "Produktionsverzeichnis train_data/hydro/ml wurde durch den Test veraendert"
    )
