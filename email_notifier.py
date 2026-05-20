"""
email_notifier.py — Warnmail-Versand fuer WetterExtended.

SMTP-Konfiguration aus Umgebungsvariablen (.env):
    SMTP_HOST     SMTP-Server (z.B. smtp.gmail.com)
    SMTP_PORT     Port (Default: 587)
    SMTP_USER     Benutzername / Login-Adresse
    SMTP_PASS     Passwort oder App-Passwort
    SMTP_FROM     Absenderadresse (z.B. "WetterExtended <user@gmail.com>")

Pro Ort koennen mehrere Empfaenger durch ";" getrennt angegeben werden:
    "user1@example.com;user2@example.com"

Cooldown verhindert Mail-Flut:
    Warnung:   max. 1 Mail pro Ort alle 15 Minuten
    Entwarnung: max. 1 Mail pro Ort alle 5 Minuten
"""

import os
import smtplib
import ssl
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from debug_utils import debug_log
except Exception:
    def debug_log(msg):
        print(msg)

# ── Konfiguration aus .env ────────────────────────────────────────────────────
_SMTP_HOST = os.getenv("SMTP_HOST", "")
_SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
_SMTP_USER = os.getenv("SMTP_USER", "")
_SMTP_PASS = os.getenv("SMTP_PASS", "")
_SMTP_FROM = os.getenv("SMTP_FROM", _SMTP_USER)

# Karte-URL (fix, oeffentlich erreichbar ohne Login)
_MAP_URL = "http://blasolar.ddns.net:81/karte"

# ── Cooldown-Tracking (in-memory, Reset bei Service-Neustart) ─────────────────
_cooldown_warning:  dict = {}   # loc_name → letzte Sendezeit (epoch)
_cooldown_allclear: dict = {}   # loc_name → letzte Sendezeit (epoch)
_COOLDOWN_WARNING_S  = 900   # 15 Minuten
_COOLDOWN_ALLCLEAR_S = 300   #  5 Minuten


def _is_configured() -> bool:
    """True wenn SMTP-Konfiguration vollstaendig."""
    return bool(_SMTP_HOST and _SMTP_USER and _SMTP_PASS)


def _parse_recipients(email_str: str) -> list:
    """
    Parst ";"-getrennte E-Mail-Adressen.
    Leere Eintraege und Leerzeichen werden ignoriert.
    """
    if not email_str:
        return []
    return [e.strip() for e in email_str.split(";") if e.strip()]


