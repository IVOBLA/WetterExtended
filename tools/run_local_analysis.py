#!/usr/bin/env python3
"""P77 — unbeaufsichtigte, nur lesende lokale Analyse mit Claude Code."""
from __future__ import annotations

import argparse
import json
import os
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
FORBIDDEN_TOOL_TOKENS = (
    "write", "edit", "notebook", "git push", "git commit", "git add",
    "git checkout", "git reset", "sudo", "rm ", "rmdir", "chmod", "chown",
    "mv ", "mkfs", "truncate", "tee ", "pip", "npm", "apt", "curl", "wget",
    "python", "bash(sh", "bash(bash", "bash(zsh", "systemctl restart",
    "systemctl stop", "systemctl start",
)
FORBIDDEN_READ_BYPASS = (
    "bash(cat", "bash(head", "bash(tail", "bash(less", "bash(more",
    "bash(strings", "bash(xxd", "bash(od", "bash(grep", "bash(awk", "bash(sed",
)
REQUIRED_LIST_FIELDS = ("fehler", "loesungen", "verbesserungen", "prompts")
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


def validate_allowed_tools(spec: str) -> None:
    low = str(spec or "").lower()
    if not low.strip(): raise PreconditionError("allowed_tools ist leer")
    for tok in FORBIDDEN_TOOL_TOKENS:
        if tok in low: raise PreconditionError(f"allowed_tools enthält ein schreibendes Werkzeug: {tok!r}")
    for tok in FORBIDDEN_READ_BYPASS:
        if tok in low: raise PreconditionError(f"allowed_tools umgeht die Read-Deny-Regeln: {tok!r}")
    if "sqlite3" in low and "sqlite3 -readonly" not in low: raise PreconditionError("sqlite3 ist nur mit -readonly zulässig")


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


def check_preconditions(cfg, repo_dir):
    validate_allowed_tools(cfg.get("allowed_tools", "")); claude_bin = resolve_claude_bin(cfg)
    prompt_file = repo_dir / str(cfg.get("prompt_path", ""))
    if not prompt_file.is_file(): raise PreconditionError(f"Prompt-Datei fehlt: {prompt_file}")
    prompt = prompt_file.read_text(encoding="utf-8").strip()
    if not prompt: raise PreconditionError(f"Prompt-Datei ist leer: {prompt_file}")
    settings = repo_dir / str(cfg.get("settings_path", ""))
    if not settings.is_file(): raise PreconditionError(f"Settings-Datei mit den Deny-Regeln fehlt: {settings}")
    try: json.loads(settings.read_text(encoding="utf-8"))
    except Exception as exc: raise PreconditionError(f"Settings-Datei ist kein gültiges JSON: {exc}") from exc
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
    return validate_payload(json.loads(strip_code_fences(outer["result"])))


def read_json_quiet(path):
    try: return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception: return {}


def write_json_atomic(path, payload):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"); os.replace(str(tmp), str(path))


write_status = write_json_atomic


def make_status(state, now_local, previous=None, mode="", **fields):
    prev = previous or {}
    st = {"state": state, "mode": mode or prev.get("mode"), "ts_local": now_local.strftime("%Y-%m-%d %H:%M:%S"), "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "last_success_date": prev.get("last_success_date"), "last_attempt_date": prev.get("last_attempt_date"), "attempts_today": int(prev.get("attempts_today", 0) or 0), "duration_s": None, "rc": None, "num_fehler": None, "error": None, "claude_bin": prev.get("claude_bin")}
    st.update(fields); return st


def parse_args(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--repo-dir", default=str(Path(__file__).resolve().parents[1])); ap.add_argument("--force", action="store_true"); ap.add_argument("--check-only", action="store_true"); ap.add_argument("--dry-run", action="store_true"); return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv); repo = Path(args.repo_dir).resolve(); cfg = load_config(repo); mode, changed = load_mode(repo); now = datetime.now(TZ)
    status_path = repo / str(cfg.get("status_path", "train_data/evaluation/local_analysis_status.json")); prev = read_json_quiet(status_path)
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
    today = now.strftime("%Y-%m-%d"); attempts = int(prev.get("attempts_today", 0) or 0)+1 if prev.get("last_attempt_date") == today else 1; base = {"last_attempt_date": today, "attempts_today": attempts, "claude_bin": claude}; t0=time.monotonic()
    try: proc = subprocess.run(cmd, cwd=str(repo), env=build_subprocess_env(), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=int(cfg.get("timeout_s", 900)))
    except subprocess.TimeoutExpired:
        write_status(status_path, make_status("failed", now, prev, mode=mode, duration_s=round(time.monotonic()-t0,1), rc=124, error=f"Zeitlimit {cfg.get('timeout_s')}s überschritten", **base)); return 2
    dur=round(time.monotonic()-t0,1)
    if proc.returncode:
        write_status(status_path, make_status("failed", now, prev, mode=mode, duration_s=dur, rc=proc.returncode, error=(proc.stderr or "")[-500:], **base)); return 2
    try: payload=extract_payload(proc.stdout)
    except ValueError as exc:
        write_status(status_path, make_status("failed", now, prev, mode=mode, duration_s=dur, rc=0, error=str(exc), **base)); return 2
    result = repo / str(cfg.get("result_path", "train_data/evaluation/analysis_result.json")); write_json_atomic(result, payload); base["last_success_date"] = today
    write_status(status_path, make_status("ok", now, prev, mode=mode, duration_s=dur, rc=0, num_fehler=len(payload["fehler"]), **base)); print(f"[LOCAL-ANALYSIS] OK — {len(payload['fehler'])} Fehler, {dur}s → {result}"); return 0


if __name__ == "__main__": raise SystemExit(main())
