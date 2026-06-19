# scheduler.py
"""
APScheduler-basierter Hintergrund-Scheduler für WetterExtended.

Jobs die immer aktiv sind:
  ai_analysis        — tägliche KI-Analyse (nur wenn enabled=True in config)
  accuracy_eval      — stündliche Closed-Loop-Verifikation + Schwere-Verifikation
  data_cleanup       — tägliche Daten-Rotation (04:30, konfigurierbar)
  api_health_check   — täglicher API-Connectivity-Check (05:15)
  weekly_backup      — wöchentliches Backup (sonntags 02:00)
  atmospheric_snapshot — Atmosphären-Snapshot (Intervall konfigurierbar)
  outlook_series     — 12-h-Ausblick-Zeitreihe (alle 30 min, mit Frische-Guard)
  outlook_compute    — 12-h-Risiko-Raster berechnen (alle 30 min, lokal)
  cpu_monitor        — CPU-Monitoring (alle 5 min)
  stats_aggregate    — Langzeitstatistik-Aggregation (nächtlich)

Jobs nur wenn LOCAL_TRAINING=True:
  rebuild_dataset    — Datensatz-Rebuild (Intervall konfigurierbar)
  retrain_interval   — LightGBM/LSTM Retrain nach Intervall
                       (+ Schwere-Datensatz rebuild + Schwere-Modelle Regen/Böen)
  retrain_nightly    — Nightly Retrain per Cron (inkl. Schwere-Training)
  convlstm_weekly    — ConvLSTM-Training wöchentlich per Cron
"""

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import (
    AI_ANALYSIS_CONFIG,
    ATMOSPHERIC_SNAPSHOT_INTERVAL_MIN,
    CLAUDE_CODE_REPORT_CONFIG,
    DATA_CLEANUP_CRON_HOUR,
    DATA_CLEANUP_CRON_MINUTE,
    DATASET_REBUILD_INTERVAL_MIN,
    LOCAL_TRAINING,
    RETRAIN_INTERVAL_HOURS,
    SKYWARN_EXPORT_CRON_HOUR,
    SKYWARN_EXPORT_CRON_MINUTE,
)
from dataset_builder import build_dataset
from debug_utils import debug_log
from training_control import run_training_with_lock
import runtime_config
import api_circuit_breaker
import size_regressor as _size_reg_mod
from accuracy_tracker import evaluate_all, append_history_point
from cpu_monitor import append_cpu_sample


# ---------------------------------------------------------------------------
# Job-Funktionen
# ---------------------------------------------------------------------------

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

    # Size-Regresser: Retraining wenn fällig und LOCAL_TRAINING aktiv
    try:
        from config import LOCAL_TRAINING as _LOCAL_TRAINING
        if runtime_config.get("LOCAL_TRAINING", _LOCAL_TRAINING):
            _size_reg_mod.get_size_regressor().maybe_trigger_training()
    except Exception as _e:
        debug_log(f"[SIZE-REG] maybe_trigger_training Fehler: {_e}")


def run_retrain_job(job_name: str):
    runtime_config.reload_overrides()
    debug_log(f"[SCHEDULER] Job {job_name} gestartet")
    try:
        result = run_training_with_lock(source=f"scheduler:{job_name}")
        if result.get("running"):
            debug_log(f"[SCHEDULER] Job {job_name} übersprungen: Es läuft bereits ein Training")
            return
        meta = result.get("meta", {})
        trained_lstm = meta.get("lstm", {}).get("trained") if isinstance(meta, dict) else False
        trained_lgbm = meta.get("lgbm", {}).get("trained") if isinstance(meta, dict) else False
        debug_log(
            f"[SCHEDULER] Job {job_name} abgeschlossen "
            f"(lstm_trained={trained_lstm}, lgbm_trained={trained_lgbm})"
        )
    except Exception as exc:
        debug_log(f"[SCHEDULER] Job {job_name} Fehler: {exc}")


