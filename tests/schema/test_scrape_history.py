from .conftest import add_ami, add_instance, fetch, insert


def test_missing_in_latest_run(db, ref):
    run1 = insert(db, "INSERT INTO scrape_run () VALUES ()")
    run2 = insert(db, "INSERT INTO scrape_run () VALUES ()")
    gone = add_instance(db, ref, "i-gone", last_scrape_run_id=run1)
    add_instance(db, ref, "i-kept", last_scrape_run_id=run1)
    add_ami(db, ref, "ami-gone", last_scrape_run_id=run1)
    first_seen = fetch(db, "SELECT first_seen_at FROM instance WHERE id=%s", (gone,))[0]
    insert(
        db,
        "UPDATE instance SET last_scrape_run_id=%s, last_seen_at=NOW() WHERE instance_id='i-kept'",
        (run2,),
    )
    missing = fetch(db, "SELECT instance_id FROM instance WHERE last_scrape_run_id <> %s", (run2,))
    assert missing == [{"instance_id": "i-gone"}]
    assert fetch(db, "SELECT image_id FROM ami WHERE last_scrape_run_id <> %s", (run2,)) == [
        {"image_id": "ami-gone"}
    ]
    assert fetch(db, "SELECT first_seen_at FROM instance WHERE id=%s", (gone,))[0] == first_seen


def test_scope_status_column_defaults_and_is_rerunnable(db, dsn, ref):
    from .conftest import apply_migrations

    run = insert(db, "INSERT INTO scrape_run () VALUES ()")
    insert(
        db,
        "INSERT INTO scrape_run_scope (scrape_run_id, account_id, region_id) VALUES (%s, %s, %s)",
        (run, ref["account"], ref["region"]),
    )
    apply_migrations(dsn)  # 0002 must be re-runnable without error
    row = fetch(db, "SELECT status, error FROM scrape_run_scope WHERE scrape_run_id=%s", (run,))
    assert row == [{"status": "succeeded", "error": None}]
