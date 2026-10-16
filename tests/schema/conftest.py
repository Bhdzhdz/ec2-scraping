"""Fixtures that apply db/migrations to a disposable MariaDB/MySQL database."""

import os
import re
from pathlib import Path
from urllib.parse import urlparse

import pymysql
import pymysql.cursors
import pytest

MIGRATIONS = sorted((Path(__file__).parents[2] / "db" / "migrations").glob("*.sql"))


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


def apply_migrations(conn) -> None:
    for path in MIGRATIONS:
        sql = re.sub(r"^\s*--.*$", "", path.read_text(), flags=re.M)
        with conn.cursor() as cur:
            for stmt in filter(None, (s.strip() for s in sql.split(";"))):
                cur.execute(stmt)


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
    conn = _connect(dsn, name)
    apply_migrations(conn)
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


@pytest.fixture
def ref(db) -> dict:
    """Minimal reference rows shared by instance/AMI tests."""
    account = insert(db, "INSERT INTO account (aws_account_id) VALUES ('111111111111')")
    region = insert(db, "INSERT INTO region (code) VALUES ('us-east-1')")
    az = insert(
        db, "INSERT INTO availability_zone (region_id, name) VALUES (%s, 'us-east-1a')", (region,)
    )
    itype = insert(db, "INSERT INTO instance_type (name) VALUES ('t3.micro')")
    vpc = insert(
        db,
        "INSERT INTO vpc (account_id, region_id, vpc_id) VALUES (%s, %s, 'vpc-1')",
        (account, region),
    )
    subnet = insert(
        db,
        "INSERT INTO subnet (vpc_pk, availability_zone_id, subnet_id) VALUES (%s, %s, 'subnet-1')",
        (vpc, az),
    )
    sg = insert(db, "INSERT INTO security_group (vpc_pk, group_id) VALUES (%s, 'sg-1')", (vpc,))
    return dict(account=account, region=region, az=az, itype=itype, vpc=vpc, subnet=subnet, sg=sg)


def add_instance(
    conn, ref: dict, instance_id: str = "i-1", image_id: str = "ami-1", **extra
) -> int:
    cols = dict(
        account_id=ref["account"],
        region_id=ref["region"],
        instance_id=instance_id,
        instance_type_id=ref["itype"],
        availability_zone_id=ref["az"],
        image_id=image_id,
        state="running",
        architecture="x86_64",
        launch_time="2026-01-01 00:00:00",
    )
    cols.update(extra)
    names = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    return insert(conn, f"INSERT INTO instance ({names}) VALUES ({marks})", tuple(cols.values()))


def add_ami(conn, ref: dict, image_id: str = "ami-1", **extra) -> int:
    cols = dict(
        account_id=ref["account"],
        region_id=ref["region"],
        image_id=image_id,
        owner_aws_account_id="111111111111",
        state="available",
        architecture="x86_64",
        root_device_type="ebs",
        virtualization_type="hvm",
    )
    cols.update(extra)
    names = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    return insert(conn, f"INSERT INTO ami ({names}) VALUES ({marks})", tuple(cols.values()))
