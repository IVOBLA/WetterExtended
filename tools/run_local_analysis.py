#!/usr/bin/env python3
"""P77 — unbeaufsichtigte, nur lesende lokale Analyse mit Claude Code."""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Vienna")
MAX_ATTEMPTS_PER_DAY = 3
# B465 (Codex-Review zu P77): Positivliste statt Verbots-Substrings.
# Platzhalterregeln wie "Bash(journalctl *)" sind nicht read-only —
# `journalctl --vacuum-size=1M` loescht Journaldateien, und die sqlite3-Shell
# kennt Punktbefehle (.shell/.output/.import). Prefix-Matching kann das nicht
# abfangen. Deshalb: genau EINE Bash-Regel, das validierende Abfragewerkzeug.
ALLOWED_PLAIN_TOOLS = frozenset({"Read", "Grep", "Glob"})
ALLOWED_BASH_RULES = frozenset({"Bash(python3 tools/ro_query.py *)"})

REQUIRED_LIST_FIELDS = ("fehler", "loesungen", "verbesserungen", "prompts")
OPTIONAL_DICT_FIELDS = ("tuning_proposals",)  # P99: von tuning_apply.py verarbeitet
SECRET_ENV_TOKENS = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "APIKEY", "API_KEY", "PRIVATE_KEY", "CREDENTIAL", "ANTHROPIC_API")
ENV_PASSTHROUGH = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TZ", "TERM", "SHELL", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "DISABLE_AUTOUPDATER")


class PreconditionError(RuntimeError):
    """Vorbedingung für den Lauf ist nicht erfüllt."""


def _prepare_import_path(repo_dir: Path) -> None:
    if str(repo_dir) not in sys.path:
        sys.path.insert(0, str(repo_dir))


def load_config(repo_dir: Path) -> dict:
    _prepare_import_path(repo_dir)
    from config import LOCAL_ANALYSIS_CONFIG as default
    cfg = dict(default)
    try:
        import runtime_config
        runtime_config.reload_overrides()
        cfg.update(runtime_config.get("LOCAL_ANALYSIS_CONFIG", {}) or {})
    except Exception as exc:
        print(f"[LOCAL-ANALYSIS] runtime_overrides nicht lesbar: {exc}", file=sys.stderr)
    return cfg


def load_mode(repo_dir: Path) -> tuple:
    _prepare_import_path(repo_dir)
    from config import ANALYSIS_MODE as mode
    from config import ANALYSIS_MODE_CHANGED as changed
    try:
        import runtime_config
        runtime_config.reload_overrides()
        mode = runtime_config.get("ANALYSIS_MODE", mode)
        changed = runtime_config.get("ANALYSIS_MODE_CHANGED", changed)
    except Exception as exc:
        print(f"[LOCAL-ANALYSIS] runtime_overrides nicht lesbar: {exc}", file=sys.stderr)
    return str(mode or "repo").strip().lower(), str(changed or "").strip()


def is_due(mode, mode_changed, cfg, status, now_local, max_attempts=MAX_ATTEMPTS_PER_DAY):
    today = now_local.strftime("%Y-%m-%d")
    if str(mode).strip().lower() != "local": return False, "mode_repo"
    if str(mode_changed).strip() == today: return False, "mode_changed_today"
    due_at = now_local.replace(hour=int(cfg.get("cron_hour", 0)), minute=int(cfg.get("cron_minute", 10)), second=0, microsecond=0)
    if now_local < due_at: return False, "not_due_yet"
    st = status or {}
    if st.get("last_success_date") == today: return False, "already_ran_today"
    if st.get("last_attempt_date") == today and int(st.get("attempts_today", 0)) >= max_attempts: return False, "max_attempts_reached"
    return True, "due"


def split_allowed_tools(spec: str) -> list:
    """Zerlegt die Allowlist an Kommas, die nicht innerhalb von Klammern stehen."""
    out, buf, depth = [], [], 0
    for ch in str(spec or ""):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return [e for e in out if e]


