"""B356: RLIMIT_AS des ConvLSTM-Trainings-Subprozesses wird dynamisch auf den
tatsaechlich freien RAM gedeckelt (statt eines rein statischen Werts), und der
Batch-Size-Retry kaskadiert bis batch_size=1 und faengt auch MemoryError ab
(nicht nur TF ResourceExhausted). Statische Quelltext-Checks — kein TF/psutil-
Laufzeitimport noetig fuer die reinen Struktur-Assertions."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_config_has_safety_margin():
    cfg = _read("config.py")
    assert "CONVLSTM_TRAIN_MEM_SAFETY_MARGIN_GB" in cfg


def test_scheduler_computes_dynamic_mem_limit():
    src = _read("scheduler.py")
    job = src.split("def run_convlstm_weekly_job(")[1].split("\ndef ")[0]
    assert "psutil" in job, "Dynamische Speicherberechnung fehlt (psutil)"
    assert "virtual_memory" in job
    assert "CONVLSTM_TRAIN_MEM_SAFETY_MARGIN_GB" in job
    assert "_effective_mem_bytes" in job
    assert "RLIMIT_AS" in job


def test_scheduler_limit_mem_uses_effective_bytes_not_static():
    src = _read("scheduler.py")
    job = src.split("def run_convlstm_weekly_job(")[1].split("\ndef ")[0]
    limit_fn = job.split("def _limit_mem():")[1].split("\n\n")[0]
    assert "_effective_mem_bytes" in limit_fn
    assert "_mem_gb * 1024" not in limit_fn, "_limit_mem nutzt noch das rein statische Limit"


def test_train_convlstm_cascades_on_oom_to_batch_size_one():
    src = _read("radar_convlstm.py")
    fn = src.split("def train_convlstm(")[1].split("\ndef ")[0]
    assert "MemoryError" in fn, "MemoryError wird nicht abgefangen"
    assert "ResourceExhausted" in fn
    assert "_candidates" in fn
    assert "(safe_batch_size, 2, 1)" in fn, "Kaskade endet nicht bei batch_size=1"


def test_train_convlstm_still_saves_model_on_success():
    src = _read("radar_convlstm.py")
    fn = src.split("def train_convlstm(")[1].split("\ndef ")[0]
    assert '"trained": True' in fn
    assert "model.save(effective_model_path)" in fn


def test_scheduler_no_direct_train_import_still_holds():
    # Regressionsschutz fuer B147: darf durch B356 nicht wieder aufgeweicht werden.
    src = _read("scheduler.py")
    assert "from radar_convlstm import train_convlstm" not in src