def run_convlstm_weekly_job():
    """B147: ConvLSTM-Training läuft als ISOLIERTER Subprozess. Ein OOM/Crash (auch ein
    nicht abfangbares SIGKILL des Kindes) beendet NUR das Kind — der Scheduler-Dienst
    überlebt. Das Kind bekommt ein Adressraum-Limit (RLIMIT_AS), damit nicht der
    system-weite OOM-Killer fremde Dienste trifft."""
    import os as _os
    import sys as _sys
    import subprocess as _sp

    runtime_config.reload_overrides()
    debug_log("[SCHEDULER] Job convlstm_weekly gestartet (isolierter Subprozess)")

    try:
        from config import CONVLSTM_TRAIN_TIMEOUT_S as _timeout
    except Exception:
        _timeout = 7200
    _timeout = int(runtime_config.get("CONVLSTM_TRAIN_TIMEOUT_S", _timeout))

    try:
        from config import CONVLSTM_TRAIN_MEM_LIMIT_GB as _mem_gb
    except Exception:
        _mem_gb = 12
    _mem_gb = int(runtime_config.get("CONVLSTM_TRAIN_MEM_LIMIT_GB", _mem_gb))

    project_root = _os.path.dirname(_os.path.abspath(__file__))

    def _limit_mem():
        try:
            import resource
            soft = _mem_gb * 1024 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (soft, soft))
        except Exception:
            pass

    cmd = [_sys.executable, _os.path.join(project_root, "radar_convlstm.py"), "--train"]
    try:
        proc = _sp.run(
            cmd, cwd=project_root, timeout=_timeout,
            stdout=_sp.PIPE, stderr=_sp.STDOUT, text=True,
            preexec_fn=_limit_mem if _os.name == "posix" else None,
        )
        tail = (proc.stdout or "")[-2000:]
        if proc.returncode == 0:
            debug_log(f"[SCHEDULER] Job convlstm_weekly abgeschlossen (rc=0). {tail}")
        elif proc.returncode in (-9, 137):
            debug_log(
                "[SCHEDULER] Job convlstm_weekly: Kind getötet (OOM/SIGKILL, "
                f"rc={proc.returncode}) — Scheduler läuft weiter. {tail}"
            )
        else:
            debug_log(f"[SCHEDULER] Job convlstm_weekly Fehler (rc={proc.returncode}). {tail}")
    except _sp.TimeoutExpired:
        debug_log(f"[SCHEDULER] Job convlstm_weekly Timeout (> {_timeout}s) — abgebrochen.")
    except Exception as exc:
        debug_log(f"[SCHEDULER] Job convlstm_weekly Fehler beim Start: {exc}")


def _cells_detected_today() -> bool:
    """
    Prüft ob heute (Europe/Vienna) mindestens eine Sturmzelle erkannt wurde.
    Liest cells_log.jsonl — jeder Eintrag hat ts (YYYY-MM-DD_HH-MM-SS) und count.
    Gibt True zurück sobald ein Eintrag mit count > 0 für heute gefunden wird.
    """
    import json as _j
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    from config import SAVE_PATHS as _SP
    import os as _o

    today = _dt.now(ZoneInfo("Europe/Vienna")).strftime("%Y-%m-%d")
    log_path = _o.path.join(
        _SP.get("evaluation", "train_data/evaluation"), "cells_log.jsonl"
    )
    if not _o.path.exists(log_path):
        return False
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = _j.loads(line)
                    # ts-Format: "2026-05-20_12-40-02"
                    if entry.get("ts", "").startswith(today) and entry.get("count", 0) > 0:
                        return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


def run_ai_analysis_job():
    """Tägliche KI-Analyse (nur wenn AI_ANALYSIS_CONFIG.enabled == True)."""
    runtime_config.reload_overrides()
    cfg = runtime_config.get("AI_ANALYSIS_CONFIG", AI_ANALYSIS_CONFIG)
    if not cfg.get("enabled", False):
        debug_log("[SCHEDULER] Job ai_analysis übersprungen (deaktiviert)")
        return
    if cfg.get("only_if_cells", False) and not _cells_detected_today():
        debug_log("[SCHEDULER] Job ai_analysis übersprungen (only_if_cells=True, heute keine Zellen erkannt)")
        return
    debug_log("[SCHEDULER] Job ai_analysis gestartet")
    try:
        from daily_analyzer import run_analysis

        result = run_analysis(cfg)
        n = len(result.get("suggestions", [])) if result else 0
        debug_log(
            f"[SCHEDULER] Job ai_analysis abgeschlossen "
            f"({n} Vorschläge, status={result.get('overall_status', '?') if result else 'none'})"
        )
    except Exception as exc:
        debug_log(f"[SCHEDULER] Job ai_analysis Fehler: {exc}")


