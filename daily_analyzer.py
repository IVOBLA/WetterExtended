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
# Token-Vorfilterung: Symptom-Map + AST-Skelett
# ---------------------------------------------------------------------------

# Dateien die immer als Volltext geladen werden (Kern-Konfiguration + Hauptschleife)
_ALWAYS_CORE_FILES: frozenset = frozenset({"config.py", "main.py"})

# Mapping: Subsystem-Anomalie → zuständige Quelldateien (Volltext)
_SYMPTOM_FILE_MAP: dict = {
    "accuracy":   ["prediction.py", "accuracy_tracker.py", "object_tracking.py"],
    "api":        [
        "fetch_arome_openmeteo.py", "blitz_api.py",
        "cloud_height_from_eumetview.py", "assign_cape_from_forecast.py",
    ],
    "model":      ["model_training.py", "dataset_builder.py", "radar_convlstm.py"],
    "data":       ["dataset_builder.py", "object_tracking.py"],
    "scheduler":  ["scheduler.py"],
    "analyzer":   ["daily_analyzer.py"],
    "storm":      ["object_tracking.py", "prediction.py"],
}


def _get_symptom_files(report: dict) -> set:
    """
    Leitet aus dem bereits gesammelten Report ab, welche Subsysteme auffällig
    sind, und gibt die zugehörigen Quelldateien zurück (Volltext-Kandidaten).

    Geprüfte Signale:
      accuracy        : hit_rate < 0.4 oder samples == 0
      api             : success_rate < 90 % oder api_health failures > 0
      model           : model_quality.status nicht ok/good/success
      data            : samples_total < 50
      scheduler/storm : journal_errors + storm_day aktive Frames
    """
    flagged: set = set()

    # Accuracy-Check
    for h_data in report.get("accuracy", {}).values():
        samples  = h_data.get("samples")  or 0
        hit_rate = h_data.get("hit_rate") or 0.0
        if samples == 0 or hit_rate < 0.4:
            flagged |= set(_SYMPTOM_FILE_MAP["accuracy"])
            break

    # API-Erfolgsrate
    for svc_data in report.get("api_success_evidence", {}).values():
        if svc_data.get("success_rate", 100.0) < 90.0:
            flagged |= set(_SYMPTOM_FILE_MAP["api"])
            break
    if report.get("api_health", {}).get("total_failures", 0) > 0:
        flagged |= set(_SYMPTOM_FILE_MAP["api"])

    # Modell-Status
    model_status = report.get("model_quality", {}).get("status")
    if not model_status or model_status.lower() not in ("ok", "good", "success"):
        flagged |= set(_SYMPTOM_FILE_MAP["model"])

    # Datensatz-Größe
    samples_total = report.get("data_quality", {}).get("samples_total")
    if samples_total is not None and samples_total < 50:
        flagged |= set(_SYMPTOM_FILE_MAP["data"])

    # Journal-Fehler: Scheduler oder Analyzer betroffen
    for err in report.get("journal_errors", []):
        sig = err.get("signature", "").upper()
        if "SCHEDULER" in sig:
            flagged |= set(_SYMPTOM_FILE_MAP["scheduler"])
        if "ANALYZER" in sig:
            flagged |= set(_SYMPTOM_FILE_MAP["analyzer"])

    # Aktive Sturmzellen → Tracking + Forecast-Code relevant
    sd = report.get("storm_day_summary", {}).get("storm_day", {})
    if sd.get("frames_with_cells", 0) > 0:
        flagged |= set(_SYMPTOM_FILE_MAP["storm"])

    return flagged


