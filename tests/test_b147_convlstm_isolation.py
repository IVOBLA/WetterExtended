"""B147: ConvLSTM-Training speicherschonend (Streaming) + Subprozess-Isolation.

Statische Quelltext-Checks (kein TF/cv2-Import) + leichte Logiktests der reinen
Index-/Pfad-Helfer (radar_convlstm importiert TF/cv2 nur lazy → Import ist leicht)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---- statische Checks -------------------------------------------------------

def test_config_has_convlstm_limits():
    cfg = _read("config.py")
    assert "CONVLSTM_MAX_FRAMES" in cfg
    assert "CONVLSTM_TRAIN_TIMEOUT_S" in cfg
    assert "CONVLSTM_TRAIN_MEM_LIMIT_GB" in cfg


def test_train_convlstm_uses_streaming_sequence():
    src = _read("radar_convlstm.py")
    assert "tf.keras.utils.Sequence" in src, "Streaming-Sequence fehlt"
    assert "_list_radar_frame_paths" in src
    assert "_window_start_indices" in src
    # train_convlstm darf KEIN validation_split mehr nutzen (Generator-inkompatibel).
    after = src.split("def train_convlstm(")[1]
    before_next = after.split("\ndef ")[0]
    assert "validation_split" not in before_next, "train_convlstm nutzt noch validation_split"
    assert "validation_data=" in before_next, "train_convlstm ohne validation_data"


def test_scheduler_runs_convlstm_as_subprocess():
    src = _read("scheduler.py")
    job = src.split("def run_convlstm_weekly_job(")[1].split("\ndef ")[0]
    assert "subprocess" in job, "Job startet keinen Subprozess"
    assert "radar_convlstm.py" in job, "Subprozess ruft radar_convlstm.py nicht auf"
    assert "RLIMIT_AS" in job, "Kein Adressraum-Limit für das Kind"
    assert "train_convlstm()" not in job, "Job ruft train_convlstm weiterhin in-process auf"


def test_scheduler_no_direct_train_import():
    src = _read("scheduler.py")
    assert "from radar_convlstm import train_convlstm" not in src, \
        "Direkter In-Process-Import von train_convlstm noch vorhanden"


# ---- leichte Logiktests -----------------------------------------------------

def test_window_start_indices():
    import radar_convlstm as rc
    n = rc.SEQUENCE_LENGTH + 2
    assert rc._window_start_indices(n) == [0, 1, 2]
    assert rc._window_start_indices(rc.SEQUENCE_LENGTH - 1) == []


def test_frame_cap_keeps_newest(tmp_path, monkeypatch):
    import radar_convlstm as rc
    import config
    radar_dir = tmp_path / "radar"
    radar_dir.mkdir()
    for i in range(10):
        (radar_dir / f"radar_2026-06-14_00-{i:02d}-00.png").write_bytes(b"x")
    monkeypatch.setattr(rc, "SAVE_PATHS", {"radar": str(radar_dir)})
    monkeypatch.setattr(config, "CONVLSTM_MAX_FRAMES", 5, raising=False)
    paths = rc._list_radar_frame_paths()
    assert len(paths) == 5, "Frame-Cap nicht angewandt"
    assert paths[-1].endswith("00-09-00.png"), "Cap behält nicht die jüngsten Frames"