def run_accuracy_eval_job():
    runtime_config.reload_overrides()
    debug_log("[SCHEDULER] Job accuracy_eval gestartet")
    try:
        from config import ML_FORECAST_HORIZONS_MIN, SAVE_PATHS

        horizons = runtime_config.get("ML_FORECAST_HORIZONS_MIN", ML_FORECAST_HORIZONS_MIN)
        result = evaluate_all(horizons, since_hours=24)
        append_history_point(result)

        try:
            from severity_verification import evaluate_severity
            sev = evaluate_severity(24)
            debug_log(f"[SCHEDULER] severity_verify: {sev}")
        except Exception as _sev_exc:
            debug_log(f"[SCHEDULER] severity_verify Fehler: {_sev_exc}")

        # Drift-Detection: MAE-Trend prüfen + ggf. Alarm senden
        try:
            from drift_detector import check_and_alert as _drift_check
            _drift_status = _drift_check(result)
            if _drift_status.get("drift_detected"):
                debug_log(f"[SCHEDULER] DRIFT ALARM: {_drift_status.get('message')}")
        except Exception as _drift_exc:
            debug_log(f"[SCHEDULER] Drift-Check Fehler: {_drift_exc}")

        # B126: Health-Check differenzieren — Schönwetter (keine Zellen) ist
        # KEIN Defekt. Nur "Zellen vorhanden, aber forecast_lat_* fehlt" warnen.
        all_zero = all(h.get("samples", 0) == 0 for h in result.get("horizons", []))
        if all_zero:
            import os as _os, json as _jh, datetime as _dt
            from accuracy_tracker import classify_zero_sample_health
            eval_dir = SAVE_PATHS.get("evaluation", "train_data/evaluation")
            obj_dir  = SAVE_PATHS.get("objects", "train_data/objects")
            _hc = classify_zero_sample_health(obj_dir, since_hours=24)
            if _hc["severity"] == "info":
                debug_log(
                    f"[ACCURACY][INFO] Keine Zellen im Beobachtungszeitraum "
                    f"({_hc['obj_files']} Objekt-Dateien, alle leer) — Ruhephase, kein Defekt."
                )
            elif _hc["event"] == "missing_forecast_fields":
                debug_log(
                    f"[ACCURACY][HEALTH-WARN] {_hc['total_cells']} Zellen vorhanden, aber KEINE mit "
                    f"forecast_lat_* — predict_positions() lief nicht ({_hc['obj_files']} Objekt-Dateien)."
                )
            else:
                debug_log(
                    f"[ACCURACY][HEALTH-WARN] 0 verifizierbare Samples trotz "
                    f"{_hc['cells_with_forecast']}/{_hc['total_cells']} Zellen mit Vorhersage — "
                    f"Matching/Zeit-Toleranz prüfen."
                )
            _os.makedirs(eval_dir, exist_ok=True)
            with open(_os.path.join(eval_dir, "accuracy_health.jsonl"), "a", encoding="utf-8") as _hf:
                _jh.dump({
                    "ts":        _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    "event":     _hc["event"],
                    "severity":  _hc["severity"],
                    "obj_files": _hc["obj_files"],
                    "total_cells": _hc["total_cells"],
                    "cells_with_forecast": _hc["cells_with_forecast"],
                    "horizons":  horizons,
                }, _hf)
                _hf.write("\n")
        else:
            debug_log(f"[SCHEDULER] accuracy_eval abgeschlossen: {result}")
    except Exception as exc:
        debug_log(f"[SCHEDULER] accuracy_eval Fehler: {exc}")


