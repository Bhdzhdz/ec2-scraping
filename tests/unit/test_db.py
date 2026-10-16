"""DSN parsing and environment fallback."""

import pytest

from ec2_scraping.db import ConfigError, connect, parse_dsn


def test_parse_dsn():
    parsed = parse_dsn("mysql://user:p%40ss@db.example:3307/inventory")
    assert parsed == {
        "host": "db.example",
        "port": 3307,
        "user": "user",
        "password": "p@ss",
        "database": "inventory",
    }


def test_default_port():
    assert parse_dsn("mysql://u:p@h/d")["port"] == 3306


@pytest.mark.parametrize("bad", ["", "postgres://u@h/d", "mysql://u@h", "mysql:///d"])
def test_bad_dsn_rejected(bad):
    with pytest.raises(ConfigError):
        parse_dsn(bad)


def test_dsn_comes_from_env_not_code(monkeypatch):
    monkeypatch.delenv("MARIADB_DSN", raising=False)
    with pytest.raises(ConfigError, match="MARIADB_DSN"):
        connect()
