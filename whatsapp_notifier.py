# whatsapp_notifier.py
"""
WhatsApp-Benachrichtigungen via CallMeBot fuer WetterExtended.

Jeder Empfaenger benoetigt einen persoenlichen API-Key von CallMeBot.
Registrierung einmalig pro Rufnummer:
  WhatsApp → +34 644 82 17 47 senden: "I allow callmebot to send me messages"
  → Antwort enthaelt den persoenlichen apikey.

Empfaenger-Format im Orts-Datensatz (Feld 'whatsapp' in LOCATIONS_WATCHLIST):
  "+4369912345678:APIKEY1;+431234567890:APIKEY2"
  (Semikolon-getrennte phone:apikey-Paare; identisch zum email-Feld-Konzept)

Nachrichten sind immer Klartext (URL-kodiert, kein HTML).
Rate-Limit CallMeBot: ~1 Nachricht / 5 Sekunden pro Rufnummer.
Mehrere Empfaenger werden sequentiell mit _SEND_DELAY_S Pause gesendet.
"""

import time
import urllib.error
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

try:
    from debug_utils import debug_log
except Exception:
    def debug_log(msg: str) -> None:  # type: ignore[misc]
        print(msg)

# ── Konfiguration ─────────────────────────────────────────────────────────────
_CALLMEBOT_URL   = "https://api.callmebot.com/whatsapp.php"
_SEND_DELAY_S    = 5      # Pause zwischen Nachrichten bei mehreren Empfaengern
_TIMEOUT_S       = 10     # HTTP-Timeout pro Request

# Cooldown — verhindert Nachrichten-Flut (in-memory, Reset bei Service-Neustart)
_COOLDOWN_WARNING_S  = 900   # 15 Minuten zwischen Warnungen pro Ort
_COOLDOWN_ALLCLEAR_S = 300   #  5 Minuten zwischen Entwarnungen pro Ort

_cooldown_warning:  dict = {}   # {loc_name: float (epoch)}
_cooldown_allclear: dict = {}   # {loc_name: float (epoch)}


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _parse_wa_recipients(wa_str: str) -> list:
    """
    Parst den WhatsApp-Empfaenger-String.
    Erwartet Format: "+436991234567:APIKEY1;+431234567:APIKEY2"
    Gibt Liste von (phone, apikey)-Tupeln zurueck.
    Eintraege ohne ':' oder mit leerem phone/apikey werden mit Debug-Log uebersprungen.
    """
    if not wa_str or not wa_str.strip():
        debug_log("[WA] Empfaenger-String leer — kein WhatsApp-Versand.")
        return []
    result = []
    for entry in wa_str.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            debug_log(f"[WA] Empfaenger-Eintrag ohne ':' uebersprungen: {entry!r}")
            continue
        phone, apikey = entry.split(":", 1)
        phone  = phone.strip()
        apikey = apikey.strip()
        if phone and apikey:
            result.append((phone, apikey))
        else:
            debug_log(f"[WA] Unvollstaendiger Eintrag uebersprungen: {entry!r}")
    return result


def _send_whatsapp(phone: str, apikey: str, message: str) -> bool:
    """
    Sendet eine Klartext-Nachricht via CallMeBot.
    Gibt True zurueck wenn HTTP-Status 200 empfangen wurde, sonst False.
    Fehler werden geloggt, aber nie als Exception weitergegeben.
    """
    params = urllib.parse.urlencode({
        "phone":  phone,
        "text":   message,
        "apikey": apikey,
    })
    url = f"{_CALLMEBOT_URL}?{params}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "WetterExtended/1.0"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            if resp.status == 200:
                debug_log(f"[WA] Gesendet an {phone}")
                return True
            debug_log(f"[WA] HTTP {resp.status} fuer {phone}")
            return False
    except Exception as exc:
        debug_log(f"[WA] Fehler fuer {phone}: {exc}")
        return False


def _now_display() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M")


# ── Oeffentliche API ──────────────────────────────────────────────────────────

