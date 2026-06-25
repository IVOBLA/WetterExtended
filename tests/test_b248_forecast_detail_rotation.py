"""B248 — Log-Rotation: forecast_error_details.jsonl + external_responses.

Tests:
- _prune_eval_jsonl_by_age erkennt verified_at_utc als Zeitstempel.
- Alte forecast_error_details-Zeilen werden entfernt, neue behalten.
- external_responses ist in DATA_CLEANUP_PATHS.
- Retention-Override für external_responses ist 2 Tage.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cleanup_old_data as cod


def _iso_z(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_jsonl(path, entries):
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


# ── verified_at_utc wird erkannt ──────────────────────────────────────────────

def test_prune_recognizes_verified_at_utc(monkeypatch):
    """_prune_eval_jsonl_by_age soll verified_at_utc als Zeitstempel akzeptieren."""
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=72)
    new = now - timedelta(hours=1)

    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(
            cod, "SAVE_PATHS",
            {"evaluation": tmpdir}
        )
        fname = "forecast_error_details.jsonl"
        fpath = os.path.join(tmpdir, fname)
        _write_jsonl(fpath, [
            {"verified_at_utc": _iso_z(old), "forecast_error_km": 5.0},
            {"verified_at_utc": _iso_z(new), "forecast_error_km": 2.0},
        ])
        removed = cod._prune_eval_jsonl_by_age(fname, 48)
        assert removed == 1, f"Erwartet 1 Zeile entfernt, got {removed}"
        with open(fpath, encoding="utf-8") as f:
            lines = [json.loads(l) for l in f if l.strip()]
        assert len(lines) == 1
        assert lines[0]["forecast_error_km"] == 2.0


def test_prune_keeps_unparseable_lines(monkeypatch):
    """Nicht-parseable Zeilen werden immer behalten (nie Daten verlieren)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(cod, "SAVE_PATHS", {"evaluation": tmpdir})
        fname = "forecast_error_details.jsonl"
        fpath = os.path.join(tmpdir, fname)
        with open(fpath, "w") as f:
            f.write("not-valid-json\n")
            f.write(json.dumps({"verified_at_utc": "2020-01-01T00:00:00Z", "x": 1}) + "\n")
        removed = cod._prune_eval_jsonl_by_age(fname, 48)
        with open(fpath, encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        # Nicht-parseable Zeile muss erhalten bleiben
        assert any("not-valid-json" in l for l in lines), "Nicht-parseable Zeile wurde gelöscht"


def test_prune_ts_field_still_works(monkeypatch):
    """Legacy ts-Feld wird weiterhin korrekt erkannt."""
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=72)
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(cod, "SAVE_PATHS", {"evaluation": tmpdir})
        fname = "api_call_counts.jsonl"
        fpath = os.path.join(tmpdir, fname)
        _write_jsonl(fpath, [
            {"ts": _iso_z(old), "service": "arso"},
            {"ts": _iso_z(now - timedelta(hours=1)), "service": "blitz"},
        ])
        removed = cod._prune_eval_jsonl_by_age(fname, 48)
        assert removed == 1


# ── external_responses in Cleanup-Konfiguration ───────────────────────────────

def test_external_responses_in_cleanup_paths():
    from config import DATA_CLEANUP_PATHS
    paths = [p.rstrip("/") for p in DATA_CLEANUP_PATHS]
    assert "train_data/external_responses" in paths, \
        "train_data/external_responses/ fehlt in DATA_CLEANUP_PATHS"


def test_external_responses_retention_override():
    from config import DATA_CLEANUP_RETENTION_OVERRIDE
    key = "train_data/external_responses/"
    assert key in DATA_CLEANUP_RETENTION_OVERRIDE, \
        f"{key} fehlt in DATA_CLEANUP_RETENTION_OVERRIDE"
    assert DATA_CLEANUP_RETENTION_OVERRIDE[key] <= 7, \
        "Retention für external_responses sollte ≤7 Tage sein"


def test_forecast_error_details_in_prune_list():
    """forecast_error_details.jsonl muss im JSONL-Prune-Loop stehen."""
    import inspect
    src = inspect.getsource(cod.cleanup_old_data)
    assert "forecast_error_details.jsonl" in src, \
        "forecast_error_details.jsonl fehlt im cleanup_old_data JSONL-Loop"


def test_cleanup_external_responses_nested_files(monkeypatch, tmp_path):
    """Service-Unterverzeichnisse unter external_responses werden rekursiv bereinigt."""
    base = tmp_path / "train_data" / "external_responses" / "open_meteo"
    base.mkdir(parents=True)
    old_file = base / "old.json"
    old_file.write_text("{}", encoding="utf-8")
    old_ts = (datetime.now() - timedelta(days=3)).timestamp()
    os.utime(old_file, (old_ts, old_ts))

    monkeypatch.setattr(cod, "DATA_CLEANUP_PATHS", ["train_data/external_responses/"])
    monkeypatch.setattr(cod, "DATA_CLEANUP_RETENTION_OVERRIDE", {"train_data/external_responses/": 2})
    monkeypatch.setattr(cod, "DATA_RETENTION_DAYS", 90)
    monkeypatch.setattr(cod, "_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(cod, "_LOG_FILE", str(tmp_path / "cleanup_log.jsonl"))

    result = cod.cleanup_old_data()

    assert result["deleted_count"] == 1
    assert not old_file.exists()
