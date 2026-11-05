"""Offline unit tests for SQLAlchemy 2.0 ORM models and Alembic migrations (no DB needed)."""

import io
from contextlib import redirect_stdout

import pytest
from alembic import command
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable, UniqueConstraint

from ec2_scraping.db import (
    Base,
    Instance,
    make_alembic_config,
    make_engine,
    make_session_factory,
    normalize_dsn,
    upgrade_db,
)

EXPECTED_TABLES = {"instance"}


def test_single_table_registered_with_innodb_utf8mb4():
    assert set(Base.metadata.tables) == EXPECTED_TABLES
    table = Base.metadata.tables["instance"]
    assert table.dialect_options["mysql"]["engine"] == "InnoDB"
    assert table.dialect_options["mysql"]["charset"] == "utf8mb4"
    ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
    assert "ENGINE=InnoDB" in ddl
    assert "CHARSET=utf8mb4" in ddl
    for col in (
        "instance_family",
        "gpu_count",
        "ebs_total_size_gib",
        "imds_http_tokens",
        "tags",
        "volumes",
        "ssh_facts",
        "extra_facts",
    ):
        assert col in table.c


def test_instance_table_indexes_and_no_foreign_keys():
    instance_table = Base.metadata.tables["instance"]
    assert not instance_table.foreign_keys
    index_cols = {idx.name: tuple(c.name for c in idx.columns) for idx in instance_table.indexes}
    assert index_cols["ix_instance_image"] == ("region", "image_id")
    assert index_cols["ix_instance_vpc"] == ("region", "vpc_id")
    assert index_cols["ix_instance_state"] == ("state",)
    assert index_cols["ix_instance_type"] == ("instance_type",)
    assert index_cols["ix_instance_last_seen"] == ("last_seen_at",)


def test_unique_constraint():
    instance_table = Base.metadata.tables["instance"]
    uqs = {
        c.name: tuple(col.name for col in c.columns)
        for c in instance_table.constraints
        if isinstance(c, UniqueConstraint)
    }
    assert uqs == {"uq_instance": ("aws_account_id", "region", "instance_id")}


def test_model_class_instantiable():
    inst = Instance(
        aws_account_id="111111111111",
        region="us-east-1",
        instance_id="i-1",
        name="web",
        instance_type="t3.micro",
        instance_family="t3",
        vcpu=2,
        memory_mib=1024,
        availability_zone="us-east-1a",
        image_id="ami-1",
        state="running",
        architecture="x86_64",
        tags={"Name": "web"},
        ssh_facts={"kernel": "6.1"},
    )
    assert inst.instance_id == "i-1"
    assert inst.ssh_facts == {"kernel": "6.1"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("mysql://u:p@h:3306/db", "mysql+pymysql://u:p@h:3306/db"),
        ("mariadb://u:p@h:3306/db", "mysql+pymysql://u:p@h:3306/db"),
        ("mysql+pymysql://u:p@h:3306/db", "mysql+pymysql://u:p@h:3306/db"),
    ],
)
def test_session_and_dsn_helpers(raw, expected):
    assert normalize_dsn(raw) == expected
    engine = make_engine(raw)
    factory = make_session_factory(engine)
    factory_from_dsn = make_session_factory(raw)
    assert factory.kw["bind"] is engine
    assert factory_from_dsn.kw["bind"].url.drivername == "mysql+pymysql"


def test_offline_alembic_upgrade_and_downgrade_sql():
    buf = io.StringIO()
    with redirect_stdout(buf):
        upgrade_db("mysql://u:p@localhost:3306/inv", "head", sql=True)
    sql_up = buf.getvalue()
    assert "CREATE TABLE IF NOT EXISTS instance" in sql_up
    assert "CREATE OR REPLACE VIEW v_instance_analytics" in sql_up

    cfg = make_alembic_config("mysql://u:p@localhost:3306/inv")
    buf_down = io.StringIO()
    with redirect_stdout(buf_down):
        command.downgrade(cfg, "0001_initial_schema:base", sql=True)
    sql_down = buf_down.getvalue()
    assert "DROP VIEW IF EXISTS v_instance_analytics" in sql_down
    assert "DROP TABLE IF EXISTS instance" in sql_down
