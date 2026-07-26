"""B469 — Sicherungskopien von Zugangsdaten muessen ueberall gesperrt sein."""
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RO_QUERY = REPO / "tools" / "ro_query.py"
SETTINGS = REPO / "tools" / "local_analysis_settings.json"
GITIGNORE = REPO / ".gitignore"
INSTALL = REPO / "install.sh"


@pytest.fixture
def rq(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("ro_query_b469", RO_QUERY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "REPO", tmp_path)
    return mod


@pytest.mark.parametrize("name", [
    ".env", ".env.local", ".env.production",
    ".env_Copy", ".env.bak", ".env~", ".env.old",
    "server.pem", "server.key", "id_rsa", "id_rsa.pub",
])
def test_is_secret_name_catches_secrets(rq, name):
    assert rq.is_secret_name(name) is True


@pytest.mark.parametrize("name", [
    ".env.example", "config.py", "readme.md", "environment.txt", "data.json",
])
def test_is_secret_name_allows_harmless(rq, name):
    # .env.example beginnt mit ".env" -> bewusst gesperrt (Platzhalter, harmlos);
    # die uebrigen duerfen NICHT als Secret gelten.
    if name == ".env.example":
        assert rq.is_secret_name(name) is True
    else:
        assert rq.is_secret_name(name) is False


def test_check_inside_repo_blocks_env_copy(rq, tmp_path):
    (tmp_path / ".env_Copy").write_text("SECRET=1\n")
    with pytest.raises(rq.QueryError):
        rq.check_inside_repo(".env_Copy")


def test_cmd_files_hides_env_copy(rq, tmp_path):
    (tmp_path / ".env_Copy").write_text("SECRET=1\n")
    (tmp_path / ".env.bak").write_text("SECRET=1\n")
    (tmp_path / "harmless.txt").write_text("ok\n")
    out = rq.cmd_files(type("A", (), {"pattern": ".env*"}))
    assert ".env_Copy" not in out
    assert ".env.bak" not in out


def test_settings_deny_covers_backups():
    deny = json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]["deny"]
    # Bestehende B468-Regeln muessen erhalten bleiben ...
    for needed in ("Read(./.env)", "Read(./.env.*)", "Read(**/.env)"):
        assert needed in deny
    # ... und die neuen Glob-Regeln muessen Kopien abdecken.
    for needed in ("Read(./.env*)", "Read(**/.env*)"):
        assert needed in deny


def test_gitignore_ignores_backups_but_keeps_example():
    text = GITIGNORE.read_text(encoding="utf-8")
    assert "\n.env*\n" in text
    assert "!.env.example" in text


def test_install_rsync_excludes_env_backups():
    text = INSTALL.read_text(encoding="utf-8")
    assert "--exclude=/.env* \\" in text
    assert "--include=/.env.example \\" in text
