import os
import stat
import subprocess
import sys
from pathlib import Path

from scripts.dedupe_env import dedupe_env_file, main


ROOT = Path(__file__).resolve().parents[1]


def test_last_active_value_is_preserved(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\nA=2\n", encoding="utf-8")

    assert dedupe_env_file(env_file) == ["A"]
    assert env_file.read_text(encoding="utf-8") == "A=2\n"


def test_admin_token_value_is_never_logged(tmp_path, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ADMIN_API_TOKEN=old-secret\nADMIN_REQUIRE_TOKEN=false\n"
        "ADMIN_API_TOKEN=new-secret\nADMIN_REQUIRE_TOKEN=true\n",
        encoding="utf-8",
    )

    assert main([str(env_file)]) == 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert "ADMIN_API_TOKEN" in combined
    assert "ADMIN_REQUIRE_TOKEN" in combined
    assert "old-secret" not in combined
    assert "new-secret" not in combined
    assert env_file.read_text(encoding="utf-8") == (
        "ADMIN_API_TOKEN=new-secret\nADMIN_REQUIRE_TOKEN=true\n"
    )


def test_comments_and_commented_examples_remain(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# ADMIN_REQUIRE_TOKEN=false\n\nADMIN_REQUIRE_TOKEN=true\n"
        "# ADMIN_REQUIRE_TOKEN=false\nADMIN_REQUIRE_TOKEN=false\n",
        encoding="utf-8",
    )

    assert dedupe_env_file(env_file) == ["ADMIN_REQUIRE_TOKEN"]
    assert env_file.read_text(encoding="utf-8") == (
        "# ADMIN_REQUIRE_TOKEN=false\n\n"
        "# ADMIN_REQUIRE_TOKEN=false\nADMIN_REQUIRE_TOKEN=false\n"
    )


def test_export_prefix_is_supported(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("export A=1\nA=2\n", encoding="utf-8")

    assert dedupe_env_file(env_file) == ["A"]
    assert env_file.read_text(encoding="utf-8") == "A=2\n"


def test_file_mode_is_preserved(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\nA=2\n", encoding="utf-8")
    os.chmod(env_file, 0o600)

    dedupe_env_file(env_file)

    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_second_run_is_idempotent(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_bytes(b"A=1\n# keep\nA=2\n")

    assert dedupe_env_file(env_file) == ["A"]
    first = env_file.read_bytes()
    assert dedupe_env_file(env_file) == []
    assert env_file.read_bytes() == first


def test_missing_file_is_noop(tmp_path):
    missing = tmp_path / ".env"

    assert dedupe_env_file(missing) == []
    assert not missing.exists()


def test_install_wires_dedupe_before_services():
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    dedupe_pos = install.index("scripts/dedupe_env.py")
    pytest_pos = install.index("python3 -m pytest")
    service_pos = install.index("sudo systemctl daemon-reload", dedupe_pos)

    assert dedupe_pos < pytest_pos
    assert dedupe_pos < service_pos
    assert '"$VENV/bin/python3" "$TARGET/scripts/dedupe_env.py"' in install
