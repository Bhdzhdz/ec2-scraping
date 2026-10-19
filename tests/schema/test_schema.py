import pymysql
import pytest

from .conftest import apply_migrations, insert


def test_migrations_apply_twice(db, dsn):
    apply_migrations(dsn)  # second application must not fail (SC-001, FR-013)


def test_reference_unique_keys(db):
    insert(db, "INSERT INTO account (aws_account_id) VALUES ('111111111111')")
    with pytest.raises(pymysql.err.IntegrityError):
        insert(db, "INSERT INTO account (aws_account_id) VALUES ('111111111111')")
    region = insert(db, "INSERT INTO region (code) VALUES ('us-east-1')")
    insert(db, "INSERT INTO availability_zone (region_id, name) VALUES (%s, 'a')", (region,))
    with pytest.raises(pymysql.err.IntegrityError):
        insert(db, "INSERT INTO availability_zone (region_id, name) VALUES (%s, 'a')", (region,))


def test_scope_cascades_on_run_delete(db, ref):
    run = insert(db, "INSERT INTO scrape_run () VALUES ()")
    insert(
        db,
        "INSERT INTO scrape_run_scope (scrape_run_id, account_id, region_id) VALUES (%s, %s, %s)",
        (run, ref["account"], ref["region"]),
    )
    insert(db, "DELETE FROM scrape_run WHERE id = %s", (run,))
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM scrape_run_scope")
        assert cur.fetchone()["n"] == 0
