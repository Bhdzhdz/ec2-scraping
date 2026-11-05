"""Fixtures that apply Alembic migrations to a disposable MariaDB/MySQL database."""

import os
from urllib.parse import urlparse

import pymysql
import pymysql.cursors
import pytest

from ec2_scraping.db.session import upgrade_db


def _connect(dsn: str, database: str | None):
    u = urlparse(dsn)
    return pymysql.connect(
        host=u.hostname,
        port=u.port or 3306,
        user=u.username,
        password=u.password or "",
        database=database,
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def apply_migrations(dsn: str) -> None:
    upgrade_db(dsn, "head")


@pytest.fixture(scope="session")
def dsn() -> str:
    value = os.environ.get("MARIADB_TEST_DSN")
    if not value:
        pytest.skip("MARIADB_TEST_DSN not set")
    return value


@pytest.fixture
def db(dsn):
    name = urlparse(dsn).path.lstrip("/")
    root = _connect(dsn, None)
    with root.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
        cur.execute(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4")
    root.close()
    apply_migrations(dsn)
    conn = _connect(dsn, name)
    yield conn
    conn.close()


def insert(conn, sql: str, args=()) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.lastrowid


def fetch(conn, sql: str, args=()) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return list(cur.fetchall())


def add_instance(
    conn,
    instance_id: str = "i-1",
    image_id: str = "ami-1",
    aws_account_id: str = "111111111111",
    region: str = "us-east-1",
    **extra,
) -> int:
    cols = dict(
        aws_account_id=aws_account_id,
        region=region,
        instance_id=instance_id,
        instance_type="t3.micro",
        availability_zone="us-east-1a",
        image_id=image_id,
        state="running",
        architecture="x86_64",
        launch_time="2026-01-01 00:00:00",
    )
    cols.update(extra)
    names = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    return insert(conn, f"INSERT INTO instance ({names}) VALUES ({marks})", tuple(cols.values()))
