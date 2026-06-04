# watchdog_heartbeat.py
"""
systemd Watchdog-Heartbeat als Daemon-Thread.

Wenn NOTIFY_SOCKET gesetzt (systemd Type=notify Service), sendet dieser Thread
alle INTERVAL Sekunden WATCHDOG=1 an systemd. Ausbleibende Pings →
systemd startet den Service nach WatchdogSec neu.

Verwendung (einmalig beim Service-Start aufrufen):
    import watchdog_heartbeat
    watchdog_heartbeat.start()

start() sendet auch READY=1 (signalisiert systemd: Service ist bereit).
"""

import os
import socket
import threading
import time

def _derive_interval() -> int:
    """
    Leitet das Ping-Intervall aus WATCHDOG_USEC ab (systemd-Umgebungsvariable).
    Formel: max(1, floor(WatchdogSec / 2) - 1), begrenzt auf max. 25 s.
    Wenn WATCHDOG_USEC nicht gesetzt: Fallback 25 s.
    """
    usec = os.getenv("WATCHDOG_USEC")
    if usec:
        try:
            watchdog_sec = int(usec) / 1_000_000
            if watchdog_sec > 0:
                return max(1, min(25, int(watchdog_sec / 2) - 1))
        except (ValueError, ZeroDivisionError):
            pass
    return 25


_INTERVAL: int = _derive_interval()
_started: bool = False
_lock = threading.Lock()


def _sd_notify(msg: str) -> None:
    """Sendet eine Nachricht an systemd via NOTIFY_SOCKET (AF_UNIX DGRAM)."""
    sock_path = os.getenv("NOTIFY_SOCKET", "")
    if not sock_path:
        return
    try:
        addr = "\0" + sock_path[1:] if sock_path.startswith("@") else sock_path
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(addr)
            s.sendall(msg.encode())
    except Exception:
        pass


def _heartbeat_loop() -> None:
    while True:
        _sd_notify("WATCHDOG=1")
        time.sleep(_INTERVAL)


def start(interval: int = _INTERVAL) -> threading.Thread | None:
    """
    Startet den Watchdog-Thread (idempotent — mehrfacher Aufruf ist sicher).
    Sendet READY=1 und startet dann den Heartbeat-Thread.

    Parameters
    ----------
    interval : Ping-Intervall in Sekunden (default: 25, muss < WatchdogSec/2 sein)

    Returns
    -------
    threading.Thread oder None (wenn NOTIFY_SOCKET nicht gesetzt)
    """
    global _started, _INTERVAL

    with _lock:
        if _started:
            return None
        _INTERVAL = interval
        _started = True

    _sd_notify("READY=1")

    if not os.getenv("NOTIFY_SOCKET", ""):
        return None

    t = threading.Thread(
        target=_heartbeat_loop,
        daemon=True,
        name="sd-watchdog",
    )
    t.start()
    return t
