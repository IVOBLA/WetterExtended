from ftplib import FTP
import os
from debug_utils import debug_log

FTP_SERVER = "w00eab71.kasserver.com"
FTP_USER = "w00eab71"
FTP_PASS = "gttJsGxo"
FTP_PATH = "/wetterAI/"

def upload_file_ftp(local_path, remote_name):
    try:
        with FTP(FTP_SERVER) as ftp:
            ftp.login(user=FTP_USER, passwd=FTP_PASS)
            ftp.cwd(FTP_PATH)
            with open(local_path, "rb") as f:
                ftp.storbinary(f"STOR {remote_name}", f)
        debug_log(f"FTP Upload OK: {remote_name}")
    except Exception as e:
        debug_log(f"FTP Upload Fehler: {remote_name} — {e}")
