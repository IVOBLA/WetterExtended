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
import urllib.request
import urllib.error
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
# Quellcode-Kontext — ausschliesslich von GitHub (autoritäre Quelle)
# ---------------------------------------------------------------------------

def _fetch_github_file(repo: str, branch: str, filepath: str,
                       token: str = "", max_lines: int = 120) -> tuple:
    """
    Holt eine Datei von raw.githubusercontent.com.
    Gibt (content: str, status: str) zurück.
    status: 'ok' | 'not_found' | 'auth_error' | 'rate_limit' | 'network_error'
    """
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/{filepath}"
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"token {token}")
    req.add_header("User-Agent", "WetterExtended-Analyzer/1.0")
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            lines = raw.splitlines(keepends=True)
            if len(lines) > max_lines:
                content = "".join(lines[:max_lines])
                content += f"\n... ({len(lines) - max_lines} weitere Zeilen gekürzt)\n"
            else:
                content = raw
            return content, "ok"
    except urllib.error.HTTPError as exc:
        codes = {404: "not_found", 401: "auth_error", 403: "rate_limit"}
        return f"[GitHub HTTP {exc.code}: {filepath}]", codes.get(exc.code, "network_error")
    except Exception as exc:
        return f"[GitHub Fehler: {exc}]", "network_error"


def _collect_source_context() -> dict:
    """
    Holt Quellcode aller konfigurierten Dateien ausschliesslich von GitHub.
    Kein Zugriff auf lokale Dateien. GitHub-Stand ist die einzige Quelle.
    """
    from config import GITHUB_VERIFY_CONFIG
    gh = runtime_config.get("GITHUB_VERIFY_CONFIG", GITHUB_VERIFY_CONFIG)

    repo      = gh.get("repo",   "IVOBLA/WetterExtended")
    branch    = gh.get("branch", "main")
    token     = gh.get("token",  "")
    files     = gh.get("files",  [])
    max_lines = gh.get("max_lines_per_file", 120)

    ctx = {
        "source":  "github",
        "repo":    repo,
        "branch":  branch,
        "files":   {},
        "errors":  [],
    }

    ok_count  = 0
    err_count = 0
    for fname in files:
        content, status = _fetch_github_file(repo, branch, fname, token, max_lines)
        ctx["files"][fname] = {"content": content, "status": status}
        if status == "ok":
            ok_count += 1
        else:
            err_count += 1
            ctx["errors"].append({"file": fname, "reason": status})

    debug_log(
        f"[ANALYZER] GitHub-Source: {ok_count} Dateien geladen, "
        f"{err_count} Fehler (repo={repo}, branch={branch})"
    )
    return ctx


# ---------------------------------------------------------------------------
# Erkannte Sturmzellen — letzte N Frames für KI-Analyse
# ---------------------------------------------------------------------------

