"""B487: tuning_apply.py las das falsche Feld (actual_km statt actual_mae_km) aus
drift_status.json und bekam dadurch immer den Sentinel-Default 999 zurueck — jede
Tuning-Aenderung wurde faelschlich als Gleichstand akzeptiert. Diese Tests verankern
den korrekten Feldnamen und die Konsistenz zwischen Erzeuger (drift_detector.py) und
Verbraucher (tuning_apply.py)."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import tools.tuning_apply as ta  # noqa: E402


def test_reads_actual_mae_km(tmp_path, monkeypatch):
    drift_file = tmp_path / "drift_status.json"
    drift_file.write_text(
        '{"quality_target_by_horizon": {"10": {"actual_mae_km": 4.2}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(ta, "DRIFT_FILE", drift_file)
    result = ta._current_mae_by_horizon()
    assert result == {"10": 4.2}


def test_wrong_legacy_field_is_ignored_not_silently_trusted(tmp_path, monkeypatch):
    """Regression: das frueher faelschlich gelesene Feld 'actual_km' darf NICHT
    zum echten Wert fuehren, sondern muss auf den Sentinel-Default zurueckfallen,
    solange 'actual_mae_km' fehlt."""
    drift_file = tmp_path / "drift_status.json"
    drift_file.write_text(
        '{"quality_target_by_horizon": {"10": {"actual_km": 1.0}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(ta, "DRIFT_FILE", drift_file)
    result = ta._current_mae_by_horizon()
    assert result == {"10": 999.0}


def test_field_name_matches_drift_detector_producer():
    """Kontrolltest: das von tuning_apply.py gelesene Feld muss mit dem von
    drift_detector.py geschriebenen Feld uebereinstimmen (verhindert erneutes
    Auseinanderlaufen von Erzeuger und Verbraucher)."""
    consumer_src = (REPO / "tools" / "tuning_apply.py").read_text(encoding="utf-8")
    producer_src = (REPO / "drift_detector.py").read_text(encoding="utf-8")
    assert 'v.get("actual_mae_km"' in consumer_src
    assert '"actual_mae_km":' in producer_src
