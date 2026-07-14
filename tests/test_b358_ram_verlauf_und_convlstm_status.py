"""B358: RAM-Verlauf (mem_monitor.py, analog cpu_monitor.py) + ConvLSTM-
Trainingsstatus im Admin Panel (liest B357-Telemetrie). Statische
Quelltext-Checks + Logiktests fuer mem_monitor (keine Frontend-Ausfuehrung,
JSX wird nur auf Quelltext-Ebene geprueft)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_mem_monitor_module_exists():
    assert os.path.exists("mem_monitor.py")
    src = _read("mem_monitor.py")
    assert "def sample_mem(" in src
    assert "def append_mem_sample(" in src
    assert "def get_mem_history(" in src
    assert "MEM_HISTORY_MAX_ENTRIES" in src


def test_mem_monitor_sample_and_history_roundtrip(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "SAVE_PATHS", {"system": str(tmp_path)}, raising=False)
    import mem_monitor as mm
    mm.append_mem_sample()
    history = mm.get_mem_history(hours=24)
    assert isinstance(history, list)
    if history:
        assert "available_gb" in history[-1]
        assert "used_pct" in history[-1]


def test_scheduler_registers_mem_monitor_job():
    src = _read("scheduler.py")
    assert "from mem_monitor import append_mem_sample" in src
    assert "def run_mem_monitor_job():" in src
    assert 'id="mem_monitor"' in src


def test_app_has_mem_history_endpoint():
    src = _read("app.py")
    assert '@app.route("/api/mem_history")' in src
    assert "from mem_monitor import get_mem_history" in src


def test_dashboard_jsx_has_mem_chart():
    src = _read("frontend/src/pages/Dashboard.jsx")
    assert "function MemChart(" in src
    assert "/api/mem_history" in src
    assert "<MemChart data={memHistory} />" in src


def test_radar_convlstm_has_recent_runs_helper():
    src = _read("radar_convlstm.py")
    assert "def get_recent_training_runs(" in src


def test_get_recent_training_runs_reads_jsonl(tmp_path, monkeypatch):
    import config
    patched_paths = dict(config.SAVE_PATHS)
    patched_paths["evaluation"] = str(tmp_path)
    monkeypatch.setattr(config, "SAVE_PATHS", patched_paths, raising=False)
    import radar_convlstm as rc
    rc._write_training_run_record({"outcome": "success", "batch_size_used": 4})
    rc._write_training_run_record({"outcome": "system_oom_kill"})
    runs = rc.get_recent_training_runs(n=5)
    assert len(runs) == 2
    assert runs[-1]["outcome"] == "system_oom_kill"


def test_app_has_convlstm_status_endpoint():
    src = _read("app.py")
    assert '@app.route("/api/admin/convlstm/status")' in src
    assert "from radar_convlstm import get_recent_training_runs" in src


def test_training_jsx_has_convlstm_status_card():
    src = _read("frontend/src/pages/Training.jsx")
    assert "function ConvlstmStatusCard(" in src
    assert "/api/admin/convlstm/status" in src
    assert "<ConvlstmStatusCard status={convlstmStatus} />" in src