def _send_smtp(recipients: list, subject: str, html_body: str) -> bool:
    """
    Versendet eine HTML-Mail via SMTP STARTTLS.
    Gibt True bei Erfolg zurueck, False bei Fehler.
    """
    if not recipients:
        debug_log("[EMAIL] Keine Empfaenger — Mail nicht gesendet.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = _SMTP_FROM
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.login(_SMTP_USER, _SMTP_PASS)
            server.sendmail(_SMTP_FROM, recipients, msg.as_string())
        debug_log(f"[EMAIL] Gesendet an: {', '.join(recipients)} | Betreff: {subject}")
        return True
    except Exception as exc:
        debug_log(f"[EMAIL] SMTP-Fehler: {exc}")
        return False


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


def send_warning_email(loc_name: str, hits: dict, email_str: str,
                       timestamp: str = "") -> bool:
    """
    Sendet eine Gewitterwarnung fuer einen Ort.

    Parameter:
        loc_name   : Ortsname (z.B. "Klagenfurt")
        hits       : hits-Dict aus annotate_locations
                     {horizon: {hit_type, cell_id, distance_km, speed_kmh}}
        email_str  : ";"-getrennte Empfaengeradressen
        timestamp  : optionaler Frame-Timestamp fuer Anzeige
    """
    if not _is_configured():
        debug_log("[EMAIL] SMTP nicht konfiguriert — Warnung nicht gesendet.")
        return False

    # Cooldown pruefen
    now = time.time()
    last = _cooldown_warning.get(loc_name, 0)
    if now - last < _COOLDOWN_WARNING_S:
        debug_log(f"[EMAIL] Warnung {loc_name}: Cooldown aktiv ({int(_COOLDOWN_WARNING_S/60)} min).")
        return False

    recipients = _parse_recipients(email_str)
    if not recipients:
        return False

    # Tabellenzeilen aus hits aufbauen
    rows = ""
    for horizon, hit in sorted(hits.items(), key=lambda x: int(x[0])):
        h_label = "JETZT" if int(horizon) == 0 else f"+{horizon} min"
        hit_type_labels = {
            "current":      "Zelle IM ORT",
            "slow_approach":"Langsam ziehend (Starkregen)",
            "forecast":     "Forecast-Pfad trifft Ort",
        }
        type_label = hit_type_labels.get(hit.get("hit_type", ""), hit.get("hit_type", ""))
        rows += f"""
        <tr style="border-bottom:1px solid #eee">
          <td style="padding:6px 10px;font-weight:bold">{h_label}</td>
          <td style="padding:6px 10px">{hit.get('cell_id','—')}</td>
          <td style="padding:6px 10px">{hit.get('distance_km','—')} km</td>
          <td style="padding:6px 10px">{hit.get('speed_kmh','—')} km/h</td>
          <td style="padding:6px 10px">{type_label}</td>
        </tr>"""

    ts_display = timestamp or _now_str()
    html = f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:620px;margin:0 auto;padding:16px;background:#f5f5f5">

  <div style="background:#dc2626;color:white;padding:16px 20px;border-radius:8px 8px 0 0">
    <h2 style="margin:0;font-size:20px">⚡ GEWITTERWARNUNG</h2>
    <p style="margin:4px 0 0;font-size:15px;opacity:.9">{loc_name} — {ts_display}</p>
  </div>

  <div style="background:#fff;padding:20px;border:1px solid #ddd;border-radius:0 0 8px 8px">

    <p style="margin-top:0">Eine <strong>Gewitterzelle</strong> bedroht den Bereich
    <strong>{loc_name}</strong>.</p>

    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead>
        <tr style="background:#f0f0f0">
          <th style="padding:6px 10px;text-align:left">Horizont</th>
          <th style="padding:6px 10px;text-align:left">Zelle</th>
          <th style="padding:6px 10px;text-align:left">Distanz</th>
          <th style="padding:6px 10px;text-align:left">Geschw.</th>
          <th style="padding:6px 10px;text-align:left">Typ</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>

    <div style="margin-top:20px;text-align:center">
      <a href="{_MAP_URL}"
         style="display:inline-block;background:#2563eb;color:white;padding:12px 28px;
                border-radius:6px;text-decoration:none;font-weight:bold;font-size:15px">
        🗺 Karte jetzt oeffnen
      </a>
      <p style="font-size:11px;color:#888;margin-top:8px">{_MAP_URL}</p>
    </div>

    <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
    <p style="font-size:11px;color:#aaa;margin:0">
      WetterExtended &bull; Kaernten Radar-Tracking &bull; Automatische Benachrichtigung
    </p>
  </div>
</body></html>"""

    subject = f"⚡ GEWITTERWARNUNG {loc_name}"
    ok = _send_smtp(recipients, subject, html)
    if ok:
        _cooldown_warning[loc_name] = now
    return ok


def send_allclear_email(loc_name: str, email_str: str) -> bool:
    """
    Sendet eine Entwarnung fuer einen Ort.
    """
    if not _is_configured():
        return False

    now = time.time()
    last = _cooldown_allclear.get(loc_name, 0)
    if now - last < _COOLDOWN_ALLCLEAR_S:
        debug_log(f"[EMAIL] Entwarnung {loc_name}: Cooldown aktiv.")
        return False

    recipients = _parse_recipients(email_str)
    if not recipients:
        return False

    ts_display = _now_str()
    html = f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:620px;margin:0 auto;padding:16px;background:#f5f5f5">

  <div style="background:#16a34a;color:white;padding:16px 20px;border-radius:8px 8px 0 0">
    <h2 style="margin:0;font-size:20px">✅ ENTWARNUNG</h2>
    <p style="margin:4px 0 0;font-size:15px;opacity:.9">{loc_name} — {ts_display}</p>
  </div>

  <div style="background:#fff;padding:20px;border:1px solid #ddd;border-radius:0 0 8px 8px">
    <p style="margin-top:0">Die Gewittergefahr fuer <strong>{loc_name}</strong>
    ist vorueber. Keine aktive Sturmzelle mehr im Bereich.</p>

    <div style="margin-top:16px;text-align:center">
      <a href="{_MAP_URL}"
         style="display:inline-block;background:#2563eb;color:white;padding:10px 24px;
                border-radius:6px;text-decoration:none;font-weight:bold;font-size:14px">
        🗺 Karte oeffnen
      </a>
    </div>

    <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
    <p style="font-size:11px;color:#aaa;margin:0">
      WetterExtended &bull; Kaernten Radar-Tracking &bull; Automatische Benachrichtigung
    </p>
  </div>
</body></html>"""

    subject = f"✅ Entwarnung {loc_name}"
    ok = _send_smtp(recipients, subject, html)
    if ok:
        _cooldown_allclear[loc_name] = now
    return ok


if __name__ == "__main__":
    # Schnelltest: Konfiguration pruefen
    print(f"SMTP konfiguriert: {_is_configured()}")
    print(f"Host: {_SMTP_HOST}:{_SMTP_PORT} | User: {_SMTP_USER}")
