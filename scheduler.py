from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import DATASET_REBUILD_INTERVAL_MIN, RETRAIN_INTERVAL_HOURS
from dataset_builder import build_dataset
from debug_utils import debug_log
from model_training import retrain_all


def run_rebuild_dataset_job():
    debug_log("[SCHEDULER] Job rebuild_dataset gestartet")
    try:
        result = build_dataset()
        x_data = result.get("X") if isinstance(result, dict) else None
        sample_count = len(x_data) if x_data is not None else 0
        debug_log(f"[SCHEDULER] Job rebuild_dataset abgeschlossen (samples={sample_count})")
    except Exception as exc:
        debug_log(f"[SCHEDULER] Job rebuild_dataset Fehler: {exc}")


def run_retrain_job(job_name: str):
    debug_log(f"[SCHEDULER] Job {job_name} gestartet")
    try:
        meta = retrain_all()
        trained_lstm = meta.get("lstm", {}).get("trained") if isinstance(meta, dict) else False
        trained_lgbm = meta.get("lgbm", {}).get("trained") if isinstance(meta, dict) else False
        debug_log(
            f"[SCHEDULER] Job {job_name} abgeschlossen "
            f"(lstm_trained={trained_lstm}, lgbm_trained={trained_lgbm})"
        )
    except Exception as exc:
        debug_log(f"[SCHEDULER] Job {job_name} Fehler: {exc}")


def create_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="Europe/Vienna")
    scheduler.add_job(
        run_rebuild_dataset_job,
        trigger=IntervalTrigger(minutes=DATASET_REBUILD_INTERVAL_MIN),
        id="rebuild_dataset",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        lambda: run_retrain_job("retrain_interval"),
        trigger=IntervalTrigger(hours=RETRAIN_INTERVAL_HOURS),
        id="retrain_interval",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        lambda: run_retrain_job("retrain_nightly"),
        trigger=CronTrigger(hour=3, minute=0),
        id="retrain_nightly",
        max_instances=1,
        coalesce=True,
    )
    return scheduler


def main():
    scheduler = create_scheduler()
    debug_log("[SCHEDULER] gestartet")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        debug_log("[SCHEDULER] gestoppt (KeyboardInterrupt)")


if __name__ == "__main__":
    main()
