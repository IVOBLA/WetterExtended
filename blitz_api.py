# blitz_api.py
"""
Blitzortung.org Lightning-Daten für Kärnten.

Sicherheit: Credentials werden als HTTP Basic Auth übergeben (nicht in URL).
Fehler werden via log_api_failure protokolliert.
Speicherpfad über SAVE_PATHS["lightning"] (zentral konfiguriert).
"""
import os
import json
import requests
from datetime import datetime

from config import SAVE_PATHS
from debug_utils import debug_log, log_api_failure

# Credentials aus Umgebungsvariablen (in .env definiert)
USERNAME = os.getenv("BLITZ_USERNAME", "")
PASSWORD = os.getenv("BLITZ_PASSWORD", "")

# Kärnten Bounding Box
WEST  = 12.5
EAST  = 15.0
SOUTH = 46.4
NORTH = 47.1

NUM_STRIKES = 100

_BASE_URL = "https://data.blitzortung.org/Data/Protected/last_strikes.php"
_SAVE_DIR = SAVE_PATHS.get("lightning", "train_data/lightning/").rstrip("/")


def fetch_and_save_lightning(timestamp: str) -> None:
    """
    Holt die letzten NUM_STRIKES Blitze im Kärnten-Bereich von Blitzortung.org
    und speichert sie als JSON in SAVE_PATHS['lightning']/<timestamp>.json.
    Credentials: HTTP Basic Auth (nicht in URL — erscheint nicht in Logs).
    """
    os.makedirs(_SAVE_DIR, exist_ok=True)

    if not USERNAME or not PASSWORD:
        debug_log("[LIGHTNING] BLITZ_USERNAME / BLITZ_PASSWORD nicht gesetzt — übersprungen.")
        return

    params = (
        f"?number={NUM_STRIKES}"
        f"&west={WEST}&east={EAST}"
        f"&north={NORTH}&south={SOUTH}&sig=0"
    )
    # Credentials NICHT in URL — würden in Logs erscheinen
    url = _BASE_URL + params

    try:
        response = requests.get(
            url,
            auth=(USERNAME, PASSWORD),  # HTTP Basic Auth Header
            timeout=10,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        log_api_failure("Blitzortung", _BASE_URL, "timeout", fallback_used=True)
        debug_log("[LIGHTNING] Timeout beim Abrufen der Blitzdaten.")
        return
    except requests.exceptions.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        log_api_failure("Blitzortung", _BASE_URL,
                        f"http-{status}", fallback_used=True, http_status=status)
        debug_log(f"[LIGHTNING] HTTP-Fehler {status}.")
        return
    except Exception as exc:
        log_api_failure("Blitzortung", _BASE_URL,
                        f"{type(exc).__name__}: {exc}", fallback_used=True)
        debug_log(f"[LIGHTNING] Fehler: {exc}")
        return

    strikes = []
    for line in response.text.strip().splitlines():
        parts = line.strip().split(",")
        if len(parts) >= 4:
            try:
                time_str = parts[0]
                lat      = float(parts[1])
                lon      = float(parts[2])
                strength = float(parts[3])
                strikes.append({
                    "timestamp": time_str,
                    "lat": lat,
                    "lon": lon,
                    "strength": strength,
                })
            except ValueError:
                continue

    save_path = os.path.join(_SAVE_DIR, f"{timestamp}.json")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(strikes, f, indent=2)
    debug_log(f"[LIGHTNING] {len(strikes)} Blitzereignisse gespeichert: {save_path}")


if __name__ == "__main__":
    now = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    fetch_and_save_lightning(now)