def run_claude_code_report_job():
    """
    Sendet analysis_result.json vom Branch debug-export-latest per E-Mail.
    Konfiguration: CLAUDE_CODE_REPORT_CONFIG (unabhängig von AI_ANALYSIS_CONFIG).
    Strategie: git fetch + git show (SSH, kein extra Token, kein Branch-Wechsel).
    """
    runtime_config.reload_overrides()
    debug_log("[SCHEDULER] Job claude_code_report gestartet")

    import json as _json
    import subprocess as _sub
    from datetime import datetime as _dt, timezone as _tz
    from pathlib import Path as _Path

    try:
        from config import CLAUDE_CODE_REPORT_CONFIG as _default
        _cfg = dict(_default)
        _cfg.update(runtime_config.get("CLAUDE_CODE_REPORT_CONFIG", {}))

        if not _cfg.get("enabled", True):
            debug_log("[SCHEDULER] claude_code_report: deaktiviert (enabled=False)")
            return

        report_email = _cfg.get("report_email", "").strip()
        if not report_email:
            debug_log(
                "[SCHEDULER] claude_code_report: report_email leer — "
                "im Admin-Panel unter 'Code-Analyse-Report' eintragen."
            )
            return

        branch = _cfg.get("branch", "debug-export-latest")
        project_dir = str(_Path(__file__).resolve().parent)

        fetch = _sub.run(
            ["git", "fetch", "origin", branch],
            cwd=project_dir, capture_output=True, text=True,
        )
        if fetch.returncode != 0:
            debug_log(
                f"[SCHEDULER] claude_code_report: git fetch fehlgeschlagen "
                f"(rc={fetch.returncode}): {fetch.stderr.strip()}"
            )
            return

        log_out = _sub.run(
            ["git", "log", f"origin/{branch}", "--format=%cI", "-1",
             "--", "analysis_result.json"],
            cwd=project_dir, capture_output=True, text=True,
        )
        commit_ts_raw = log_out.stdout.strip()
        if not commit_ts_raw:
            debug_log(
                f"[SCHEDULER] claude_code_report: analysis_result.json nicht auf "
                f"origin/{branch} — noch kein Analyse-Lauf?"
            )
            return

        try:
            commit_ts = _dt.fromisoformat(commit_ts_raw)
            if commit_ts.tzinfo is None:
                commit_ts = commit_ts.replace(tzinfo=_tz.utc)
            age_h = (_dt.now(_tz.utc) - commit_ts).total_seconds() / 3600
        except Exception as _te:
            debug_log(f"[SCHEDULER] claude_code_report: Timestamp-Parse Fehler: {_te}")
            age_h = 0.0

        if age_h > 26:
            debug_log(
                f"[SCHEDULER] claude_code_report: Datei ist {age_h:.1f}h alt (>26h) "
                "— übersprungen."
            )
            return

        show = _sub.run(
            ["git", "show", f"origin/{branch}:analysis_result.json"],
            cwd=project_dir, capture_output=True, text=True,
        )
        if show.returncode != 0:
            debug_log(
                f"[SCHEDULER] claude_code_report: git show fehlgeschlagen: "
                f"{show.stderr.strip()}"
            )
            return

        result = _json.loads(show.stdout)

        from email_notifier import send_claude_code_report_email
        ok = send_claude_code_report_email(result, report_email)
        debug_log(
            f"[SCHEDULER] claude_code_report: "
            f"{'gesendet' if ok else 'FEHLER'} → {report_email} "
            f"(Branch: {branch}, Alter: {age_h:.1f}h)"
        )

    except Exception as exc:
        debug_log(f"[SCHEDULER] claude_code_report Fehler: {exc}")