def _load_recent_objects(n_frames: int = 5) -> list:
    """
    Lädt die letzten n_frames Objekt-JSON-Dateien aus SAVE_PATHS['objects'].
    Gibt Liste von Frames zurück: [{"timestamp": str, "cell_count": int, "cells": [...]}]
    Felder pro Zelle werden auf KI-relevante Keys reduziert (Token-Budget).
    """
    objects_dir = SAVE_PATHS.get("objects", "data/objects")
    if not os.path.isdir(objects_dir):
        return []

    files = sorted(
        [f for f in os.listdir(objects_dir) if f.endswith(".json")],
        reverse=True,
    )[:n_frames]

    _CELL_KEYS = (
        "id", "lat", "lon", "size", "core_ratio",
        "vx", "vy", "missing", "lineage",
        "cape", "cloud_top_height_m", "lightning_count_10km",
        "of_magnitude", "of_angle",
        "arome_precip_mm", "arome_cape",
        "intensity", "intensity_label",
    )

    frames = []
    for fname in reversed(files):
        fpath = os.path.join(objects_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                raw_cells = json.load(f)
        except Exception as exc:
            debug_log(f"[ANALYZER] Objekt-Lesefehler {fname}: {exc}")
            continue

        slim_cells = []
        for cell in raw_cells:
            slim = {k: cell[k] for k in _CELL_KEYS if k in cell}
            for h in (10, 20, 30):
                for ax in ("lat", "lon"):
                    key = f"forecast_{ax}_{h}"
                    if key in cell:
                        slim[key] = cell[key]
            slim_cells.append(slim)

        frames.append({
            "timestamp":  fname.replace(".json", ""),
            "cell_count": len(slim_cells),
            "cells":      slim_cells,
        })

    return frames


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
        "source_context": {},
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

    # --- Quellcode von GitHub ---
    try:
        report["source_context"] = _collect_source_context()
    except Exception as exc:
        debug_log(f"[ANALYZER] Source-Kontext Fehler: {exc}")
        report["source_context"] = {"source": "error", "error": str(exc)}

    # --- Erkannte Sturmzellen (letzte 5 Frames) ---
    try:
        recent = _load_recent_objects(n_frames=5)
        report["recent_objects"] = {
            "description": (
                "Letzte 5 erkannte Radar-Frames. Felder je Zelle: "
                "id, lat/lon, size(px), core_ratio, vx/vy(px/frame), "
                "cape(J/kg), cloud_top_height_m, lightning_count_10km, "
                "of_magnitude/angle, arome_precip_mm, intensity_label, "
                "forecast_lat/lon_10/20/30."
            ),
            "frames":      recent,
            "frame_count": len(recent),
        }
    except Exception as exc:
        debug_log(f"[ANALYZER] recent_objects Fehler: {exc}")
        report["recent_objects"] = {"frames": [], "frame_count": 0}

    return report


_SYSTEM_PROMPT = """
Du bist ein autonomer Code-, Daten- und Wetteranalyse-Experte für das
WetterExtended-Sturmzell-Tracking-System in Kärnten/Österreich.
Hardware: Raspberry Pi 5, Hailo-8 AI (26 TOPS), 16 GB RAM. OS: Raspbian.
Radardaten: ARSO INCA (5-min-Takt). Zielgebiet: Klagenfurt, Villach,
Wolfsberg, Spittal, St. Veit (lat 46.3–47.1 / lon 13.0–15.2).

Der Report enthält:

1) source_context.files — Quellcode direkt von GitHub (repo IVOBLA/WetterExtended).
   Dies ist der OFFIZIELLE, committete Stand. Kein lokaler Code.
   Jede Datei: {"content": "<erste 120 Zeilen>", "status": "ok|not_found|..."}
   source_context.errors — Dateien die nicht von GitHub geladen werden konnten.

2) recent_objects — letzte 5 erkannte Radar-Frames mit Sturmzellen.
   Felder je Zelle: id, lat, lon, size(px), core_ratio, vx, vy,
   cape(J/kg), cloud_top_height_m, lightning_count_10km,
   of_magnitude, of_angle, arome_precip_mm, arome_cape,
   intensity, intensity_label, forecast_lat/lon_10/20/30.

3) Metriken: accuracy (MAE/hit-rate je Horizont), api_health, model_quality,
   data_quality, system (RAM, Disk).

Analysiere ALLE Teile. Erkenne:
- CODE: Bugs, fehlende Fehlerbehandlung, hardcodierte Werte, inkonsistente
  Logik, API-Aufrufe mit falschen Parametern (URLs, Query-Params, Auth).
  Dateiname + Funktion/Zeile bei Befunden angeben.
- METRIKEN: schlechte MAE/Hit-Rate, API-Ausfälle, Modell-Drift.
- WETTERLAGE: unplausible Objektwerte (vx/vy > ±50 px/frame, cape > 5000),
  fehlende Features (alle None), Gewitterrisiko (hohes CAPE + Blitzdichte).
- ZUSAMMENHÄNGE: z.B. API-Fehler + fehlerhafter Code für diesen Dienst.

Antworte AUSSCHLIESSLICH mit einem validen JSON-Objekt —
kein Text davor oder danach, keine Markdown-Backticks.

JSON-Schema (strikt einhalten):
{
  "analysis_date": "ISO-Datum",
  "overall_status": "ok|warning|critical",
  "summary": "Max. 2 Sätze Gesamtbewertung (Code, Metriken, Wetterlage).",
  "weather_situation": {
    "active_cells": <int — Anzahl Zellen im letzten Frame>,
    "max_intensity": "<intensity_label der stärksten Zelle oder null>",
    "severe_risk": true|false,
    "note": "Max. 1 Satz zur aktuellen Wetterlage."
  },
  "suggestions": [
    {
      "priority": "high|medium|low",
      "category": "accuracy|api|model|data|system|config|code|weather",
      "title": "Kurztitel (max. 60 Zeichen)",
      "description": "Problembeschreibung mit Dateiname/Funktion (max. 200 Zeichen)",
      "action": "Konkrete Massnahme inkl. Code-Snippet falls sinnvoll (max. 300 Zeichen)"
    }
  ]
}

Maximal 8 Vorschläge, sortiert nach Priorität.
Nur echte Probleme melden. suggestions = [] wenn alles in Ordnung.
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
            model=cfg.get("model", "claude-sonnet-4-6"),
            max_tokens=cfg.get("max_tokens", 1500),
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (f"System-Report ({since_hours}h):\n{report_json}"),
                }
            ],
        )
        try:
            from debug_utils import log_api_call
            log_api_call("anthropic_api", url="https://api.anthropic.com/v1/messages",
                         status_code=200)
        except Exception:
            pass
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