def validate_allowed_tools(spec: str) -> None:
    """Laesst ausschliesslich Eintraege der Positivliste zu (B465).

    Jeder andere Eintrag wird abgelehnt — auch scheinbar harmlose. Shell-Zugriffe
    laufen ohne Ausnahme ueber tools/ro_query.py, das seine Parameter selbst
    validiert und externe Programme nie ueber die Shell aufruft.
    """
    entries = split_allowed_tools(spec)
    if not entries:
        raise PreconditionError("allowed_tools ist leer")
    erlaubt = sorted(ALLOWED_PLAIN_TOOLS | ALLOWED_BASH_RULES)
    for entry in entries:
        if entry in ALLOWED_PLAIN_TOOLS or entry in ALLOWED_BASH_RULES:
            continue
        raise PreconditionError(
            f"Werkzeug nicht auf der Positivliste: {entry!r}. "
            f"Erlaubt sind ausschliesslich: {', '.join(erlaubt)}. "
            "Shell-Zugriffe laufen ueber tools/ro_query.py."
        )
    if "Read" not in entries:
        raise PreconditionError("Read fehlt — die Analyse koennte keine Datei lesen")


def build_subprocess_env(base_env=None):
    src = dict(os.environ if base_env is None else base_env)
    env = {key: src[key] for key in ENV_PASSTHROUGH if key in src}
    env.setdefault("HOME", str(Path.home())); env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    env["DISABLE_AUTOUPDATER"] = "1"
    return {k: v for k, v in env.items() if not any(tok in k.upper() for tok in SECRET_ENV_TOKENS)}


def resolve_claude_bin(cfg):
    candidates = [str(cfg.get("claude_bin", "")).strip(), shutil.which("claude"), str(Path.home()/".local/bin/claude"), "/usr/local/bin/claude"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK): return candidate
    raise PreconditionError("Claude-Code-CLI nicht gefunden. Installation: curl -fsSL https://claude.ai/install.sh | bash -s stable — danach 'claude' einmal interaktiv starten und anmelden.")


def validate_deny_rules(settings_obj, settings_path) -> None:
    """Laesst nur qualifizierte Deny-Regeln der Form Tool(muster) zu (B468).

    Ein blosser Werkzeugname bricht den gesamten Lauf ab, sobald das Werkzeug in der
    installierten CLI-Version nicht existiert ("Permission deny rule \"MultiEdit\"
    matches no known tool"). Unter --permission-mode dontAsk sind nicht vorab erlaubte
    Werkzeuge ohnehin gesperrt — blosse Namen waeren also reine Bruchstelle ohne
    Schutzgewinn. Zusaetzlich muss das Werkzeug in der Positivliste stehen: eine Regel
    fuer ein nicht erlaubtes Werkzeug ist wirkungslos.
    """
    deny = ((settings_obj or {}).get("permissions") or {}).get("deny") or []
    if not isinstance(deny, list):
        raise PreconditionError(f"permissions.deny ist keine Liste: {settings_path}")
    erlaubte_werkzeuge = set(ALLOWED_PLAIN_TOOLS) | {
        r.split("(", 1)[0] for r in ALLOWED_BASH_RULES
    }
    for rule in deny:
        rule = str(rule)
        if "(" not in rule or not rule.endswith(")"):
            raise PreconditionError(
                f"Deny-Regel ohne Muster: {rule!r} in {settings_path}. "
                "Blosse Werkzeugnamen brechen den Lauf ab, wenn das Werkzeug in der "
                "CLI-Version nicht existiert. Form: Tool(muster)."
            )
        tool = rule.split("(", 1)[0]
        if tool not in erlaubte_werkzeuge:
            raise PreconditionError(
                f"Deny-Regel fuer nicht erlaubtes Werkzeug: {rule!r}. "
                f"Wirkungslos — erlaubt sind nur {', '.join(sorted(erlaubte_werkzeuge))}."
            )


