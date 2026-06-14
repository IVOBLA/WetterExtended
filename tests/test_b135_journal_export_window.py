"""B135: Journal-Export nutzt UTC-Epoch (@sek) für --since/--until und -n (neueste)."""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_export_cmd_uses_epoch_until_and_tail(monkeypatch):
    import debug_export

    captured = {}

    class _Result:
        returncode = 0
        stdout = "line1\nline2\n"
        stderr = ""

    def _fake_which(_):
        return "/usr/bin/journalctl"

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["timeout"] = kwargs.get("timeout")
        return _Result()

    monkeypatch.setattr(debug_export.shutil, "which", _fake_which)
    monkeypatch.setattr(debug_export.subprocess, "run", _fake_run)

    ws = datetime(2026, 6, 13, 7, 10, 0, tzinfo=timezone.utc)
    now = datetime(2026, 6, 14, 7, 10, 0, tzinfo=timezone.utc)
    text, ok = debug_export._journalctl_export_text("wetterprojekt", ws, now)

    assert ok is True
    cmd = captured["cmd"]
    # --since und --until sind Epoch-Angaben (@<sek>), zeitzonenfrei:
    assert "--since" in cmd and "--until" in cmd
    since_val = cmd[cmd.index("--since") + 1]
    until_val = cmd[cmd.index("--until") + 1]
    assert since_val == f"@{int(ws.timestamp())}"
    assert until_val == f"@{int(now.timestamp())}"
    # neueste Zeilen via -n, kein --lines-vom-Anfang:
    assert "-n" in cmd
    assert "--lines=2000" not in cmd
    # kein naiver Datums-String mehr:
    assert not any(":" in c and "-" in c and "@" not in c for c in cmd if c not in ("-u", "--no-pager"))


def test_naive_datetime_treated_as_utc(monkeypatch):
    """Ein naives (tz-loses) window_start wird als UTC interpretiert."""
    import debug_export

    captured = {}

    class _Result:
        returncode = 0
        stdout = "x\n"
        stderr = ""

    monkeypatch.setattr(debug_export.shutil, "which", lambda _: "/usr/bin/journalctl")
    monkeypatch.setattr(debug_export.subprocess, "run",
                        lambda cmd, **k: (captured.update(cmd=cmd) or _Result()))

    ws_naive = datetime(2026, 6, 13, 7, 10, 0)            # naiv
    ws_utc = ws_naive.replace(tzinfo=timezone.utc)
    now = datetime(2026, 6, 14, 7, 10, 0, tzinfo=timezone.utc)
    debug_export._journalctl_export_text("wetterprojekt", ws_naive, now)
    since_val = captured["cmd"][captured["cmd"].index("--since") + 1]
    assert since_val == f"@{int(ws_utc.timestamp())}"
