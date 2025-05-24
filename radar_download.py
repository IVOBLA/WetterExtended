import os
import requests
import zipfile
from datetime import datetime
from email.utils import parsedate_to_datetime
from debug_utils import debug_log

KMZ_URL = "https://meteo.arso.gov.si/uploads/probase/www/nowcast/inca/inca_si0zm_latest.kmz"
KMZ_PATH = "weather_data.kmz"

def download_kmz():
    os.makedirs("data", exist_ok=True)

    try:
        last_download = os.path.getmtime(KMZ_PATH) if os.path.exists(KMZ_PATH) else 0
        response = requests.head(KMZ_URL, allow_redirects=True)
        remote_time = response.headers.get('Last-Modified')

        if remote_time:
            remote_timestamp = parsedate_to_datetime(remote_time).timestamp()
            if remote_timestamp <= last_download:
                debug_log("Kein neues Radarbild verfügbar.")
                return False

    except Exception as e:
        debug_log(f"Zeitprüfung fehlgeschlagen: {e} — lade trotzdem.")

    try:
        response = requests.get(KMZ_URL)
        with open(KMZ_PATH, "wb") as f:
            f.write(response.content)
    except Exception as e:
        debug_log(f"[FEHLER] KMZ-Download fehlgeschlagen: {e}")
        return False

    if not zipfile.is_zipfile(KMZ_PATH):
        debug_log("[FEHLER] Die heruntergeladene Datei ist keine gültige KMZ/ZIP-Datei.")
        return False

    try:
        with zipfile.ZipFile(KMZ_PATH, 'r') as zip_ref:
            zip_ref.extractall("data")

            for file in zip_ref.namelist():
                if file.endswith(".kml"):
                    if os.path.exists("data/latest.kml"):
                        os.remove("data/latest.kml")
                    os.rename(f"data/{file}", "data/latest.kml")

                if file.endswith(".png"):
                    if os.path.exists("data/latest.png"):
                        os.remove("data/latest.png")
                    os.rename(f"data/{file}", "data/latest.png")
    except Exception as e:
        debug_log(f"[FEHLER] Entpacken der KMZ-Datei fehlgeschlagen: {e}")
        return False

    debug_log("Radarbild und KML erfolgreich heruntergeladen und entpackt.")
    return True
