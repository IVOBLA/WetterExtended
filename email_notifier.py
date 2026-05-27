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


def send_risk_alert_email(location_name: str, dominant: str,
                          details: dict, recipient: str) -> bool:
    """
    P46: Alarm-E-Mail bei Gewitterrisiko=3 (Hoch) für einen Ort.
    E-Mail-Adresse kommt aus der Ortsdefinition (Locations-Seite, email-Feld).
    Max. 1× täglich pro Ort. Keine Entwarnung.
    Mehrere Empfänger: Semikolon-getrennt (user1@x.com;user2@y.com).
    """
    if not _is_configured() or not recipient:
        debug_log(f"[EMAIL] Risiko-Alarm nicht gesendet — SMTP oder Empfänger fehlt")
        return False

    dom_label = {
        "cell": "🌩 Aktive Gewitterzelle in der Nähe",
        "track": "📍 Zelle zieht auf Ort zu (Forecast-Zugbahn)",
        "lightning": "⚡ Starke Blitzaktivität",
        "atm": "☁ Atmosphärische Instabilität",
    }.get(dominant, dominant)
    li = details.get("li")
    fl = details.get("fl_height")
    cap = details.get("cape")
    cin = details.get("cin")
    cloud_h = details.get("cloud_height_m")
    detail_rows = ""
    if li is not None:
        instab = "sehr instabil" if li < -3 else "instabil" if li < -1 else "stabil"
        detail_rows += f"<tr><td style='padding:2px 8px'>Lifted Index</td><td><b>{li:.1f} °C</b> ({instab})</td></tr>"
    if fl and fl > 0:
        detail_rows += f"<tr><td style='padding:2px 8px'>Gefriergrenze</td><td><b>{fl:.0f} m</b></td></tr>"
    if cloud_h and cloud_h > 0:
        detail_rows += f"<tr><td style='padding:2px 8px'>Wolkenhöhe</td><td><b>{cloud_h:.0f} m</b></td></tr>"
    if cap and cap > 0:
        detail_rows += f"<tr><td style='padding:2px 8px'>CAPE</td><td><b>{cap:.0f} J/kg</b></td></tr>"
    if cin and abs(cin) > 10:
        detail_rows += f"<tr><td style='padding:2px 8px'>CIN</td><td><b>{cin:.0f} J/kg</b></td></tr>"

    from datetime import datetime as _dt
    ts = _dt.utcnow().strftime("%d.%m.%Y %H:%M UTC")
    html = f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;padding:16px">
  <div style="background:#dc2626;color:white;padding:16px 20px;border-radius:8px 8px 0 0">
    <h2 style="margin:0;font-size:20px">🔴 Hohes Gewitterrisiko — {location_name}</h2>
    <p style="margin:4px 0 0;opacity:.9;font-size:13px">{ts}</p>
  </div>
  <div style="background:#fff;padding:20px;border:1px solid #ddd;border-radius:0 0 8px 8px">
    <p style="color:#991b1b;font-weight:bold">⚠ Für <b>{location_name}</b> wurde hohes Gewitterrisiko (Stufe 3) festgestellt.</p>
    <p><b>Hauptursache:</b> {dom_label}</p>
    {f'<table style="font-size:13px;border-collapse:collapse">{detail_rows}</table>' if detail_rows else ''}
    <p style="font-size:12px;color:#6b7280;margin-top:16px">Max. 1 Warnung pro Ort und Tag. Keine Entwarnung wird gesendet.</p>
  </div>
