#!/usr/bin/env python3
"""
send_analysis_email.py — verschickt den Debug-Analyse-Report 2026-06-10 per Mail.

Nutzt den projekteigenen SMTP-Mailer (email_notifier._send_smtp) und damit die
SMTP-Zugangsdaten aus der .env (SMTP_HOST/PORT/USER/PASS/FROM).

Hintergrund: Der Report wurde in einer Sandbox ohne SMTP-Zugang (Port 587 durch
Netzwerk-Policy blockiert, keine Credentials) erstellt. Auf dem Pi (KI-PI) bzw.
jeder Umgebung mit gültiger .env genügt:

    python3 debug_exports/send_analysis_email.py

Empfänger ist per Default blaha540@gmail.com (per Argument überschreibbar).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import email_notifier as en

RECIPIENT = sys.argv[1] if len(sys.argv) > 1 else "blaha540@gmail.com"
REPORT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analyse_2026-06-10.md")


def _md_to_html(md: str) -> str:
    """Minimaler Markdown→HTML-Wrapper (Codeblöcke + Zeilen, ohne externe Libs)."""
    from html import escape
    out, in_code = [], False
    for line in md.splitlines():
        if line.startswith("```"):
            out.append("<pre style='background:#0f172a;color:#e2e8f0;padding:12px;"
                       "border-radius:6px;overflow:auto;font-size:12px'>" if not in_code else "</pre>")
            in_code = not in_code
            continue
        if in_code:
            out.append(escape(line))
            continue
        if line.startswith("# "):
            out.append(f"<h1 style='font-size:20px'>{escape(line[2:])}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2 style='font-size:17px;margin-top:20px'>{escape(line[3:])}</h2>")
        elif line.startswith("### "):
            out.append(f"<h3 style='font-size:14px'>{escape(line[4:])}</h3>")
        elif line.startswith("---"):
            out.append("<hr style='border:none;border-top:1px solid #ddd'>")
        elif line.strip() == "":
            out.append("<br>")
        else:
            out.append(f"<p style='margin:4px 0;font-size:13px'>{escape(line)}</p>")
    body = "\n".join(out)
    return (
        "<!DOCTYPE html><html lang='de'><head><meta charset='utf-8'></head>"
        "<body style='font-family:Arial,sans-serif;max-width:760px;margin:0 auto;"
        "padding:16px;background:#fff;color:#111'>" + body + "</body></html>"
    )


def main() -> int:
    if not en._is_configured():
        print("[FEHLER] SMTP nicht konfiguriert (.env: SMTP_HOST/USER/PASS). Mail nicht gesendet.")
        return 2
    with open(REPORT_MD, "r", encoding="utf-8") as fh:
        html = _md_to_html(fh.read())
    subject = "WetterExtended — Debug-Analyse 24h (2026-06-10): 4 Fehlerbilder + Fixes/Prompts"
    ok = en._send_smtp([RECIPIENT], subject, html)
    print(f"[{'OK' if ok else 'FEHLER'}] Mail an {RECIPIENT} {'gesendet' if ok else 'NICHT gesendet'}.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
