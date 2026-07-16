import multiprocessing
import time

import hydro_flood_ml as h


def _hold_lock(path, ready, release):
    h.HYDRO_TRAINING_LOCK_PATH = path
    handle = h.acquire_training_lock()
    ready.put(handle is not None)
    release.get(timeout=10)
    h.release_training_lock(handle)


def test_lock_is_exclusive_across_processes(tmp_path, monkeypatch):
    path = tmp_path / "training.lock"
    monkeypatch.setattr(h, "HYDRO_TRAINING_LOCK_PATH", path)
    ready, release = multiprocessing.Queue(), multiprocessing.Queue()
    process = multiprocessing.Process(target=_hold_lock, args=(path, ready, release))
    process.start()
    assert ready.get(timeout=5) is True
    assert h.acquire_training_lock() is None
    release.put(True)
    process.join(timeout=5)
    third = h.acquire_training_lock()
    assert third is not None
    h.release_training_lock(third)


def test_worker_uses_handed_over_handle_and_releases_it(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "HYDRO_TRAINING_LOCK_PATH", tmp_path / "training.lock")
    monkeypatch.setattr(h, "HYDRO_TRAINING_STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(h, "_train_model_unlocked", lambda lock_handle=None: {"status": "trained"})
    payload, code = h.start_training_job()
    assert code == 202
    deadline = time.time() + 5
    while h.training_status()["phase"] != "finished" and time.time() < deadline:
        time.sleep(0.01)
    assert h.training_status()["phase"] == "finished"
    handle = h.acquire_training_lock()
    assert handle is not None
    h.release_training_lock(handle)


def test_thread_start_failure_releases_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "HYDRO_TRAINING_LOCK_PATH", tmp_path / "training.lock")
    monkeypatch.setattr(h, "HYDRO_TRAINING_STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(h.threading.Thread, "start", lambda self: (_ for _ in ()).throw(RuntimeError("start failed")))
    try:
        h.start_training_job()
    except RuntimeError:
        pass
    handle = h.acquire_training_lock()
    assert handle is not None
    h.release_training_lock(handle)