def send_warning_wa(loc_name: str, hits: dict, wa_str: str,
                    timestamp: str = "") -> bool:
    """
    Sendet eine Gewitterwarnung per WhatsApp fuer einen Ort.

    Parameter:
        loc_name  : Ortsname (z.B. "Klagenfurt")
        hits      : hits-Dict aus annotate_locations
                    {horizon_key: {hit_type, cell_id, distance_km, speed_kmh}}
        wa_str    : ";"-getrennte "phone:apikey"-Paare
        timestamp : optionaler Frame-Timestamp fuer Anzeige (leer = jetzt)

    Gibt True zurueck wenn mindestens 1 Empfaenger erfolgreich benachrichtigt wurde.
    """
    recipients = _parse_wa_recipients(wa_str)
    if not recipients:
        debug_log(
            f"[WA] Warnung {loc_name}: keine gueltigen Empfaenger "
            f"(wa_str={wa_str!r:.60}) — Versand abgebrochen."
        )
        return False

    now = time.time()
    if now - _cooldown_warning.get(loc_name, 0) < _COOLDOWN_WARNING_S:
        debug_log(
            f"[WA] Warnung {loc_name}: Cooldown aktiv "
            f"({int(_COOLDOWN_WARNING_S / 60)} min)."
        )
        return False

    # Fruehesten Treffer ermitteln: Horizont-Key 0 (jetzt) hat Vorrang,
    # dann kleinster positiver Horizont — identische Logik wie email_notifier.py
    sorted_hits = sorted(hits.items(), key=lambda x: int(x[0]))
    earliest_h  = int(sorted_hits[0][0]) if sorted_hits else None
    earliest    = sorted_hits[0][1]       if sorted_hits else {}
    cell_id     = earliest.get("cell_id",     "—")
    dist        = earliest.get("distance_km", "—")
    speed       = earliest.get("speed_kmh",   "—")

    if earliest_h == 0:
        eta_text = "ist JETZT im Bereich"
    elif earliest_h is not None:
        eta_dt   = datetime.now() + timedelta(minutes=earliest_h)
        eta_text = f"trifft in ~{earliest_h} Min. (ca. {eta_dt.strftime('%H:%M')} Uhr)"
    else:
        eta_text = "trifft den Bereich voraussichtlich"

    ts_display = timestamp or _now_display()
    message = (
        f"GEWITTERWARNUNG {loc_name}\n"
        f"{ts_display}\n\n"
        f"Zelle {cell_id} {eta_text}\n"
        f"Distanz: {dist} km  |  {speed} km/h\n\n"
        f"WetterExtended Kaernten"
    )

    any_ok = False
    for idx, (phone, apikey) in enumerate(recipients):
        if idx > 0:
            time.sleep(_SEND_DELAY_S)
        if _send_whatsapp(phone, apikey, message):
            any_ok = True

    if any_ok:
        _cooldown_warning[loc_name] = now
    return any_ok


def send_allclear_wa(loc_name: str, wa_str: str) -> bool:
    """
    Sendet eine Entwarnung per WhatsApp fuer einen Ort.
    Gibt True zurueck wenn mindestens 1 Empfaenger erfolgreich benachrichtigt wurde.
    """
    recipients = _parse_wa_recipients(wa_str)
    if not recipients:
        return False

    now = time.time()
    if now - _cooldown_allclear.get(loc_name, 0) < _COOLDOWN_ALLCLEAR_S:
        debug_log(f"[WA] Entwarnung {loc_name}: Cooldown aktiv.")
        return False

    message = (
        f"ENTWARNUNG {loc_name}\n"
        f"{_now_display()}\n\n"
        f"Die Gewittergefahr fuer {loc_name} ist vorueber.\n\n"
        f"WetterExtended Kaernten"
    )

    any_ok = False
    for idx, (phone, apikey) in enumerate(recipients):
        if idx > 0:
            time.sleep(_SEND_DELAY_S)
        if _send_whatsapp(phone, apikey, message):
            any_ok = True

    if any_ok:
        _cooldown_allclear[loc_name] = now
    return any_ok


def send_risk_alert_wa(location_name: str, dominant: str,
                       details: dict, wa_str: str) -> bool:
    """
    Sendet einen Hohes-Risiko-Alarm (Stufe 3) per WhatsApp.
    Kein Modul-seitiger Cooldown — der Tages-Cooldown wird von main.py
    (_RISK_ALERT_LOG) verwaltet, identisch zur E-Mail-Variante.

    Parameter:
        location_name : Ortsname
        dominant      : Hauptursache ("cell" | "track" | "lightning" | "atm")
        details       : info-Dict aus convective_outlook / risk_grid
                        (li, cape, cin, fl_height, cloud_height_m, ...)
        wa_str        : ";"-getrennte "phone:apikey"-Paare
    """
    recipients = _parse_wa_recipients(wa_str)
    if not recipients:
        return False

    dom_label = {
        "cell":      "Aktive Gewitterzelle in der Naehe",
        "track":     "Zelle zieht auf Ort zu (Forecast)",
        "lightning": "Starke Blitzaktivitaet",
        "atm":       "Atmosphaerische Instabilitaet",
        "ir_cell":   "IR-Vorlaeufer (CB/Overshooting Top)",
    }.get(dominant, dominant)

    li   = details.get("li")
    cape = details.get("cape")
    extra_lines = []
    if li is not None:
        instab = "sehr instabil" if li < -3 else ("instabil" if li < -1 else "stabil")
        extra_lines.append(f"Lifted Index: {li:.1f} ({instab})")
    if cape is not None and cape > 0:
        extra_lines.append(f"CAPE: {cape:.0f} J/kg")

    ts = datetime.utcnow().strftime("%d.%m.%Y %H:%M UTC")
    extra_str = "\n".join(extra_lines)
    if extra_str:
        extra_str = "\n" + extra_str

    message = (
        f"HOHES GEWITTERRISIKO — {location_name}\n"
        f"{ts}\n\n"
        f"Ursache: {dom_label}"
        f"{extra_str}\n\n"
        f"Naechste Warnung frühestens in 2 Stunden.\n"
        f"WetterExtended Kaernten"
    )

    any_ok = False
    for idx, (phone, apikey) in enumerate(recipients):
        if idx > 0:
            time.sleep(_SEND_DELAY_S)
        if _send_whatsapp(phone, apikey, message):
            any_ok = True
    return any_ok


