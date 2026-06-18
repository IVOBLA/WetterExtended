"""B178: install.sh prüft echten pip-Exit (PIPESTATUS) + verifiziert kritische Importe."""
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _install_sh():
    with open(os.path.join(_ROOT, "install.sh"), encoding="utf-8") as f:
        return f.read()


def test_pip_success_measured_by_pipestatus_not_tail():
    src = _install_sh()
    # Das fehleranfällige Muster "pip install ... | tail -5; then" darf NICHT mehr
    # als Erfolgsbedingung dienen (Exit-Code wäre der von tail, nicht von pip).
    assert "| tail -5; then" not in src, \
        "pip-Erfolg wird weiterhin am tail-Exit statt am echten pip-Exit gemessen"


def test_pip_install_safe_has_pipestatus_checks():
    src = _install_sh()
    # Drei pip-Install-Stufen → mind. 3 PIPESTATUS-Prüfungen in pip_install_safe.
    assert src.count("PIPESTATUS[0]") >= 3, \
        "pip_install_safe prüft den echten pip-Exit (PIPESTATUS[0]) nicht an allen Stufen"


def test_critical_import_verification_present():
    src = _install_sh()
    assert "B178" in src
    assert "Kritische Module NICHT importierbar" in src
    for mod in ("pysteps", "scipy", "cv2", "lightgbm"):
        assert mod in src, f"Verifikation nennt {mod} nicht"


def test_pysteps_lucaskanade_function_check_present():
    src = _install_sh()
    assert "dense_lucaskanade" in src
    assert "pySTEPS Lucas-Kanade Funktionstest" in src
    assert '"$VENV/bin/python3" - <<' in src
    assert "pip install git+https://github.com/pySTEPS/pysteps" in src


def test_pysteps_lucaskanade_function_check_is_offline():
    src = _install_sh()
    start = src.index('log_info "Teste pySTEPS Lucas-Kanade Funktion..."')
    end = src.index('print("OK: pySTEPS Lucas-Kanade Funktionstest:', start)
    block = src[start:end].lower()

    for forbidden in (
        "curl ",
        "wget ",
        "import requests",
        "requests.get",
        "requests.post",
        "urllib.request",
        "http://",
        "https://",
    ):
        assert forbidden not in block, \
            f"pySTEPS-Funktionstest enthält unerwarteten externen Aufruf: {forbidden}"


def test_requirements_still_lists_pysteps():
    with open(os.path.join(_ROOT, "requirements.txt"), encoding="utf-8") as f:
        req = f.read().lower()
    assert "pysteps" in req