def _extract_ast_skeleton(source: str) -> str:
    """
    Extrahiert Modul-Docstring, Imports und Klassen-/Funktionssignaturen
    mit Docstrings aus Python-Quellcode (ast-Modul).

    Gibt ein kompaktes Skelett zurück — ca. 80–90 % weniger Token als Volltext,
    aber vollständige Strukturübersicht für die KI.

    Fallback: erste 40 Zeilen bei Syntaxfehlern oder leerem Ergebnis.
    """
    import ast as _ast

    try:
        tree = _ast.parse(source)
    except SyntaxError:
        return "\n".join(source.splitlines()[:40]) + "\n# [AST-PARSE-FEHLER — Skelett gekürzt]"

    lines = source.splitlines()
    out: list = [f"# AST-SKELETT ({len(lines)} Originalzeilen)"]

    # Modul-Docstring
    mod_doc = _ast.get_docstring(tree)
    if mod_doc:
        out.append(f'"""(Modul) {mod_doc[:200].replace(chr(10), " ")}"""')

    # Imports (max. 20 Zeilen)
    import_lines: list = []
    for node in tree.body:
        if isinstance(node, (_ast.Import, _ast.ImportFrom)):
            import_lines.append(lines[node.lineno - 1].strip())
    if import_lines:
        out.append("")
        out.extend(import_lines[:20])
        if len(import_lines) > 20:
            out.append(f"# ... ({len(import_lines) - 20} weitere Imports)")

    # Top-Level Funktionen und Klassen
    for node in tree.body:
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            doc = _ast.get_docstring(node)
            out.append(f"\ndef {node.name}(...):  # Zeile {node.lineno}")
            if doc:
                out.append(f'    """{doc[:150].replace(chr(10), " ")}"""')
        elif isinstance(node, _ast.ClassDef):
            out.append(f"\nclass {node.name}:  # Zeile {node.lineno}")
            doc = _ast.get_docstring(node)
            if doc:
                out.append(f'  """{doc[:150].replace(chr(10), " ")}"""')
            for sub in node.body:
                if isinstance(sub, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    mdoc = _ast.get_docstring(sub)
                    out.append(f"    def {sub.name}(...):  # Zeile {sub.lineno}")
                    if mdoc:
                        out.append(f'        """{mdoc[:100].replace(chr(10), " ")}"""')

    if len(out) <= 2:
        return source[:1500] + "\n# [SKELETT-LEER — Volltext gekürzt]"
    return "\n".join(out)


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
            if max_lines > 0 and len(lines) > max_lines:
                content = "".join(lines[:max_lines])
                content += f"\n... ({len(lines) - max_lines} weitere Zeilen gekürzt)\n"
            else:
                content = raw  # max_lines=0 → vollständiger Source (full_source_mode)
            return content, "ok"
    except urllib.error.HTTPError as exc:
        codes = {404: "not_found", 401: "auth_error", 403: "rate_limit"}
        return f"[GitHub HTTP {exc.code}: {filepath}]", codes.get(exc.code, "network_error")
    except Exception as exc:
        return f"[GitHub Fehler: {exc}]", "network_error"


def _collect_source_context(report: "dict | None" = None) -> dict:
    """
    Holt Quellcode aller konfigurierten Dateien ausschliesslich von GitHub.
    Kein Zugriff auf lokale Dateien. GitHub-Stand ist die einzige Quelle.

    Symptom-gesteuerter Modus (wenn `report` übergeben wird — automatische Analyse):
      - Immer Volltext: _ALWAYS_CORE_FILES (config.py, main.py)
      - Volltext: Dateien aus _get_symptom_files(report) (auffällige Subsysteme)
      - Alle anderen: kompaktes AST-Skelett (~80-90 % Token-Einsparung)
      Ergebnis: Relevante Dateien vollständig, Rest als Strukturübersicht.

    Unkontrollierter Modus (report=None — interaktiver Chat in app.py):
      Verhält sich identisch zum bisherigen Verhalten (max_lines / full_source_mode).
    """
    from config import GITHUB_VERIFY_CONFIG
    gh = runtime_config.get("GITHUB_VERIFY_CONFIG", GITHUB_VERIFY_CONFIG)

    repo      = gh.get("repo",   "IVOBLA/WetterExtended")
    branch    = gh.get("branch", "main")
    token     = gh.get("token",  "")
    files     = gh.get("files",  [])
    full_mode = gh.get("full_source_mode", False)
    max_lines = 0 if full_mode else gh.get("max_lines_per_file", 120)

    # Symptom-Gate: nur bei automatischer Analyse (report übergeben)
    full_files: set = set(_ALWAYS_CORE_FILES)
    if report is not None and not full_mode:
        full_files |= _get_symptom_files(report)

    ctx = {
        "source":         "github",
        "repo":           repo,
        "branch":         branch,
        "files":          {},
        "errors":         [],
        "skeleton_files": [],   # Dateien die als AST-Skelett gesendet wurden
        "full_files":     [],   # Dateien die als Volltext gesendet wurden
    }

    ok_count  = 0
    err_count = 0
    for fname in files:
        # Skelett-Modus: symptom-gesteuerte Analyse + Datei nicht im full_files-Set
        use_skeleton = (
            report is not None
            and not full_mode
            and fname not in full_files
        )
        # Volltext laden (0 = unbegrenzt), dann ggf. auf Skelett reduzieren
        content, status = _fetch_github_file(repo, branch, fname, token,
                                             max_lines=0 if use_skeleton else max_lines)
        if status == "ok" and use_skeleton:
            content = _extract_ast_skeleton(content)
            ctx["skeleton_files"].append(fname)
            ctx["files"][fname] = {"content": content, "status": "ok", "mode": "skeleton"}
        else:
            ctx["files"][fname] = {
                "content": content,
                "status":  status,
                "mode":    "full" if status == "ok" else "error",
            }
            if status == "ok":
                ctx["full_files"].append(fname)

        if status == "ok":
            ok_count += 1
        else:
            err_count += 1
            ctx["errors"].append({"file": fname, "reason": status})

    debug_log(
        f"[ANALYZER] GitHub-Source: {ok_count} geladen, {err_count} Fehler "
        f"(volltext={len(ctx['full_files'])}, skelett={len(ctx['skeleton_files'])})"
    )
    return ctx


# ---------------------------------------------------------------------------
# Tages-Sturmzellen und Fehlerkontext für KI-Analyse
# ---------------------------------------------------------------------------

def _load_storm_day_summary(since_hours: int, max_peak_frames: int = 3) -> dict:
    """
    Baut einen vollständigen Tages-Sturmzellen-Report für den KI-Analyse-Aufruf.

    Ersetzt _load_recent_objects() — statt der "letzten 5 Frames" werden die
    aktivsten Frames des gesamten Analyse-Fensters (since_hours) herangezogen.

    Datenquellen:
      - cells_log.jsonl       : Sturm-Tagesübersicht (alle Frames, Zellcount)
      - locations_*.json      : Orts-Treffer-Aggregat pro Frame
      - SAVE_PATHS["objects"] : Vollständige Zelldaten der Peak-Frames

    Rückgabe-Dict:
      storm_day       : Aktivitäts-Aggregat (Frames, Peak, Zeitfenster, Lineages)
      location_hits   : Orts-Treffer-Aggregat (Häufigkeit pro Ort)
      peak_frames     : Top-N Frames mit vollständigen Zelldaten
    """
    eval_dir    = SAVE_PATHS.get("evaluation", "train_data/evaluation")
    objects_dir = SAVE_PATHS.get("objects",    "data/objects")
    cutoff      = datetime.utcnow() - timedelta(hours=since_hours)

    # Timestamp-Parser für Format "YYYY-MM-DD_HH-MM-SS"
    def _ts(ts_str: str) -> "datetime | None":
        try:
            return datetime.strptime(ts_str, "%Y-%m-%d_%H-%M-%S")
        except (ValueError, TypeError):
            return None

    # ── 1. cells_log.jsonl lesen ──────────────────────────────────────────────
    cells_log_path = os.path.join(eval_dir, "cells_log.jsonl")
    log_entries: list = []
    if os.path.exists(cells_log_path):
        try:
            with open(cells_log_path, "r", encoding="utf-8") as _f:
                for line in _f:
                    try:
                        rec = json.loads(line.strip())
                        t = _ts(rec.get("ts", ""))
                        if t is not None and t >= cutoff:
                            log_entries.append(rec)
                    except Exception:
                        continue
        except Exception as exc:
            debug_log(f"[ANALYZER] cells_log Lesefehler: {exc}")

    # ── 2. Tages-Aggregat ─────────────────────────────────────────────────────
    active = [e for e in log_entries if e.get("count", 0) > 0]
    peak_e = max(active, key=lambda e: e.get("count", 0), default=None)

    # Distinct Lineages über alle aktiven Frames
    all_lineages: set = set()
    for e in active:
        for c in e.get("cells", []):
            if "lineage" in c:
                all_lineages.add(c["lineage"])

    # Sturm-Zeitfenster: zusammenhängende Segmente mit count > 0 (Lücke > 30 min = neues Fenster)
    storm_windows: list = []
    if active:
        sorted_active = sorted(active, key=lambda e: e.get("ts", ""))
        win_start = sorted_active[0]["ts"]
        win_max   = sorted_active[0].get("count", 0)
        prev_t    = _ts(sorted_active[0]["ts"])
        for entry in sorted_active[1:]:
            curr_t = _ts(entry.get("ts", ""))
            gap    = (curr_t - prev_t).total_seconds() if (curr_t and prev_t) else 0
            if gap > 1800:
                storm_windows.append({
                    "start":     win_start,
                    "end":       prev_t.strftime("%Y-%m-%d_%H-%M-%S") if prev_t else win_start,
                    "max_cells": win_max,
                })
                win_start = entry["ts"]
                win_max   = entry.get("count", 0)
            else:
                win_max = max(win_max, entry.get("count", 0))
            prev_t = curr_t
        storm_windows.append({
            "start":     win_start,
            "end":       sorted_active[-1]["ts"],
            "max_cells": win_max,
        })

    storm_day = {
        "frames_in_window":  len(log_entries),
        "frames_with_cells": len(active),
        "quiet_frames":      len(log_entries) - len(active),
        "peak_cell_count":   peak_e.get("count", 0) if peak_e else 0,
        "peak_timestamp":    peak_e.get("ts")        if peak_e else None,
        "distinct_lineages": len(all_lineages),
        "storm_windows":     storm_windows[:5],       # max. 5 Fenster
        "window_hours":      since_hours,
    }

    # ── 3. Orts-Treffer-Aggregat aus locations_*.json ─────────────────────────
    hit_counts: dict = {}
    total_hit_frames = 0
    if os.path.isdir(eval_dir):
        loc_files = sorted(
            f for f in os.listdir(eval_dir)
            if f.startswith("locations_") and f.endswith(".json")
        )
        for fname in loc_files:
            bare = fname[len("locations_"):].replace(".json", "")
            t = _ts(bare)
            if t is None or t < cutoff:
                continue
            fpath = os.path.join(eval_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as _f:
                    hits = json.load(_f)
                if isinstance(hits, list) and hits:
                    total_hit_frames += 1
                    for loc in hits:
                        name = loc.get("name", "?")
                        hit_counts[name] = hit_counts.get(name, 0) + 1
            except Exception:
                continue

    location_hits_agg = {
        "locations_affected":   sorted(hit_counts.keys()),
        "hit_frame_counts":     hit_counts,
        "total_hit_frames":     total_hit_frames,
        "note": (
            "Anzahl Frames in denen der Ort getroffen wurde. "
            "Kein direktes Äquivalent zu gesendeten Warnungen "
            "(Cooldown und 2-Frame-Bestätigung nicht berücksichtigt)."
        ),
    }

    # ── 4. Peak-Frames: vollständige Zelldaten ────────────────────────────────
    _CELL_KEYS = (
        "id", "lat", "lon", "size", "core_ratio",
        "vx", "vy", "missing", "lineage",
        "cape", "cloud_top_height_m", "lightning_count_10km",
        "of_magnitude", "of_angle",
        "arome_precip_mm", "arome_cape",
        "hail_prob", "hail_warning",
        "gust_warning", "heavy_rain_warning",
        "intensity", "intensity_label",
        "severity_score", "severity_level",
        "wind_shear_speed",
    )

    # Top-N aktivste Frames + immer den neuesten Frame (zeigt aktuellen Zustand)
    peak_ts = [
        e["ts"] for e in sorted(active, key=lambda e: e.get("count", 0), reverse=True)[:max_peak_frames]
    ]
    if log_entries:
        newest = sorted(log_entries, key=lambda e: e.get("ts", ""), reverse=True)[0]["ts"]
        if newest not in peak_ts:
            peak_ts.append(newest)

    peak_frames: list = []
    for ts_str in sorted(peak_ts):
        fpath = os.path.join(objects_dir, f"{ts_str}.json")
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as _f:
                raw_cells = json.load(_f)
        except Exception as exc:
            debug_log(f"[ANALYZER] Peak-Frame Lesefehler {fpath}: {exc}")
            continue
        slim_cells = []
        for cell in (raw_cells or []):
            slim = {k: cell[k] for k in _CELL_KEYS if k in cell}
            for h in (10, 20, 30):
                for ax in ("lat", "lon"):
                    key = f"forecast_{ax}_{h}"
                    if key in cell:
                        slim[key] = cell[key]
            slim_cells.append(slim)
        peak_frames.append({
            "timestamp":  ts_str,
            "cell_count": len(slim_cells),
            "cells":      slim_cells,
        })

    debug_log(
        f"[ANALYZER] storm_day_summary: {storm_day['frames_with_cells']} aktive Frames, "
        f"peak={storm_day['peak_cell_count']} Zellen @ {storm_day['peak_timestamp']}, "
        f"{len(hit_counts)} Orte getroffen, {len(peak_frames)} Peak-Frames geladen"
    )

    return {
        "description": (
            f"Vollständiger Tages-Report letzter {since_hours}h. "
            "storm_day=Aktivitäts-Aggregat aus cells_log.jsonl; "
            "location_hits=Orts-Treffer-Aggregat aus locations_*.json; "
            "peak_frames=Top-Frames nach Zellanzahl (vollständige Zelldaten)."
        ),
        "storm_day":        storm_day,
        "location_hits":    location_hits_agg,
        "peak_frames":      peak_frames,
        "peak_frame_count": len(peak_frames),
    }


# ---------------------------------------------------------------------------
# Fehler-Digest aus systemd-Journal
# ---------------------------------------------------------------------------

def _load_journal_error_digest(since_hours: int) -> list:
    """
    Liest systemd-Journal der wetterprojekt-Services auf Fehler/Tracebacks.

    Wertet beide Units aus: wetterprojekt und wetterprojekt-scheduler.
    Gibt eine deduplizierte, nach Häufigkeit sortierte Liste zurück:
      [{"signature": str, "count": int, "first_seen": str, "last_seen": str}]

    Gibt [] zurück wenn journalctl nicht verfügbar oder nicht lesbar ist.
    Fehler-Erkennung: Zeilen mit "Traceback", "Error:", "Exception:",
    "ERROR", "CRITICAL", "WARNING".
    """
    import subprocess
    import re as _re

    since_dt  = datetime.utcnow() - timedelta(hours=since_hours)
    since_str = since_dt.strftime("%Y-%m-%d %H:%M:%S")

    raw_lines: list = []
    for unit in ("wetterprojekt", "wetterprojekt-scheduler"):
        try:
            proc = subprocess.run(
                ["journalctl", "-u", unit, "--since", since_str,
                 "--no-pager", "-o", "short-iso"],
                capture_output=True, text=True, timeout=15,
            )
            if proc.returncode in (0, 1):
                raw_lines.extend(proc.stdout.splitlines())
            else:
                debug_log(f"[ANALYZER] journalctl {unit} rc={proc.returncode}")
        except FileNotFoundError:
            debug_log("[ANALYZER] journalctl nicht gefunden — Journal-Digest übersprungen.")
            return []
        except Exception as exc:
            debug_log(f"[ANALYZER] journalctl Fehler ({unit}): {exc}")

    _MARKERS = ("Traceback", "Error:", "Exception:", "ERROR", "CRITICAL", "WARNING")
    _NUM_RE  = _re.compile(r"\b\d{4,}\b")

    # Deduplizierung nach normalisierter Signatur
    sig_map: dict = {}
    for line in raw_lines:
        # Format: 2025-06-15T14:30:00+0000 hostname unit[PID]: MESSAGE
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        ts_raw = parts[0]
        msg    = parts[3]
        if not any(m in msg for m in _MARKERS):
            continue
        # Volatile Zahlen ersetzen, auf 120 Zeichen kürzen
        sig = _NUM_RE.sub("N", msg[:120]).strip()
        if sig not in sig_map:
            sig_map[sig] = {"count": 0, "first_seen": "", "last_seen": ""}
        sig_map[sig]["count"] += 1
        if not sig_map[sig]["first_seen"]:
            sig_map[sig]["first_seen"] = ts_raw
        sig_map[sig]["last_seen"] = ts_raw

    result = sorted(
        [{"signature": sig, **data} for sig, data in sig_map.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]

    debug_log(f"[ANALYZER] Journal-Digest: {len(result)} Fehlermuster in {len(raw_lines)} Journal-Zeilen")
    return result


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


# Keys die NIEMALS in den KI-Report wandern dürfen (Secrets)
_SECRET_KEY_PARTS = frozenset({
    "TOKEN", "KEY", "PASS", "PASSWORD", "SECRET",
    "AUTH", "CREDENTIAL", "PRIVATE", "API_KEY",
})


def _sanitize_config(obj, depth=0):
    """
    Entfernt rekursiv alle Secret-Keys aus einem Config-Dict.
    depth-Limit verhindert endlose Rekursion bei zirkulären Strukturen.
    """
    if depth > 5:
        return obj
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            key_upper = str(k).upper()
            if any(s in key_upper for s in _SECRET_KEY_PARTS):
                out[k] = "***REDACTED***"
            else:
                out[k] = _sanitize_config(v, depth + 1)
        return out
    if isinstance(obj, list):
        return [_sanitize_config(i, depth + 1) for i in obj]
    return obj


def build_system_report(since_hours: int = 24) -> dict:
    """
    Baut einen komprimierten System-Report für den KI-Analyse-Aufruf.
    Enthält: Metriken, API-Health, Modellqualität, Systemstatus,
             vollständige bereinigte Konfiguration (ohne Secrets).
    """
    report = {
        "generated_utc":    datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "since_hours":      since_hours,
        "accuracy":         {},
        "api_health":       {},
        "model_quality":    {},
        "data_quality":     {},
        "system":           {},
        "system_config":    {},   # bereinigte Konfiguration (Secrets entfernt)
        "storm_day_summary": {},  # vollständige Tagesdaten (cells_log + locations + peak_frames)
        "journal_errors":   [],   # Fehler-Digest aus systemd-Journal
        "source_context":   {},
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

    # --- API-Erfolgs-Nachweis (verhindert False Findings durch fehlenden Kontext) ---
    try:
        from debug_utils import api_call_summary
        calls = api_call_summary(since_hours=since_hours)
        report["api_success_evidence"] = {
            svc: {"calls": info.get("calls", 0), "errors": info.get("errors", 0),
                  "success_rate": round(
                      (info.get("calls", 0) - info.get("errors", 0)) /
                      max(info.get("calls", 0), 1) * 100, 1
                  )}
            for svc, info in calls.get("by_service", {}).items()
            if info.get("calls", 0) > 0
        }
    except Exception as exc:
        debug_log(f"[ANALYZER] api_success_evidence Fehler: {exc}")

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

    # --- Tages-Sturmzellen-Summary (cells_log + locations + Peak-Frames) ---
    try:
        report["storm_day_summary"] = _load_storm_day_summary(since_hours=since_hours)
    except Exception as exc:
        debug_log(f"[ANALYZER] storm_day_summary Fehler: {exc}")
        report["storm_day_summary"] = {
            "storm_day": {}, "location_hits": {}, "peak_frames": [], "peak_frame_count": 0,
        }

    # --- Tages-Sturmzellen-Summary und Journal-Fehler VOR source_context sammeln
    # (Symptom-Gate in _collect_source_context braucht diese Daten als Eingabe)

    # --- Journal-Fehler-Digest (systemd: wetterprojekt + wetterprojekt-scheduler) ---
    try:
        report["journal_errors"] = _load_journal_error_digest(since_hours=since_hours)
    except Exception as exc:
        debug_log(f"[ANALYZER] Journal-Digest Fehler: {exc}")
        report["journal_errors"] = []

    # --- Quellcode von GitHub (symptom-gesteuert — nach allen Metriken) ---
    try:
        report["source_context"] = _collect_source_context(report)
    except Exception as exc:
        debug_log(f"[ANALYZER] Source-Kontext Fehler: {exc}")
        report["source_context"] = {"source": "error", "error": str(exc)}

    # --- System-Konfiguration (alle effektiven Werte, Secrets entfernt) ---
    try:
        effective_raw = runtime_config.all_effective()
        report["system_config"] = _sanitize_config(effective_raw)

        # Explizit wichtige Sub-Bereiche direkt lesbar machen (falls nicht in all_effective)
        # ML_FORECAST_HORIZONS_MIN ist bereits am Modul-Anfang importiert.
        # Wenn es hier nochmals lokal importiert würde, markiert Python die
        # Variable für die GESAMTE Funktion als lokal — der frühere Zugriff
        # im accuracy-Block würde UnboundLocalError werfen.
        from config import (
            HSV_BAND_LABELS, LOCATIONS_WATCHLIST,
            HAIL_WARN_THRESHOLD, GUST_WARN_KMH, HEAVY_RAIN_WARN_MM_PER_H,
            VERIFICATION_TOLERANCE_KM, DATA_RETENTION_DAYS,
            TAWES_GUST_STATION_IDS, BBOX_KAERNTEN_EXTENDED,
            LOOP_INTERVAL_CELLS_S, LOOP_INTERVAL_NO_CELLS_S,
        )
        # Nur wenn all_effective() diese nicht bereits enthält
        _supplement = {
            "HSV_BAND_LABELS":             runtime_config.get("HSV_BAND_LABELS", HSV_BAND_LABELS),
            "LOCATIONS_WATCHLIST":         runtime_config.get("LOCATIONS_WATCHLIST", LOCATIONS_WATCHLIST),
            "ML_FORECAST_HORIZONS_MIN":    runtime_config.get("ML_FORECAST_HORIZONS_MIN", ML_FORECAST_HORIZONS_MIN),
            "HAIL_WARN_THRESHOLD":         runtime_config.get("HAIL_WARN_THRESHOLD", HAIL_WARN_THRESHOLD),
            "GUST_WARN_KMH":               runtime_config.get("GUST_WARN_KMH", GUST_WARN_KMH),
            "HEAVY_RAIN_WARN_MM_PER_H":    runtime_config.get("HEAVY_RAIN_WARN_MM_PER_H", HEAVY_RAIN_WARN_MM_PER_H),
            "VERIFICATION_TOLERANCE_KM":   VERIFICATION_TOLERANCE_KM,
            "DATA_RETENTION_DAYS":         runtime_config.get("DATA_RETENTION_DAYS", DATA_RETENTION_DAYS),
            "TAWES_GUST_STATION_IDS":      runtime_config.get("TAWES_GUST_STATION_IDS", TAWES_GUST_STATION_IDS),
            "BBOX_KAERNTEN_EXTENDED":      BBOX_KAERNTEN_EXTENDED,
            "LOOP_INTERVAL_CELLS_S":       runtime_config.get("LOOP_INTERVAL_CELLS_S", LOOP_INTERVAL_CELLS_S),
            "LOOP_INTERVAL_NO_CELLS_S":    runtime_config.get("LOOP_INTERVAL_NO_CELLS_S", LOOP_INTERVAL_NO_CELLS_S),
        }
        for k, v in _supplement.items():
            if k not in report["system_config"]:
                report["system_config"][k] = v

        # runtime_overrides.json Rohinhalt (bereits bereinigt durch _sanitize_config)
        try:
            import json as _jcfg
            from config import RUNTIME_OVERRIDES_PATH
            _ov_path = runtime_config.get("RUNTIME_OVERRIDES_PATH", RUNTIME_OVERRIDES_PATH)
            if os.path.exists(_ov_path):
                with open(_ov_path, "r", encoding="utf-8") as _ov_f:
                    _ov_raw = _jcfg.load(_ov_f)
                report["system_config"]["_runtime_overrides_active"] = _sanitize_config(_ov_raw)
            else:
                report["system_config"]["_runtime_overrides_active"] = {}
        except Exception as _ov_exc:
            debug_log(f"[ANALYZER] runtime_overrides lesen fehlgeschlagen: {_ov_exc}")

    except Exception as exc:
        debug_log(f"[ANALYZER] system_config Fehler: {exc}")

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

2) storm_day_summary — vollständige Tagesdaten des Analysefensters:
   storm_day (Frames, aktive Frames, Peak-Zellzahl/-Zeit, Sturm-Zeitfenster,
   distinct Lineages), location_hits (aggregierte Orts-Treffer) und
   peak_frames (Top-Frames mit vollständigen Zelldaten: id, lat/lon, size,
   core_ratio, vx/vy, CAPE, Blitzcount, Hagel-/Böen-/Starkregenwarnung,
   severity_score/-level, intensity_label, forecast_lat/lon_10/20/30).

3) journal_errors — deduplizierte Fehler/Tracebacks aus dem systemd-Journal
   der Units wetterprojekt und wetterprojekt-scheduler.

4) Metriken: accuracy (MAE/hit-rate je Horizont), api_health, model_quality,
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
    "active_cells": <int — Zellen im neuesten Peak-/Status-Frame>,
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

    # Lokale Konfiguration explizit als ersten lesbaren Block voranstellen.
    # build_system_report() enthält system_config zwar, aber im kompakten JSON
    # vergraben. Durch den Prefix sieht die KI Schwellwerte, Horizonte, Orte
    # und runtime_overrides als ERSTEN Kontext — prominent und gut lesbar.
    try:
        _cfg_block = _sanitize_config(runtime_config.all_effective())
        _cfg_prefix = (
            "=== LOKALE KONFIGURATION (runtime_overrides + config.py) ===\n"
            + json.dumps(_cfg_block, ensure_ascii=False, indent=1)
            + "\n\n"
        )
    except Exception as _cfg_exc:
        debug_log(f"[ANALYZER] Konfiguration konnte nicht serialisiert werden: {_cfg_exc}")
        _cfg_prefix = ""

    _user_content = (
        _cfg_prefix
        + f"=== SYSTEM-REPORT (letzte {since_hours}h) ===\n"
        + report_json
    )

    debug_log(
        f"[ANALYZER] Report erstellt ({len(report_json)} Zeichen"
        f" + {len(_cfg_prefix)} Zeichen Konfiguration), sende an Anthropic API..."
    )

    import re as _re

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        max_tok = int(cfg.get("max_tokens", 3000))
        message = client.messages.create(
            model=str(cfg.get("model", "claude-sonnet-4-6")),
            max_tokens=max_tok,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": _user_content,
                }
            ],
        )
        raw = message.content[0].text if message.content else ""
        try:
            from debug_utils import log_api_call
            log_api_call("anthropic_api", url="https://api.anthropic.com/v1/messages",
                         status_code=200, method="POST",
                         response_text=raw, content_type="application/json")
        except Exception:
            pass
        stop_reason = getattr(message, "stop_reason", None)
        debug_log(f"[ANALYZER] Antwort empfangen ({len(raw)} Zeichen, stop_reason={stop_reason})")

        if stop_reason == "max_tokens":
            debug_log(
                f"[ANALYZER][WARN] Antwort durch max_tokens={max_tok} abgeschnitten! "
                f"max_tokens in AI_ANALYSIS_CONFIG erhoehen."
            )
            log_api_failure(
                "Anthropic-API",
                "https://api.anthropic.com/v1/messages",
                f"stop_reason=max_tokens — Antwort abgeschnitten (max_tokens={max_tok})",
                fallback_used=False,
            )
            return None

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
        fence_match = _re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", clean, _re.DOTALL)
        if fence_match:
            clean = fence_match.group(1).strip()
        result = json.loads(clean)
    except Exception as exc:
        log_api_failure(
            "Anthropic-API",
            "https://api.anthropic.com/v1/messages",
            f"JSON-Parse-Fehler: {exc}",
            fallback_used=False,
        )
        debug_log(f"[ANALYZER] Roh-Antwort (erste 800 Zeichen): {raw[:800]}")
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

    # E-Mail-Report senden (wenn report_email konfiguriert)
    _report_email = cfg.get("report_email", "").strip()
    if _report_email and result:
        try:
            from email_notifier import send_ai_report_email

            ok = send_ai_report_email(result, _report_email)
            debug_log(f"[ANALYZER] E-Mail-Report {'gesendet' if ok else 'fehlgeschlagen'}: {_report_email}")
        except Exception as _exc:
            debug_log(f"[ANALYZER] E-Mail-Versand Fehler: {_exc}")

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
