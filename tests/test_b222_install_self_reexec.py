"""
B222 — install.sh muss sich nach einem Selbst-Update (Phase 3) mit dem neuen
Skript neu starten (re-exec). Ohne Re-Exec führt der laufende Bash-Prozess das
ALTE Skript zu Ende aus; ein frisch gemergter install.sh-Fix greift erst beim
nächsten Aufruf.
"""
import subprocess
import pathlib


def _repo_root() -> pathlib.Path:
    p = pathlib.Path(__file__).resolve()
    for parent in [p, *p.parents]:
        if (parent / "install.sh").is_file():
            return parent
    raise AssertionError("Repo-Root (install.sh) nicht gefunden")


ROOT = _repo_root()
INSTALL = ROOT / "install.sh"


def test_install_sh_syntax_valid():
    r = subprocess.run(["bash", "-n", str(INSTALL)], capture_output=True, text=True)
    assert r.returncode == 0, f"bash -n fehlgeschlagen:\n{r.stderr}"


def test_reexec_mechanism_present():
    s = INSTALL.read_text()
    assert '_ORIG_ARGV=("$@")' in s, "Original-Argumente werden nicht gesichert"
    assert "_SELF_HASH_BEFORE" in s and "_SELF_HASH_AFTER" in s, "Selbst-Hash-Vergleich fehlt"
    assert "WETTER_INSTALL_REEXEC" in s, "Endlosschutz-Flag fehlt"
    assert 'exec bash "$_SELF_PATH" "${_ORIG_ARGV[@]}"' in s, "re-exec-Aufruf fehlt/abweichend"


def test_reexec_positioned_within_phase3():
    s = INSTALL.read_text()
    assert s.count('exec bash "$_SELF_PATH" "${_ORIG_ARGV[@]}"') == 1, "genau ein re-exec erwartet"
    i_p3 = s.find("Phase 3 — Source holen")
    i_p3b = s.find("Phase 3b")
    i_exec = s.find('exec bash "$_SELF_PATH"')
    assert i_p3 != -1 and i_p3b != -1 and i_exec != -1
    assert i_p3 < i_exec < i_p3b, "re-exec muss innerhalb Phase 3 (vor Phase 3b) liegen"
