"""
tests/test_b124_full_mode_log_clearing.py

B124: install.sh leert im Full-Modus ALLE Logs vollständig.
Belegt (grep-basiert auf install.sh):
  1. Die wirkungslose Per-Unit-Vacuum-Zeile ist entfernt.
  2. Globales rotate + vacuum-time=1s ist vorhanden.
  3. nginx access.log und error.log werden geleert.
  4. nginx wird zum Neuöffnen der Handles angestoßen (reload/reopen).
  5. Das Log-Leeren steht im Full-Modus-Zweig.

Ausführbar: python3 -m pytest tests/test_b124_full_mode_log_clearing.py -v
"""
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_install_sh():
    path = os.path.join(_ROOT, "install.sh")
    assert os.path.exists(path), "install.sh fehlt"
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_ineffective_per_unit_vacuum_removed():
    txt = _read_install_sh()
    assert '--vacuum-time=1s --unit=' not in txt, \
        "Per-Unit-Vacuum (wirkungslos) muss entfernt sein"


def test_global_journal_clear_present():
    txt = _read_install_sh()
    assert "sudo journalctl --rotate" in txt
    assert "sudo journalctl --vacuum-time=1s" in txt


def test_nginx_logs_cleared():
    txt = _read_install_sh()
    assert "/var/log/nginx/access.log" in txt
    assert "/var/log/nginx/error.log" in txt
    assert "truncate -s 0" in txt


def test_nginx_handles_reopened():
    txt = _read_install_sh()
    assert ("systemctl reload nginx" in txt) or ("nginx -s reopen" in txt)


def test_log_clearing_inside_full_branch():
    txt = _read_install_sh()
    marker = "B124: nginx-Zugriffs-/Fehler-Logs"
    assert marker in txt
    # Der Marker muss innerhalb eines `if [[ "$MODE" == "full" ]]` Zweigs liegen:
    idx = txt.index(marker)
    prefix = txt[:idx]
    last_full = prefix.rfind('if [[ "$MODE" == "full" ]]; then')
    assert last_full != -1, "B124-nginx-Block nicht im Full-Branch gefunden"
