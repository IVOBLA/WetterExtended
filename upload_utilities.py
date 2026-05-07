from ftplib import FTP
import os
from dotenv import load_dotenv
from debug_utils import debug_log

load_dotenv()

FTP_SERVER = os.getenv("FTP_SERVER", "")
FTP_USER   = os.getenv("FTP_USER", "")
FTP_PASS   = os.getenv("FTP_PASS", "")
FTP_PATH   = os.getenv("FTP_PATH", "/")


def upload_file_ftp(local_path: str, remote_name: str) -> bool:
    if not FTP_SERVER or not FTP_USER or not FTP_PASS:
        debug_log("[FTP] Keine Credentials konfiguriert — Upload übersprungen.")
        return False
    if not os.path.exists(local_path):
        debug_log(f"[FTP] Lokale Datei nicht gefunden: {local_path}")
        return False
    try:
        with FTP(FTP_SERVER) as ftp:
            ftp.login(user=FTP_USER, passwd=FTP_PASS)
            ftp.cwd(FTP_PATH)
            with open(local_path, "rb") as f:
                ftp.storbinary(f"STOR {remote_name}", f)
        debug_log(f"[FTP] Upload OK: {remote_name}")
        return True
    except Exception as e:
        debug_log(f"[FTP] Upload Fehler: {remote_name} — {e}")
        return False
