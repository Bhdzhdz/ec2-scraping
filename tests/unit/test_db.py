"""DSN parsing and SQLite fallback when MariaDB is unset or unreachable."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from ec2_scraping import load
from ec2_scraping.db import ConfigError, connect, parse_dsn
from ec2_scraping.models import Collected, InstanceRecord

if TYPE_CHECKING:
    from pathlib import Path


def test_parse_dsn() -> None:
    parsed = parse_dsn("mysql://user:p%40ss@db.example:3307/inventory")
    assert parsed == {
        "host": "db.example",
        "port": 3307,
        "user": "user",
        "password": "p@ss",
        "database": "inventory",
    }


def test_parse_sqlite_dsn() -> None:
    assert parse_dsn("sqlite:///tmp/test.db") == {"scheme": "sqlite", "database": "tmp/test.db"}
    assert parse_dsn("sqlite:///:memory:") == {"scheme": "sqlite", "database": ":memory:"}


def test_default_port() -> None:
    assert parse_dsn("mysql://u:p@h/d")["port"] == 3306


@pytest.mark.parametrize("bad", ["", "postgres://u@h/d", "mysql://u@h", "mysql:///d"])
def test_bad_dsn_rejected(bad: str) -> None:
    with pytest.raises(ConfigError):
        parse_dsn(bad)


def test_defaults_to_sqlite_when_mariadb_env_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("MARIADB_DSN", raising=False)
    sqlite_dsn = f"sqlite:///{tmp_path / 'fallback.db'}"
    session = connect(fallback_dsn=sqlite_dsn)
    try:
        assert session.bind is not None
        assert session.bind.dialect.name == "sqlite"
        data = Collected(
            instances=[
                InstanceRecord(
                    instance_id="i-sqlite",
                    instance_type="t3.micro",
                    availability_zone="us-east-1a",
                    image_id="ami-1",
                    state="running",
                    architecture="x86_64",
                    launch_time=datetime(2026, 1, 1),
                    public_ip="1.2.3.4",
                    imds_http_tokens="required",
                )
            ]
        )
        counts = load.load_instances(session, "111111111111", "us-east-1", data)
        session.commit()
        assert counts.created == 1
        row = session.execute(
            text("SELECT instance_id, has_public_ip, is_imdsv2_enforced FROM v_instance_analytics")
        ).one()
        assert tuple(row) == ("i-sqlite", 1, 1)
    finally:
        session.close()


def test_falls_back_to_sqlite_when_mariadb_unreachable(tmp_path: Path) -> None:
    sqlite_dsn = f"sqlite:///{tmp_path / 'unreachable_fallback.db'}"
    # Port 1 on 127.0.0.1 refuses TCP connections immediately
    session = connect("mysql://u:p@127.0.0.1:1/inv", fallback_dsn=sqlite_dsn)
    try:
        assert session.bind is not None
        assert session.bind.dialect.name == "sqlite"
    finally:
        session.close()