def run_cleanup_job():
    """Tägliche Daten-Rotation — löscht Dateien älter als DATA_RETENTION_DAYS."""
    runtime_config.reload_overrides()
    debug_log("[SCHEDULER] Job data_cleanup gestartet")
    try:
        from cleanup_old_data import cleanup_old_data

        result = cleanup_old_data()
        debug_log(
            f"[SCHEDULER] Job data_cleanup abgeschlossen: "
            f"{result.get('deleted_count', 0)} Dateien gelöscht, "
            f"{result.get('freed_mb', 0)} MB freigegeben."
        )
    except Exception as exc:
        debug_log(f"[SCHEDULER] Job data_cleanup Fehler: {exc}")




def run_api_cache_cleanup_job():
    """Räumt API-Cache-Dateien älter als 7 Tage auf."""
    try:
        from api_cache import cache_cleanup
        n = cache_cleanup(max_age_seconds=7 * 24 * 3600)
        debug_log(f"[SCHEDULER] api_cache_cleanup: {n} Dateien entfernt.")
    except Exception as exc:
        debug_log(f"[SCHEDULER] api_cache_cleanup Fehler: {exc}")
def run_atmospheric_snapshot_job():
    """Atmosphärischer Zustand für Kärnten-Referenzpunkte — unabhängig von Zellen."""
    runtime_config.reload_overrides()
    if api_circuit_breaker.is_open("open_meteo_atmosphere"):
        debug_log("[SCHEDULER] atmospheric_snapshot übersprungen: Circuit offen")
        return
    debug_log("[SCHEDULER] Job atmospheric_snapshot gestartet")
    try:
        from fetch_atmospheric_snapshot import fetch_atmospheric_snapshot
        result = fetch_atmospheric_snapshot()
        n = len(result.get("locations", []))
        debug_log(f"[SCHEDULER] atmospheric_snapshot abgeschlossen ({n} Orte)")
    except Exception as exc:
        debug_log(f"[SCHEDULER] atmospheric_snapshot Fehler: {exc}")


def run_outlook_series_job():
    """Holt die 12-h-Zeitreihe der konvektiven Felder (Frische-Guard inside)."""
    runtime_config.reload_overrides()
    debug_log("[SCHEDULER] Job outlook_series gestartet")
    try:
        from fetch_outlook_series import fetch_outlook_series
        res = fetch_outlook_series()
        debug_log(f"[SCHEDULER] outlook_series abgeschlossen ({len(res.get('points', []))} Punkte)")
    except Exception as exc:
        debug_log(f"[SCHEDULER] outlook_series Fehler: {exc}")


def run_outlook_compute_job():
    """Berechnet die 12 Stunden-Raster aus der Zeitreihe."""
    runtime_config.reload_overrides()
    if api_circuit_breaker.is_open("open_meteo_outlook"):
        debug_log("[SCHEDULER] outlook_compute: Outlook-Circuit offen, nutze lokale Zeitreihe falls vorhanden")
    debug_log("[SCHEDULER] Job outlook_compute gestartet")
    try:
        from convective_outlook import compute_outlook
        r = compute_outlook()
        debug_log(f"[SCHEDULER] outlook_compute abgeschlossen ({len(r.get('hours', []))} Stunden)")
    except Exception as exc:
        debug_log(f"[SCHEDULER] outlook_compute Fehler: {exc}")


def run_api_health_job():
    """Täglicher API-Connectivity-Check (05:15 Europe/Vienna)."""
    debug_log("[SCHEDULER] Job api_health_check gestartet")
    try:
        from api_health_check import check_all_apis
        result = check_all_apis()
        status = "OK" if result.get("all_ok") else "PROBLEME ERKANNT"
        debug_log(f"[SCHEDULER] API-Health: {status}")
    except Exception as exc:
        debug_log(f"[SCHEDULER] API-Health Fehler: {exc}")