</body></html>"""
    ok = True
    for addr in [a.strip() for a in recipient.split(";") if a.strip()]:
        ok = ok and _send_smtp(
            recipients=[addr],
            subject=f"⚠ Hohes Gewitterrisiko — {location_name}",
            html_body=html,
        )
    return ok


def send_ai_report_email(result: dict, email_str: str) -> bool:
    """
    Sendet den täglichen KI-Analyse-Report per E-Mail.
    Kein Cooldown — wird maximal einmal täglich vom Scheduler ausgelöst.

    Parameters:
        result    : Ergebnis von run_analysis() — overall_status, suggestions, report_snapshot
        email_str : ";"-getrennte Empfängeradressen
    """
    if not _is_configured():
        debug_log("[EMAIL] SMTP nicht konfiguriert — KI-Report nicht gesendet.")
        return False

    recipients = _parse_recipients(email_str)
    if not recipients:
        return False

    status      = result.get("overall_status", "ok")
    suggestions = result.get("suggestions", [])
    snapshot    = result.get("report_snapshot", {})
    ts_date     = (snapshot.get("generated_utc") or _now_str())[:10]

    hdr_color = {"ok": "#16a34a", "warning": "#ca8a04", "critical": "#dc2626"}.get(
        status, "#2563eb"
    )
    status_label = {"ok": "✅ OK", "warning": "⚠ WARNUNG", "critical": "🔴 KRITISCH"}.get(
        status, status.upper()
    )

    _PRI_STYLE = {
        "high":   "background:#fee2e2;color:#991b1b",
        "medium": "background:#fef9c3;color:#854d0e",
        "low":    "background:#dbeafe;color:#1e40af",
    }

    rows = ""
    for s in suggestions[:8]:
        pri   = s.get("priority", "low")
        style = _PRI_STYLE.get(pri, "background:#f3f4f6;color:#374151")
        rows += (
            f'<tr style="border-bottom:1px solid #e5e7eb">'
            f'<td style="padding:6px 8px;{style};font-weight:bold;white-space:nowrap">'
            f'{pri.upper()}</td>'
            f'<td style="padding:6px 8px;font-weight:bold;font-size:13px">'
            f'{s.get("title","")}</td>'
            f'<td style="padding:6px 8px;font-size:12px;color:#6b7280">'
            f'{s.get("description","")}</td>'
            f'<td style="padding:6px 8px;font-size:12px">'
            f'{s.get("action","")}</td>'
            f'</tr>'
        )

    api_failures = snapshot.get("api_health", {}).get("total_failures", 0)
    model_mae    = snapshot.get("model_quality", {}).get("mae_total")
    mae_str      = f"{model_mae:.2f} km" if isinstance(model_mae, (int, float)) else "n/a"
    n_sug        = len(suggestions)

    # Suggestions-Block vorab aufbauen (kein verschachteltes f-string)
    _failure_color = '#dc2626' if api_failures > 0 else '#16a34a'
    if n_sug == 0:
        _sug_html = '<p style="color:#16a34a;font-weight:bold">&#10003; Keine Probleme erkannt.</p>'
    else:
        _sug_html = (
            '<table style="width:100%;border-collapse:collapse;font-size:13px">'
            '<thead><tr style="background:#f0f0f0">'
            '<th style="padding:6px 8px;text-align:left;width:70px">Priorit&#228;t</th>'
            '<th style="padding:6px 8px;text-align:left">Titel</th>'
            '<th style="padding:6px 8px;text-align:left">Beschreibung</th>'
            '<th style="padding:6px 8px;text-align:left">Ma&#223;nahme</th>'
            '</tr></thead>'
            f'<tbody>{rows}</tbody>'
            '</table>'
        )

    _admin_url = _MAP_URL.replace('/karte', '')

    html = (
        '<!DOCTYPE html><html lang="de"><head><meta charset="utf-8"></head>'
        '<body style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;'
        'padding:16px;background:#f5f5f5">'
        f'<div style="background:{hdr_color};color:white;padding:16px 20px;'
        'border-radius:8px 8px 0 0">'
        '<h2 style="margin:0;font-size:20px">&#129302; WetterExtended KI-Report</h2>'
        f'<p style="margin:4px 0 0;font-size:15px;opacity:.9">'
        f'{ts_date} &bull; Status: {status_label}</p></div>'
        '<div style="background:#fff;padding:20px;border:1px solid #ddd;'
        'border-radius:0 0 8px 8px">'
        '<table style="width:100%;border-collapse:collapse;margin-bottom:16px;font-size:13px"><tr>'
        '<td style="padding:4px 8px;color:#6b7280">API-Fehler (24h)</td>'
        f'<td style="padding:4px 8px;font-weight:bold;color:{_failure_color}">{api_failures}</td>'
        '<td style="padding:4px 8px;color:#6b7280">Modell MAE</td>'
        f'<td style="padding:4px 8px;font-weight:bold">{mae_str}</td>'
        '<td style="padding:4px 8px;color:#6b7280">Vorschl&#228;ge</td>'
        f'<td style="padding:4px 8px;font-weight:bold">{n_sug}</td>'
        '</tr></table>'
        + _sug_html +
        f'<div style="margin-top:20px;text-align:center">'
        f'<a href="{_admin_url}" style="display:inline-block;background:#2563eb;'
        'color:white;padding:10px 24px;border-radius:6px;text-decoration:none;'
        'font-weight:bold;font-size:14px">&#128421; Admin-Panel &#246;ffnen</a></div>'
        '<hr style="border:none;border-top:1px solid #eee;margin:20px 0">'
        '<p style="font-size:11px;color:#aaa;margin:0">'
        'WetterExtended &bull; K&#228;rnten Radar-Tracking &bull; '
        'Automatischer Tagesbericht</p></div></body></html>'
    )

    subject = f"🤖 WetterExtended KI-Report {ts_date} — {status_label}"
    return _send_smtp(recipients, subject, html)


def send_drift_alert(status: dict) -> None:
    """
    Sendet eine E-Mail-Warnung bei erkanntem Model-Drift.
    Nutzt dieselbe SMTP-Konfiguration wie Sturmwarnungen.
    """
    if not _is_configured():
        debug_log("[DRIFT-MAIL] SMTP nicht konfiguriert — kein Alert.")
        return

    subject = "⚠️ WetterExtended: Model-Drift erkannt"
    delta = status.get("delta_km", "?")
    recent = status.get("mae_recent_km", "?")
    base = status.get("mae_baseline_km", "?")
    body = f"""
