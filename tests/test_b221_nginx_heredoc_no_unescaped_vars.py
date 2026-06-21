"""
B221 — Regressionstest: nginx-Here-Doc in install.sh darf keine unescapten
Bash-Variablen enthalten.

install.sh erzeugt die nginx-Config über einen UNQUOTED Here-Doc (`<<NGINXCONF`).
Bash expandiert dort jede `$VAR`; nginx-Variablen MÜSSEN daher als `\\$VAR` escaped
sein, sonst bricht install.sh unter `set -u` mit `unbound variable` ab (Phase 7d).
Dieser Test bewacht die gesamte Bug-Klasse.
"""
import pathlib
import re


def _repo_root() -> pathlib.Path:
    p = pathlib.Path(__file__).resolve()
    for parent in [p, *p.parents]:
        if (parent / "install.sh").is_file():
            return parent
    raise AssertionError("Repo-Root (install.sh) nicht gefunden")


ROOT = _repo_root()
INSTALL = ROOT / "install.sh"


def _heredoc_body() -> str:
    lines = INSTALL.read_text().splitlines()
    start = next(
        (
            i
            for i, line in enumerate(lines)
            if 'tee "$NGINX_SITE_CONF"' in line and "<<NGINXCONF" in line
        ),
        None,
    )
    assert start is not None, "nginx-Here-Doc-Start nicht gefunden"
    end = next(
        (j for j in range(start + 1, len(lines)) if lines[j] == "NGINXCONF"),
        None,
    )
    assert end is not None, "nginx-Here-Doc-Ende (NGINXCONF Spalte 0) nicht gefunden"
    return "\n".join(lines[start + 1 : end])


def test_request_uri_is_escaped():
    content = INSTALL.read_text()
    assert (
        "http://127.0.0.1:5000\\$request_uri;" in content
    ), "$request_uri ist nicht escaped"
    assert (
        "http://127.0.0.1:5000$request_uri;" not in content
    ), "unescaptes $request_uri vorhanden"


def test_heredoc_has_no_unescaped_bash_vars():
    body = _heredoc_body()
    allowed = {"FRONTEND_DIST", "TARGET"}  # einzige gewollte Bash-Expansionen
    scan = body.replace("\\$", "")  # escapte nginx-Vars sind sicher
    scan = re.sub(r"\$\(date[^)]*\)", "", scan)  # $(date ...) ist gewollt
    bad = sorted(
        {
            match.group(1)
            for match in re.finditer(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", scan)
            if match.group(1) not in allowed
        }
    )
    assert not bad, f"Unescapte Variablen im nginx-Here-Doc: {bad}"