def check_preconditions(cfg, repo_dir):
    validate_allowed_tools(cfg.get("allowed_tools", "")); claude_bin = resolve_claude_bin(cfg)
    prompt_file = repo_dir / str(cfg.get("prompt_path", ""))
    if not prompt_file.is_file(): raise PreconditionError(f"Prompt-Datei fehlt: {prompt_file}")
    prompt = prompt_file.read_text(encoding="utf-8").strip()
    if not prompt: raise PreconditionError(f"Prompt-Datei ist leer: {prompt_file}")
    settings = repo_dir / str(cfg.get("settings_path", ""))
    if not settings.is_file(): raise PreconditionError(f"Settings-Datei mit den Deny-Regeln fehlt: {settings}")
    try: parsed = json.loads(settings.read_text(encoding="utf-8"))
    except Exception as exc: raise PreconditionError(f"Settings-Datei ist kein gültiges JSON: {exc}") from exc
    validate_deny_rules(parsed, settings)
    return claude_bin, prompt, settings


def build_command(cfg, claude_bin, prompt_text, settings_file):
    cmd = [claude_bin, "-p", prompt_text, "--output-format", "json", "--permission-mode", "dontAsk", "--allowedTools", str(cfg.get("allowed_tools", "")), "--max-turns", str(int(cfg.get("max_turns", 40))), "--settings", str(settings_file)]
    if str(cfg.get("model", "")).strip(): cmd += ["--model", str(cfg["model"]).strip()]
    return cmd


def strip_code_fences(text):
    s = str(text or "").strip()
    if not s.startswith("```"): return s
    lines = s.splitlines()[1:]
    if lines and lines[-1].strip().startswith("```"): lines.pop()
    return "\n".join(lines).strip()


def validate_payload(obj):
    if not isinstance(obj, dict): raise ValueError("Antwort ist kein JSON-Objekt")
    summary = obj.get("zusammenfassung")
    if not isinstance(summary, str) or not summary.strip(): raise ValueError("Feld 'zusammenfassung' fehlt oder ist leer")
    clean = {"zusammenfassung": summary.strip()}
    for field in REQUIRED_LIST_FIELDS:
        val = obj.get(field, [])
        if val is None: val = []
        if not isinstance(val, list): raise ValueError(f"Feld {field!r} muss eine Liste sein")
        clean[field] = [str(x) for x in val]
    return clean


def extract_payload(stdout_text):
    try: outer = json.loads(stdout_text)
    except Exception as exc: raise ValueError(f"CLI-Antwort ist kein JSON: {exc}") from exc
    if isinstance(outer, list): outer = next((x for x in reversed(outer) if isinstance(x, dict) and "result" in x), None)
    if not isinstance(outer, dict): raise ValueError("Unerwartete Struktur der CLI-Antwort")
    if outer.get("is_error"): raise ValueError(f"Claude-Code meldet einen Fehler: {outer.get('result')!r}")
    if "result" not in outer: raise ValueError("Feld 'result' fehlt in der CLI-Antwort")
    return validate_payload(_json_from_result(outer["result"]))


def _json_from_result(result_text):
    """B473 — Das Modell liefert das Ergebnis-JSON gelegentlich mit erklaerendem Text
    davor/dahinter oder in einem nicht am Zeilenanfang stehenden ```json-Block. Statt die
    fertige Analyse zu verwerfen, holt diese Funktion das JSON-Objekt robust heraus."""
    s = strip_code_fences(result_text)
    try:
        return json.loads(s)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", str(result_text), re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    text = str(result_text or "")
    i, j = text.find("{"), text.rfind("}")
    if i != -1 and j > i:
        return json.loads(text[i:j + 1])
    raise ValueError("kein JSON-Objekt in der CLI-Antwort gefunden")


def read_json_quiet(path):
    try: return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception: return {}


def write_json_atomic(path, payload):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"); os.replace(str(tmp), str(path))


write_status = write_json_atomic