<html><body>
<h2>⚠️ WetterExtended Model-Drift-Alarm</h2>
<p>Der Nowcast-Fehler hat sich signifikant verschlechtert:</p>
<table border="1" cellpadding="4">
  <tr><th>Kennzahl</th><th>Wert</th></tr>
  <tr><td>MAE recent (letzte 24 h)</td><td><b>{recent} km</b></td></tr>
  <tr><td>MAE baseline (7-Tage-Mittel)</td><td>{base} km</td></tr>
  <tr><td>Verschlechterung</td><td style="color:red"><b>+{delta} km</b></td></tr>
  <tr><td>Threshold</td><td>{status.get("threshold_km")} km</td></tr>
</table>
<p><b>Mögliche Ursachen:</b> Wetter-Regime-Wechsel, zu wenig Training-Samples,
Feature-Drift (neue Radar-Kalibrierung), Datenausfall bei einem API-Provider.</p>
<p><b>Maßnahmen:</b></p>
<ul>
  <li>Admin-Panel → Seite „Genauigkeit" prüfen</li>
  <li><code>python3 models_rollback.py list</code> — frühere bessere Version?</li>
  <li>Nächstes Training abwarten oder manuell auslösen</li>
</ul>
<p><small>Gesendet von WetterExtended drift_detector.py</small></p>
</body></html>
"""
    try:
        _send_smtp(_get_all_drift_recipients(), subject, body)
        debug_log("[DRIFT-MAIL] Drift-Alarm versendet.")
    except Exception as exc:
        debug_log(f"[DRIFT-MAIL] Fehler beim Senden: {exc}")


def _get_all_drift_recipients() -> list:
    """Gibt E-Mail-Empfänger für Drift-Alarm zurück (alle konfigurierten Ort-Mails)."""
    try:
        import runtime_config as _rc

        locations = _rc.get("LOCATIONS_WATCHLIST", [])
        recipients = set()
        for loc in locations:
            for addr in str(loc.get("email", "")).split(";"):
                addr = addr.strip()
                if addr and "@" in addr:
                    recipients.add(addr)
        return list(recipients) if recipients else [os.getenv("SMTP_USER", "")]
    except Exception:
        return [os.getenv("SMTP_USER", "")]


if __name__ == "__main__":
    # Schnelltest: Konfiguration pruefen
    print(f"SMTP konfiguriert: {_is_configured()}")
    print(f"Host: {_SMTP_HOST}:{_SMTP_PORT} | User: {_SMTP_USER}")
