import pymysql
import pytest

from .conftest import add_instance, apply_migrations, fetch


def test_migrations_apply_twice(db, dsn):
    apply_migrations(dsn)  # second application must not fail


def test_only_instance_table_and_analytics_view_created(db):
    base_tables = {
        r["TABLE_NAME"]
        for r in fetch(
            db,
            "SELECT TABLE_NAME FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND TABLE_TYPE = 'BASE TABLE' "
            "AND TABLE_NAME != 'alembic_version'",
        )
    }
    views = {
        r["TABLE_NAME"]
        for r in fetch(
            db,
            "SELECT TABLE_NAME FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND TABLE_TYPE = 'VIEW'",
        )
    }
    assert base_tables == {"instance"}
    assert views == {"v_instance_analytics"}


def test_instance_unique_key(db):
    add_instance(db, "i-1")
    with pytest.raises(pymysql.err.IntegrityError):
        add_instance(db, "i-1")
