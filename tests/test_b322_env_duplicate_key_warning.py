"""
B322: config.py warnt beim Start, wenn .env doppelt definierte Schluessel enthaelt
(python-dotenv wertet sonst stillschweigend nach "last-wins" aus).
"""
import importlib
import sys

import pytest

config = pytest.importorskip("config")


def test_no_warning_for_clean_env_file(tmp_path, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=1\nBAR=2\n", encoding="utf-8")
    result = config._warn_duplicate_env_keys(str(env_file))
    assert result == []


def test_warns_for_duplicate_keys(tmp_path, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ADMIN_API_TOKEN=aaa\nADMIN_API_TOKEN=bbb\nADMIN_API_TOKEN=ccc\n"
        "ADMIN_REQUIRE_TOKEN=true\nADMIN_REQUIRE_TOKEN=false\n"
        "OTHER_KEY=1\n",
        encoding="utf-8",
    )
    result = config._warn_duplicate_env_keys(str(env_file))
    assert result == ["ADMIN_API_TOKEN", "ADMIN_REQUIRE_TOKEN"]
    captured = capsys.readouterr()
    assert "ADMIN_API_TOKEN" in captured.out
    assert "ADMIN_REQUIRE_TOKEN" in captured.out


def test_ignores_comments_and_blank_lines(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# ADMIN_API_TOKEN=commented_out\n\nADMIN_API_TOKEN=aaa\n",
        encoding="utf-8",
    )
    result = config._warn_duplicate_env_keys(str(env_file))
    assert result == []


def test_missing_file_returns_empty_list(tmp_path):
    result = config._warn_duplicate_env_keys(str(tmp_path / "does_not_exist.env"))
    assert result == []


def test_never_raises_on_unreadable_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_bytes(b"\xff\xfe\x00garbage")
    # Darf nicht crashen, auch bei kaputtem/binaerem Inhalt.
    result = config._warn_duplicate_env_keys(str(env_file))
    assert isinstance(result, list)
