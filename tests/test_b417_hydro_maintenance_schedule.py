from pathlib import Path

def test_maintenance_registered():
    source=Path('scheduler.py').read_text()
    assert 'id="hydro_ml_maintenance"' in source and 'run_hydro_ml_maintenance_job' in source
