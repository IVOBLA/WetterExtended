import pytest
import hydro_flood_ml as h

def test_nonblocking_flock(tmp_path, monkeypatch):
    monkeypatch.setattr(h,'HYDRO_TRAINING_LOCK_PATH',tmp_path/'lock')
    with h.hydro_training_lock():
        with pytest.raises(BlockingIOError):
            with h.hydro_training_lock(): pass