def run_backup_job():
    """Wöchentliches Backup von Modellen + Secrets (sonntags 02:00)."""
    import subprocess
    import os as _os
    debug_log("[SCHEDULER] Job weekly_backup gestartet")
    script = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "backup_wetterprojekt.sh")
    if not _os.path.isfile(script):
        debug_log(f"[BACKUP] backup_wetterprojekt.sh nicht gefunden: {script}")
        return
    try:
        result = subprocess.run(
            ["bash", script],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=_os.path.dirname(script),
        )
        for line in result.stdout.strip().splitlines():
            debug_log(line)
        if result.returncode != 0:
            debug_log(f"[BACKUP] Fehler (rc={result.returncode}): {result.stderr.strip()[:300]}")
    except subprocess.TimeoutExpired:
        debug_log("[BACKUP] Timeout nach 300 s")
    except Exception as exc:
        debug_log(f"[BACKUP] Exception: {type(exc).__name__}: {exc}")


def run_cpu_monitor_job():
    """CPU-Auslastung aller Kerne sampeln und in cpu_history.jsonl speichern."""
    try:
        append_cpu_sample()
    except Exception as exc:
        debug_log(f"[SCHEDULER] Job cpu_monitor Fehler: {exc}")



def run_skywarn_export_snapshot_job():
    """Daily Skywarn snapshot for the 24h debug export only."""
    debug_log("[SCHEDULER] Job skywarn_export_snapshot gestartet")
    try:
        from skywarn_export_snapshot import fetch_and_store_skywarn_export_snapshot

        result = fetch_and_store_skywarn_export_snapshot(force=False)
        status = result.get("status") if isinstance(result, dict) else "unknown"
        if status == "ok":
            features = result.get("features_inside_kaernten_bbox", {}).get("features", [])
            debug_log(
                "[SCHEDULER] Skywarn Export-Snapshot abgeschlossen "
                f"(status={status}, valid_from={result.get('valid_from')}, "
                f"valid_to={result.get('valid_to')}, features={len(features)}, "
                f"max_severity={result.get('max_severity_inside_kaernten_bbox')})"
            )
        elif status == "error":
            err = result.get("error") or {}
            debug_log(
                "[SCHEDULER] Skywarn Export-Snapshot Fehler "
                f"(type={err.get('type')}, http_status={err.get('http_status')}, "
                f"message={err.get('message')})"
            )
        else:
            debug_log(f"[SCHEDULER] Skywarn Export-Snapshot: status={status}")
    except Exception as exc:
        debug_log(f"[SCHEDULER] Skywarn Export-Snapshot unerwarteter Fehler: {exc}")


def run_stats_aggregate_job():
    """P-S02: Nächtliche Langzeitstatistik-Aggregation (immer aktiv)."""
    from stats_aggregator import aggregate

    runtime_config.reload_overrides()
    debug_log("[SCHEDULER] Job stats_aggregate gestartet")
    try:
        result = aggregate()
        debug_log(f"[SCHEDULER] stats_aggregate abgeschlossen: {result}")
    except Exception as exc:
        debug_log(f"[SCHEDULER] stats_aggregate Fehler: {exc}")


# ---------------------------------------------------------------------------
# Scheduler erstellen
# ---------------------------------------------------------------------------

