import os
import hydro_fetch


def test_atomic_write_cleanup_error_does_not_name_error(monkeypatch, tmp_path):
    target=tmp_path/'x.json'
    real_exists=os.path.exists
    monkeypatch.setattr(hydro_fetch.os.path, 'exists', lambda p: True if str(p).endswith('.tmp') else real_exists(p))
    monkeypatch.setattr(hydro_fetch.os, 'unlink', lambda p: (_ for _ in ()).throw(OSError('blocked')))
    hydro_fetch._atomic_write_json(target, {'ok': True})
    assert target.exists()
