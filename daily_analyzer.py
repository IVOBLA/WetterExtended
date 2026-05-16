"""
daily_analyzer.py — Autonome KI-Analyse-Pipeline.

Läuft täglich per Scheduler (wenn AI_ANALYSIS_CONFIG['enabled'] == True).
Sammelt System-Metriken, sendet einen komprimierten Report an die
Anthropic API und speichert strukturierte Verbesserungsvorschläge.

Datenschutz: Es werden ausschließlich anonymisierte Metriken gesendet
(MAE-Werte, Fehlertypen, Zählungen). Keine Personendaten, keine Rohdaten.
"""

import glob
import json
import os
from datetime import datetime, timedelta
from typing import Optional

from config import (
    AI_ANALYSIS_CONFIG,
    AI_SUGGESTIONS_DIR,
    ML_FORECAST_HORIZONS_MIN,
    SAVE_PATHS,
)
from debug_utils import debug_log, log_api_failure
import runtime_config


# ---------------------------------------------------------------------------
# Report-Zusammenstellung
# ---------------------------------------------------------------------------

def _load_jsonl_tail(path: str, since_hours: int) -> list:
    """Liest JSONL-Datei, filtert auf die letzten since_hours."""
    if not os.path.exists(path):
        return []
    cutoff = datetime.utcnow() - timedelta(hours=since_hours)
    out = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line.strip())
                    ts_str = rec.get("timestamp_utc", "").replace("Z", "")
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str)
                        if ts >= cutoff:
                            out.append(rec)
                except Exception:
                    continue
    except Exception as exc:
        debug_log(f"[ANALYZER] Lesefehler {path}: {exc}")
    return out


def build_system_report(since_hours: int = 24) -> dict:
    """
    Baut einen komprimierten System-Report für den KI-Analyse-Aufruf.
    Maximale Größe: ~2000 Zeichen (Token-Budget schonen).
    """
    report = {
        "generated_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "since_hours": since_hours,
        "accuracy": {},
        "api_health": {},
        "model_quality": {},
        "data_quality": {},
        "system": {},
    }

    # --- Vorhersage-Genauigkeit ---
    try:
        from accuracy_tracker import evaluate_all

        horizons = runtime_config.get(
            "ML_FORECAST_HORIZONS_MIN", ML_FORECAST_HORIZONS_MIN
        )
        acc = evaluate_all(horizons, since_hours=since_hours)
        for h in acc.get("horizons", []):
            report["accuracy"][f"h{h['horizon']}"] = {
                "mae_km": h.get("mae_km"),
                "hit_rate": h.get("hit_rate"),
                "samples": h.get("samples"),
                "missed": h.get("missed"),
            }
    except Exception as exc:
        debug_log(f"[ANALYZER] accuracy Fehler: {exc}")

    # --- API-Health ---
    try:
        from debug_utils import api_health_summary

        health = api_health_summary(since_hours=since_hours)
        report["api_health"] = {
            "total_failures": health.get("total", 0),
            "by_service": {
                svc: {
                    "count": info.get("count", 0),
                    "top_reason": next(
                        iter(
                            sorted(
                                info.get("reasons", {}).items(),
                                key=lambda x: x[1],
                                reverse=True,
                            )
                        ),
                        (None,),
                    )[0],
                    "fallback_count": info.get("fallback_count", 0),
                }
                for svc, info in health.get("by_service", {}).items()
            },
        }
    except Exception as exc:
        debug_log(f"[ANALYZER] api_health Fehler: {exc}")

    # --- Modell-Qualität (letztes Training) ---
    try:
        meta_files = sorted(
            glob.glob(os.path.join(SAVE_PATHS["models"], "v_*/training_meta.json"))
        )
        if meta_files:
            with open(meta_files[-1], encoding="utf-8") as f:
                meta = json.load(f)
            report["model_quality"] = {
                "timestamp": meta.get("timestamp_utc"),
                "samples": meta.get("num_samples"),
                "mae_total": meta.get("validation", {}).get("mae_new"),
                "lstm_val_loss": meta.get("lstm", {}).get("val_loss"),
                "status": meta.get("validation", {}).get("status"),
            }
    except Exception as exc:
        debug_log(f"[ANALYZER] model_quality Fehler: {exc}")

    # --- Datenqualität (Rejection-Reasons) ---
    try:
        dataset_file = os.path.join(SAVE_PATHS["dataset"], "dataset.npz")
        if os.path.exists(dataset_file):
            import numpy as np

            data = np.load(dataset_file, allow_pickle=True)
            report["data_quality"]["samples_total"] = (
                int(data["X"].shape[0]) if "X" in data else 0
            )
    except Exception:
        pass

    # --- Systemressourcen (Raspberry Pi) ---
    try:
        import shutil

        disk = shutil.disk_usage("/")
        report["system"]["disk_free_gb"] = round(disk.free / 1e9, 1)
        report["system"]["disk_used_pct"] = round(disk.used / disk.total * 100, 1)
    except Exception:
        pass
    try:
        with open("/proc/meminfo") as f:
            lines = {l.split(":")[0]: l.split(":")[1].strip() for l in f.readlines()}
        mem_total = int(lines.get("MemTotal", "0 kB").split()[0])
        mem_avail = int(lines.get("MemAvailable", "0 kB").split()[0])
        if mem_total > 0:
            report["system"]["ram_used_pct"] = round(
                (mem_total - mem_avail) / mem_total * 100, 1
            )
    except Exception:
        pass

    return report