def create_scheduler() -> BlockingScheduler:
    # LOCAL_TRAINING aus runtime_overrides (Laufzeit) oder config (Default)
    local_training = runtime_config.get("LOCAL_TRAINING", LOCAL_TRAINING)

    if local_training:
        debug_log("[SCHEDULER] LOCAL_TRAINING=True — alle Training-Jobs aktiv.")
    else:
        debug_log("[SCHEDULER] LOCAL_TRAINING=False — Training-Jobs deaktiviert.")
        debug_log("[SCHEDULER] Aktive Jobs: accuracy_eval, ai_analysis, data_cleanup")

    # B146: Verpasste Jobs (z.B. nächtliches retrain_nightly nach kurzer Downtime) holen
    # bis SCHEDULER_MISFIRE_GRACE_S nach, statt erst am Folgetag zu laufen.
    try:
        from config import SCHEDULER_MISFIRE_GRACE_S as _misfire_grace
    except Exception:
        _misfire_grace = 3600
    sched = BlockingScheduler(
        timezone="Europe/Vienna",
        job_defaults={
            "coalesce": True,
            "misfire_grace_time": int(runtime_config.get("SCHEDULER_MISFIRE_GRACE_S", _misfire_grace)),
        },
    )

    # --- immer aktiv: KI-Analyse ---
    _ai_cfg  = runtime_config.get("AI_ANALYSIS_CONFIG", AI_ANALYSIS_CONFIG)
    _ai_days = _ai_cfg.get("cron_days", "mon,tue,wed,thu,fri,sat,sun").strip()
    _ai_days = _ai_days if _ai_days else "mon,tue,wed,thu,fri,sat,sun"
    sched.add_job(
        run_ai_analysis_job,
        trigger=CronTrigger(
            day_of_week=_ai_days,
            hour=_ai_cfg.get("cron_hour", 6),
            minute=_ai_cfg.get("cron_minute", 0),
            timezone="Europe/Vienna",
        ),
        id="ai_analysis", max_instances=1, coalesce=True,
    )
    debug_log(
        f"[SCHEDULER] KI-Analyse: {_ai_days} "
        f"um {_ai_cfg.get('cron_hour', 6):02d}:{_ai_cfg.get('cron_minute', 0):02d}"
    )

    # --- immer aktiv: Accuracy-Eval ---
    sched.add_job(
        run_accuracy_eval_job,
        trigger=IntervalTrigger(hours=1),
        id="accuracy_eval", max_instances=1, coalesce=True,
    )

    # --- immer aktiv: Claude-Code-Report-Mail (unabhängig von AI_ANALYSIS_CONFIG) ---
    _cc_cfg = runtime_config.get("CLAUDE_CODE_REPORT_CONFIG", CLAUDE_CODE_REPORT_CONFIG)
    _cc_h = int(_cc_cfg.get("cron_hour", CLAUDE_CODE_REPORT_CONFIG["cron_hour"]))
    _cc_m = int(_cc_cfg.get("cron_minute", CLAUDE_CODE_REPORT_CONFIG["cron_minute"]))
    sched.add_job(
        run_claude_code_report_job,
        trigger=CronTrigger(hour=_cc_h, minute=_cc_m, timezone="Europe/Vienna"),
        id="claude_code_report", max_instances=1, coalesce=True,
    )
    debug_log(
        f"[SCHEDULER] Claude-Code-Report-Mail: täglich {_cc_h:02d}:{_cc_m:02d} "
        f"Europe/Vienna (Branch: {_cc_cfg.get('branch', 'debug-export-latest')})"
    )

    # --- immer aktiv: Daten-Cleanup ---
    sched.add_job(
        run_cleanup_job,
        trigger=CronTrigger(
            hour=runtime_config.get("DATA_CLEANUP_CRON_HOUR", DATA_CLEANUP_CRON_HOUR),
            minute=runtime_config.get("DATA_CLEANUP_CRON_MINUTE", DATA_CLEANUP_CRON_MINUTE),
        ),
        id="data_cleanup", max_instances=1, coalesce=True,
    )



    # --- immer aktiv: Täglicher API-Connectivity-Check (05:15) ---
    sched.add_job(
        run_api_health_job,
        trigger=CronTrigger(hour=5, minute=15, timezone="Europe/Vienna"),
        id="api_health_check", max_instances=1, coalesce=True,
    )

    # --- immer aktiv: Wöchentliches Backup (sonntags 02:00) ---
    sched.add_job(
        run_backup_job,
        trigger=CronTrigger(
            day_of_week="sun",
            hour=2,
            minute=0,
            timezone="Europe/Vienna",
        ),
        id="weekly_backup", max_instances=1, coalesce=True,
    )

    # --- immer aktiv: API-Cache-Cleanup (täglich, 7 Tage Aufbewahrung) ---
    sched.add_job(
        run_api_cache_cleanup_job,
        trigger=CronTrigger(hour=4, minute=45, timezone="Europe/Vienna"),
        id="api_cache_cleanup", max_instances=1, coalesce=True,
    )

    # --- immer aktiv: Skywarn Export-Snapshot (nur gespeicherte Datei für 24h-Debug-Export) ---
    sched.add_job(
        run_skywarn_export_snapshot_job,
        trigger=CronTrigger(
            hour=runtime_config.get("SKYWARN_EXPORT_CRON_HOUR", SKYWARN_EXPORT_CRON_HOUR),
            minute=runtime_config.get("SKYWARN_EXPORT_CRON_MINUTE", SKYWARN_EXPORT_CRON_MINUTE),
            timezone="Europe/Vienna",
        ),
        id="skywarn_export_snapshot", max_instances=1, coalesce=True,
    )
    debug_log("[SCHEDULER] Skywarn Export-Snapshot: täglich 12:00 Europe/Vienna")

    # --- immer aktiv: CPU-Monitoring (alle 5 Min) ---
    sched.add_job(
        run_cpu_monitor_job,
        trigger=IntervalTrigger(minutes=5),
        id="cpu_monitor", max_instances=1, coalesce=True,
    )

    # --- immer aktiv: Langzeitstatistik-Aggregation (nächtlich) ---
    from config import STATS_AGGREGATE_CRON_HOUR, STATS_AGGREGATE_CRON_MINUTE
    sched.add_job(
        run_stats_aggregate_job,
        trigger=CronTrigger(
            hour=runtime_config.get("STATS_AGGREGATE_CRON_HOUR", STATS_AGGREGATE_CRON_HOUR),
            minute=runtime_config.get("STATS_AGGREGATE_CRON_MINUTE", STATS_AGGREGATE_CRON_MINUTE),
            timezone="Europe/Vienna",
        ),
        id="stats_aggregate", max_instances=1, coalesce=True,
    )
    for _svc in ("open_meteo_outlook", "open_meteo_atmosphere"):
        debug_log(f"[SCHEDULER] Circuit-Status {_svc}: {api_circuit_breaker.get_status(_svc)}")

    # --- immer aktiv: Atmosphären-Snapshot ---
    sched.add_job(
        run_atmospheric_snapshot_job,
        trigger=IntervalTrigger(
            minutes=runtime_config.get(
                "ATMOSPHERIC_SNAPSHOT_INTERVAL_MIN", ATMOSPHERIC_SNAPSHOT_INTERVAL_MIN
            ),
            seconds=60,
        ),
        id="atmospheric_snapshot", max_instances=1, coalesce=True,
    )

    # --- immer aktiv: 12-h-Ausblick-Zeitreihe (Frische-Guard verhindert Mehrfach-Requests) ---
    sched.add_job(
        run_outlook_series_job,
        trigger=IntervalTrigger(
            minutes=runtime_config.get("OUTLOOK_SERIES_INTERVAL_MIN", 30)
        ),
        id="outlook_series", max_instances=1, coalesce=True,
    )

    # --- immer aktiv: Ausblick-Raster (liest nur lokale Dateien) ---
    sched.add_job(
        run_outlook_compute_job,
        trigger=IntervalTrigger(
            minutes=runtime_config.get("OUTLOOK_COMPUTE_INTERVAL_MIN", 30)
        ),
        id="outlook_compute", max_instances=1, coalesce=True,
    )

    # --- nur wenn LOCAL_TRAINING=True ---
    if local_training:
        sched.add_job(
            run_rebuild_dataset_job,
            trigger=IntervalTrigger(
                minutes=runtime_config.get(
                    "DATASET_REBUILD_INTERVAL_MIN", DATASET_REBUILD_INTERVAL_MIN
                )
            ),
            id="rebuild_dataset", max_instances=1, coalesce=True,
        )

        ts = runtime_config.get("TRAINING_SCHEDULE", {}) or {}
        sched.add_job(
            lambda: run_retrain_job("retrain_interval"),
            trigger=IntervalTrigger(
                hours=int(ts.get("retrain_interval_hours", RETRAIN_INTERVAL_HOURS))
            ),
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

    return sched


def main():
    import watchdog_heartbeat
    watchdog_heartbeat.start()          # systemd READY=1 + Watchdog-Ping alle 25 s
    scheduler = create_scheduler()
    debug_log("[SCHEDULER] gestartet")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        debug_log("[SCHEDULER] gestoppt (KeyboardInterrupt)")


if __name__ == "__main__":
    main()
