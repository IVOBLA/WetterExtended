from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import DATASET_REBUILD_INTERVAL_MIN, RETRAIN_INTERVAL_HOURS
from dataset_builder import build_dataset
from debug_utils import debug_log
from model_training import retrain_all
import runtime_config
from accuracy_tracker import evaluate_all, append_history_point
from radar_convlstm import train_convlstm
from config import AI_ANALYSIS_CONFIG


def run_rebuild_dataset_job():
    runtime_config.reload_overrides()
    debug_log("[SCHEDULER] Job rebuild_dataset gestartet")
    try:
        result = build_dataset()
        x_data = result.get("X") if isinstance(result, dict) else None
        sample_count = len(x_data) if x_data is not None else 0
        debug_log(f"[SCHEDULER] Job rebuild_dataset abgeschlossen (samples={sample_count})")
    except Exception as exc:
        debug_log(f"[SCHEDULER] Job rebuild_dataset Fehler: {exc}")


def run_retrain_job(job_name: str):
    runtime_config.reload_overrides()
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




def run_convlstm_weekly_job():
    debug_log("[SCHEDULER] Job convlstm_weekly gestartet")
    try:
        result = train_convlstm()
        debug_log(f"[SCHEDULER] Job convlstm_weekly abgeschlossen ({result})")
    except Exception as exc:
        debug_log(f"[SCHEDULER] Job convlstm_weekly Fehler: {exc}")


def run_ai_analysis_job():
    """Tägliche KI-Analyse (nur wenn AI_ANALYSIS_CONFIG.enabled == True)."""
    runtime_config.reload_overrides()
    cfg = runtime_config.get("AI_ANALYSIS_CONFIG", AI_ANALYSIS_CONFIG)
    if not cfg.get("enabled", False):
        debug_log("[SCHEDULER] Job ai_analysis übersprungen (deaktiviert)")
        return
    debug_log("[SCHEDULER] Job ai_analysis gestartet")
    try:
        from daily_analyzer import run_analysis
        result = run_analysis(cfg)
        n = len(result.get("suggestions", [])) if result else 0
        debug_log(f"[SCHEDULER] Job ai_analysis abgeschlossen ({n} Vorschläge, status={result.get('overall_status','?') if result else 'none'})")
    except Exception as exc:
        debug_log(f"[SCHEDULER] Job ai_analysis Fehler: {exc}")


def run_accuracy_eval_job():
    runtime_config.reload_overrides()
    debug_log("[SCHEDULER] Job accuracy_eval gestartet")
    try:
        from config import ML_FORECAST_HORIZONS_MIN
        horizons = runtime_config.get("ML_FORECAST_HORIZONS_MIN", ML_FORECAST_HORIZONS_MIN)
        result = evaluate_all(horizons, since_hours=24)
        append_history_point(result)
        debug_log(f"[SCHEDULER] accuracy_eval abgeschlossen: {result}")
    except Exception as exc:
        debug_log(f"[SCHEDULER] accuracy_eval Fehler: {exc}")

def create_scheduler() -> BlockingScheduler:
    sched = BlockingScheduler(timezone="Europe/Vienna")

    # KI-Analyse täglich (Uhrzeit aus AI_ANALYSIS_CONFIG)
    _ai_cfg = runtime_config.get("AI_ANALYSIS_CONFIG", AI_ANALYSIS_CONFIG)
    sched.add_job(
        run_ai_analysis_job,
        trigger=CronTrigger(
            hour=_ai_cfg.get("cron_hour", 6),
            minute=_ai_cfg.get("cron_minute", 0),
            timezone="Europe/Vienna",
        ),
        id="ai_analysis", max_instances=1, coalesce=True,
    )

    sched.add_job(
        run_rebuild_dataset_job,
        trigger=IntervalTrigger(minutes=runtime_config.get("DATASET_REBUILD_INTERVAL_MIN", DATASET_REBUILD_INTERVAL_MIN)),
        id="rebuild_dataset", max_instances=1, coalesce=True,
    )

    ts = runtime_config.get("TRAINING_SCHEDULE", {}) or {}
    sched.add_job(
        lambda: run_retrain_job("retrain_interval"),
        trigger=IntervalTrigger(hours=int(ts.get("retrain_interval_hours", RETRAIN_INTERVAL_HOURS))),
        id="retrain_interval", max_instances=1, coalesce=True,
    )
    sched.add_job(
        lambda: run_retrain_job("retrain_nightly"),
        trigger=CronTrigger(
            hour=int(ts.get("retrain_cron_hour", 3)),
            minute=int(ts.get("retrain_cron_minute", 0)),
        ),
        id="retrain_nightly", max_instances=1, coalesce=True,
    )
    sched.add_job(
        run_convlstm_weekly_job,
        trigger=CronTrigger(
            day_of_week=str(ts.get("convlstm_cron_day_of_week", "mon")),
            hour=int(ts.get("convlstm_cron_hour", 2)),
            minute=int(ts.get("convlstm_cron_minute", 0)),
        ),
        id="convlstm_weekly", max_instances=1, coalesce=True,
    )
    sched.add_job(
        run_accuracy_eval_job,
        trigger=IntervalTrigger(hours=1),
        id="accuracy_eval", max_instances=1, coalesce=True,
    )
    return sched


def main():
    scheduler = create_scheduler()
    debug_log("[SCHEDULER] gestartet")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        debug_log("[SCHEDULER] gestoppt (KeyboardInterrupt)")


if __name__ == "__main__":
    main()