_SYSTEM_PROMPT = """Du bist ein automatischer Qualitätsanalyst für das
WetterExtended-System (Raspberry Pi 5, Hailo-8, Kärnten/Österreich).
Das System erkennt Gewitterzellen auf ARSO-Radarbildern und macht
ML-basierte Positionsvorhersagen.

Du erhältst täglich einen komprimierten Metrik-Report und antwortest
AUSSCHLIESSLICH mit einem validen JSON-Objekt — kein Text davor oder
danach, keine Markdown-Backticks.

JSON-Schema (strikt einhalten):
{
  "analysis_date": "ISO-Datum",
  "overall_status": "ok|warning|critical",
  "summary": "Max. 2 Sätze Gesamtbewertung.",
  "suggestions": [
    {
      "priority": "high|medium|low",
      "category": "accuracy|api|model|data|system|config",
      "title": "Kurztitel (max. 60 Zeichen)",
      "description": "Problembeschreibung (max. 150 Zeichen)",
      "action": "Konkrete Handlungsempfehlung (max. 200 Zeichen)"
    }
  ]
}

Maximal 5 Vorschläge, sortiert nach Priorität. Nur echte Probleme
melden, keine trivialen Hinweise. Wenn alles in Ordnung ist,
suggestions = [].
"""


def run_analysis(cfg: Optional[dict] = None) -> Optional[dict]:
    if cfg is None:
        cfg = runtime_config.get("AI_ANALYSIS_CONFIG", AI_ANALYSIS_CONFIG)
    if not cfg.get("enabled", False):
        debug_log("[ANALYZER] KI-Analyse deaktiviert (enabled=False)")
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        log_api_failure(
            "Anthropic-API",
            "https://api.anthropic.com/v1/messages",
            "ANTHROPIC_API_KEY nicht gesetzt",
            fallback_used=False,
        )
        return None

    since_hours = cfg.get("since_hours", 24)
    report = build_system_report(since_hours=since_hours)
    report_json = json.dumps(report, ensure_ascii=False, separators=(",", ":"))

    debug_log(
        f"[ANALYZER] Report erstellt ({len(report_json)} Zeichen), sende an Anthropic API..."
    )

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=cfg.get("model", "claude-sonnet-4-20250514"),
            max_tokens=cfg.get("max_tokens", 1500),
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (f"System-Report ({since_hours}h):\n{report_json}"),
                }
            ],
        )
        raw = message.content[0].text if message.content else ""
        debug_log(f"[ANALYZER] Antwort empfangen ({len(raw)} Zeichen)")
    except Exception as exc:
        log_api_failure(
            "Anthropic-API",
            "https://api.anthropic.com/v1/messages",
            f"{type(exc).__name__}: {exc}",
            fallback_used=False,
        )
        return None

    try:
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        result = json.loads(clean.strip())
    except Exception as exc:
        log_api_failure(
            "Anthropic-API",
            "https://api.anthropic.com/v1/messages",
            f"JSON-Parse-Fehler: {exc}",
            fallback_used=False,
        )
        debug_log(f"[ANALYZER] Roh-Antwort: {raw[:500]}")
        return None

    result["report_snapshot"] = {
        k: report[k]
        for k in ("generated_utc", "since_hours", "api_health", "model_quality", "system")
    }

    if cfg.get("save_suggestions", True):
        os.makedirs(AI_SUGGESTIONS_DIR, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
        out_path = os.path.join(AI_SUGGESTIONS_DIR, f"{ts}.json")
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            debug_log(f"[ANALYZER] Vorschläge gespeichert: {out_path}")
        except Exception as exc:
            debug_log(f"[ANALYZER] Speichern fehlgeschlagen: {exc}")

    return result


def load_latest_suggestions(n: int = 10) -> list:
    if not os.path.exists(AI_SUGGESTIONS_DIR):
        return []
    files = sorted(glob.glob(os.path.join(AI_SUGGESTIONS_DIR, "*.json")), reverse=True)[:n]
    results = []
    for p in files:
        try:
            with open(p, encoding="utf-8") as f:
                results.append(json.load(f))
        except Exception:
            continue
    return results


if __name__ == "__main__":
    import sys

    if "--dry-run" in sys.argv:
        report = build_system_report(24)
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        result = run_analysis()
        if result:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print("Kein Ergebnis (deaktiviert oder Fehler).")