def make_status(state, now_local, previous=None, mode="", **fields):
    prev = previous or {}
    st = {"state": state, "mode": mode or prev.get("mode"), "ts_local": now_local.strftime("%Y-%m-%d %H:%M:%S"), "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "last_success_date": prev.get("last_success_date"), "last_attempt_date": prev.get("last_attempt_date"), "attempts_today": int(prev.get("attempts_today", 0) or 0), "duration_s": None, "rc": None, "num_fehler": None, "error": None, "claude_bin": prev.get("claude_bin"), "log_path": prev.get("log_path")}
    st.update(fields); return st


# B470: Ein fehlgeschlagener Lauf hinterliess keine verwertbare Spur — stdout wurde
# verworfen, stderr landete nur gekuerzt im Status, und war es leer, blieb das Feld
# leer. Im Admin-Panel stand dann "Fehlgeschlagen: rc=2:" ohne jede Angabe.
LOG_TAIL_CHARS = 4000
STATUS_ERROR_CHARS = 500


def describe_returncode(rc: int) -> str:
    """Negative Rueckgabewerte sind Signale — das erklaert stille Abbrueche."""
    if rc is None:
        return "unbekannt"
    if rc < 0:
        import signal as _sig
        try:
            name = _sig.Signals(-rc).name
        except (ValueError, AttributeError):
            name = "unbekannt"
        hinweis = " (vermutlich Speichermangel)" if -rc == 9 else ""
        return f"durch Signal {-rc} ({name}) beendet{hinweis}"
    return f"Rueckgabewert {rc}"


def summarize_failure(rc: int, stdout: str, stderr: str) -> str:
    """Liefert IMMER eine Meldung — auch wenn das Programm nichts ausgegeben hat."""
    err = (stderr or "").strip()
    out = (stdout or "").strip()
    kopf = describe_returncode(rc)
    if err:
        return f"{kopf}: {err[-STATUS_ERROR_CHARS:]}"
    if out:
        return f"{kopf}, nur stdout: {out[-STATUS_ERROR_CHARS:]}"
    return f"{kopf}, keine Ausgabe auf stdout oder stderr"


def detect_incomplete(stdout: str):
    """B471 — Ein Abbruch am Schritt-Limit ist keine Stoerung, sondern ein zu grosser
    Auftrag. Die CLI-JSON traegt dann terminal_reason=max_turns. Solche Faelle bekommen
    einen eigenen, handlungsleitenden Status statt der undurchsichtigen Fehlermeldung."""
    try:
        obj = json.loads(stdout or "")
    except Exception:
        return None
    if isinstance(obj, list):
        obj = next((x for x in reversed(obj) if isinstance(x, dict)), None)
    if not isinstance(obj, dict):
        return None
    reason = str(obj.get("terminal_reason") or "")
    errs = obj.get("errors") or []
    text = " ".join(str(e) for e in errs) if isinstance(errs, list) else str(errs)
    if reason == "max_turns" or "maximum number of turns" in text.lower():
        return ("Schritt-Limit erreicht — Auftrag zu umfangreich fuer max_turns. "
                "max_turns/timeout_s erhoehen oder Umfang von Abschnitt B (offene ACs) kuerzen.")
    return None


def cli_version(claude_bin: str) -> str:
    try:
        proc = subprocess.run(
            [claude_bin, "--version"], shell=False, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=30,
        )
        return (proc.stdout or proc.stderr or "").strip().splitlines()[0]
    except Exception as exc:
        return f"nicht ermittelbar ({exc})"


def write_run_log(path, *, cmd, claude_bin, mode, rc, duration_s,
                  stdout="", stderr="", note="") -> None:
    """Schreibt die vollstaendige Spur eines Laufs.

    Der Auftrag selbst wird ausgelassen (mehrere KB, unveraenderlich). Die Umgebung
    des Unterprozesses ist bereits geheimnisfrei, es kann also nichts Vertrauliches
    in dieser Datei landen.
    """
    gekuerzt = list(cmd or [])
    if len(gekuerzt) > 2:
        gekuerzt[2] = f"<Auftrag: {len(str(cmd[2]))} Zeichen>"
    zeilen = [
        f"Zeitpunkt   : {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')}",
        f"Betriebsart : {mode}",
        f"CLI         : {claude_bin}",
        f"CLI-Version : {cli_version(claude_bin) if claude_bin else '-'}",
        f"Ergebnis    : {describe_returncode(rc)}",
        f"Dauer       : {duration_s} s",
        f"Kommando    : {' '.join(shlex.quote(str(c)) for c in gekuerzt)}",
        "",
        f"--- stdout (letzte {LOG_TAIL_CHARS} Zeichen) ---",
        (stdout or "")[-LOG_TAIL_CHARS:] or "(leer)",
        "",
        f"--- stderr (letzte {LOG_TAIL_CHARS} Zeichen) ---",
        (stderr or "")[-LOG_TAIL_CHARS:] or "(leer)",
    ]
    if note:
        zeilen += ["", "--- Hinweis ---", note]
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    except Exception as exc:  # pragma: no cover - Logging darf nie der Grund sein
        print(f"[LOCAL-ANALYSIS] Laufprotokoll nicht schreibbar: {exc}", file=sys.stderr)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--repo-dir", default=str(Path(__file__).resolve().parents[1])); ap.add_argument("--force", action="store_true"); ap.add_argument("--check-only", action="store_true"); ap.add_argument("--dry-run", action="store_true"); return ap.parse_args(argv)


def run_deterministic_ai_checks(repo: Path):
    """Fuehrt den deterministischen AIChecks-Harness (P83+) aus und schreibt
    train_data/evaluation/ai_checks_results.json — budgetfrei, VOR der LLM-Analyse,
    damit der Prompt die Verdikte konsumieren kann. Ein Fehler hier darf die
    LLM-Analyse NIE blockieren (der LLM-Fallback deckt dann alle ACs ab)."""
    try:
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        from tools.ai_checks import run_all
        summary = run_all(repo, repo / "AIChecks.md")
        out = repo / "train_data/evaluation/ai_checks_results.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(out, summary)
        print(f"[LOCAL-ANALYSIS] Deterministische Checks: {summary['implemented']} impl, "
              f"{summary['not_implemented']} offen, {summary['findings']} Befunde, "
              f"{summary['errors']} Fehler -> {out.name}")
        return summary
    except Exception as exc:
        print(f"[LOCAL-ANALYSIS] Deterministische Checks uebersprungen ({exc}); "
              f"LLM-Fallback deckt alle ACs ab", file=sys.stderr)
        return None


def main(argv=None):
    args = parse_args(argv); repo = Path(args.repo_dir).resolve(); cfg = load_config(repo); mode, changed = load_mode(repo); now = datetime.now(TZ)
    status_path = repo / str(cfg.get("status_path", "train_data/evaluation/local_analysis_status.json")); prev = read_json_quiet(status_path)
    log_path = repo / str(cfg.get("log_path", "train_data/evaluation/local_analysis_last_run.log"))
    if not (args.force or args.check_only or args.dry_run):
        due, reason = is_due(mode, changed, cfg, prev, now)
        if not due:
            if reason in ("mode_repo", "mode_changed_today", "max_attempts_reached"): write_status(status_path, make_status(reason, now, prev, mode=mode))
            print(f"[LOCAL-ANALYSIS] kein Lauf: {reason} (Betriebsart: {mode})"); return 0
    try: claude, prompt, settings = check_preconditions(cfg, repo)
    except PreconditionError as exc:
        write_status(status_path, make_status("precondition_failed", now, prev, mode=mode, error=str(exc))); print(f"[LOCAL-ANALYSIS] Vorbedingung fehlt: {exc}", file=sys.stderr); return 1
    if args.check_only: print(f"[LOCAL-ANALYSIS] Vorbedingungen OK (claude={claude}, Betriebsart={mode})"); return 0
    cmd = build_command(cfg, claude, prompt, settings)
    if args.dry_run:
        shown = list(cmd); shown[2] = f"<Prompt: {len(prompt)} Zeichen>"; print("[LOCAL-ANALYSIS] " + " ".join(shlex.quote(c) for c in shown)); return 0
    run_deterministic_ai_checks(repo)
    today = now.strftime("%Y-%m-%d"); attempts = int(prev.get("attempts_today", 0) or 0)+1 if prev.get("last_attempt_date") == today else 1; base = {"last_attempt_date": today, "attempts_today": attempts, "claude_bin": claude}; t0=time.monotonic()
    try: proc = subprocess.run(cmd, cwd=str(repo), env=build_subprocess_env(), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=int(cfg.get("timeout_s", 900)))
    except subprocess.TimeoutExpired as exc:
        dur = round(time.monotonic()-t0, 1)
        meldung = f"Zeitlimit {cfg.get('timeout_s')}s überschritten"
        write_run_log(log_path, cmd=cmd, claude_bin=claude, mode=mode, rc=124,
                      duration_s=dur, stdout=(exc.stdout or ""), stderr=(exc.stderr or ""),
                      note=meldung)
        write_status(status_path, make_status("failed", now, prev, mode=mode, duration_s=dur, rc=124, error=meldung, log_path=str(log_path), **base))
        print(f"[LOCAL-ANALYSIS] {meldung}", file=sys.stderr); return 2
    dur=round(time.monotonic()-t0,1)
    if proc.returncode:
        unvollstaendig = detect_incomplete(proc.stdout)
        if unvollstaendig:
            write_run_log(log_path, cmd=cmd, claude_bin=claude, mode=mode, rc=proc.returncode,
                          duration_s=dur, stdout=proc.stdout, stderr=proc.stderr, note=unvollstaendig)
            write_status(status_path, make_status("incomplete", now, prev, mode=mode, duration_s=dur, rc=proc.returncode, error=unvollstaendig, log_path=str(log_path), **base))
            print(f"[LOCAL-ANALYSIS] {unvollstaendig}", file=sys.stderr)
            print(f"[LOCAL-ANALYSIS] Vollstaendige Spur: {log_path}", file=sys.stderr); return 2
        meldung = summarize_failure(proc.returncode, proc.stdout, proc.stderr)
        write_run_log(log_path, cmd=cmd, claude_bin=claude, mode=mode, rc=proc.returncode,
                      duration_s=dur, stdout=proc.stdout, stderr=proc.stderr)
        write_status(status_path, make_status("failed", now, prev, mode=mode, duration_s=dur, rc=proc.returncode, error=meldung, log_path=str(log_path), **base))
        print(f"[LOCAL-ANALYSIS] {meldung}", file=sys.stderr)
        print(f"[LOCAL-ANALYSIS] Vollstaendige Spur: {log_path}", file=sys.stderr); return 2
    try: payload=extract_payload(proc.stdout)
    except ValueError as exc:
        meldung = f"Antwort unbrauchbar: {exc}"
        write_run_log(log_path, cmd=cmd, claude_bin=claude, mode=mode, rc=0,
                      duration_s=dur, stdout=proc.stdout, stderr=proc.stderr, note=meldung)
        write_status(status_path, make_status("failed", now, prev, mode=mode, duration_s=dur, rc=0, error=meldung, log_path=str(log_path), **base))
        print(f"[LOCAL-ANALYSIS] {meldung}", file=sys.stderr)
        print(f"[LOCAL-ANALYSIS] Vollstaendige Spur: {log_path}", file=sys.stderr); return 2
    result = repo / str(cfg.get("result_path", "train_data/evaluation/analysis_result.json")); write_json_atomic(result, payload); base["last_success_date"] = today
    write_run_log(log_path, cmd=cmd, claude_bin=claude, mode=mode, rc=0,
                  duration_s=dur, stdout=proc.stdout, stderr=proc.stderr,
                  note=f"{len(payload['fehler'])} Fehler gemeldet")
    write_status(status_path, make_status("ok", now, prev, mode=mode, duration_s=dur, rc=0, num_fehler=len(payload["fehler"]), **base)); print(f"[LOCAL-ANALYSIS] OK — {len(payload['fehler'])} Fehler, {dur}s → {result}"); return 0


if __name__ == "__main__": raise SystemExit(main())