def send_test_wa(wa_str: str) -> dict:
    """
    Sendet eine Testnachricht an alle Empfaenger im wa_str.

    Bypasst den Cooldown — ausschliesslich fuer manuelle Konfigurationspruefung
    aus dem Admin-Panel gedacht. Darf nicht im automatischen Warn-Pfad verwendet werden.

    Im Gegensatz zu _send_whatsapp() liest diese Funktion den HTTP-Response-Body
    auch bei Fehlern aus und gibt ihn als "error"-Feld zurueck — damit ist der
    exakte CallMeBot-Fehlertext (z.B. "Not Registered", "API Key not Valid")
    fuer den Benutzer sichtbar.

    Parameter:
        wa_str : ";"-getrennte "phone:apikey"-Paare
                 z.B. "+4369912345678:KEY1;+43664...:KEY2"

    Rueckgabe:
        {
          "ok":       bool,        # True wenn mindestens 1 Empfaenger erreicht
          "sent_to":  [str, ...],  # Erfolgreich erreichte Telefonnummern
          "failed":   [str, ...],  # Nicht erreichte Telefonnummern
          "error":    str | None,  # Letzter Fehlertext (CallMeBot-Antwort oder Netzwerk)
        }
    """
    recipients = _parse_wa_recipients(wa_str)
    if not recipients:
        debug_log("[WA-TEST] Keine gueltigen Empfaenger im wa_str.")
        return {"ok": False, "sent_to": [], "failed": [],
                "error": "Kein gueltiger Empfaenger (Format: +43Nr:APIKey)"}

    ts         = datetime.now().strftime("%d.%m.%Y %H:%M")
    sent_to:   list = []
    failed:    list = []
    last_error: str | None = None

    for idx, (phone, apikey) in enumerate(recipients):
        if idx > 0:
            time.sleep(_SEND_DELAY_S)

        message = (
            f"WetterExtended Test\n"
            f"{ts}\n\n"
            f"Diese Nachricht bestaetigt dass WhatsApp-Benachrichtigungen "
            f"fuer WetterExtended korrekt konfiguriert sind.\n"
            f"Empfaenger: {phone}"
        )

        # HTTP-Call inline (nicht via _send_whatsapp) — damit der Response-Body
        # auch bei Fehlern ausgelesen und zurueckgegeben werden kann.
        params = urllib.parse.urlencode({
            "phone":  phone,
            "text":   message,
            "apikey": apikey,
        })
        url = f"{_CALLMEBOT_URL}?{params}"
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "WetterExtended/1.0"}
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                body = resp.read().decode("utf-8", errors="replace").strip()
                if resp.status == 200:
                    sent_to.append(phone)
                    debug_log(f"[WA-TEST] Gesendet: {phone} — {body[:80]}")
                else:
                    failed.append(phone)
                    last_error = f"HTTP {resp.status}: {body[:300]}"
                    debug_log(f"[WA-TEST] HTTP {resp.status} fuer {phone}: {body[:200]}")

        except urllib.error.HTTPError as exc:
            # CallMeBot sendet Fehlertexte im Body auch bei 4xx/5xx
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", errors="replace").strip()
            except Exception:
                pass
            last_error = f"HTTP {exc.code}: {error_body[:300] or exc.reason}"
            failed.append(phone)
            debug_log(
                f"[WA-TEST] HTTP-Fehler {exc.code} fuer {phone}: "
                f"{error_body[:200] or exc.reason}"
            )

        except Exception as exc:
            last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            failed.append(phone)
            debug_log(f"[WA-TEST] Netzwerk-Fehler fuer {phone}: {exc}")

    debug_log(
        f"[WA-TEST] Ergebnis: sent={sent_to}, failed={failed}, "
        f"error={last_error!r:.120}"
    )
    return {
        "ok":      len(sent_to) > 0,
        "sent_to": sent_to,
        "failed":  failed,
        "error":   last_error,
    }
