"""Instance/AMI upserts: attributes, idempotency, change detection, child replacement."""

import dataclasses

from tests.integration.helpers import collected, make_ami, make_instance
from tests.schema.conftest import fetch, insert

from ec2_scraping import load


def new_run(db) -> int:
    return insert(db, "INSERT INTO scrape_run () VALUES ()")


def do_load(conn, data, run_id):
    account = load.upsert_account(conn, "111111111111")
    region = load.upsert_region(conn, "us-east-1")
    ctx = load.LoadContext(conn, run_id, account, region)
    counts = load.load_instances(ctx, data), load.load_amis(ctx, data)
    conn.commit()
    return counts


def test_stores_all_instance_and_ami_attributes(conn, db):
    run = new_run(db)
    ic, ac = do_load(conn, collected(make_instance(), amis=(make_ami(),)), run)
    assert (ic.created, ac.created) == (1, 1)

    inst = fetch(db, "SELECT * FROM instance")[0]
    assert inst["state"] == "running"
    assert inst["image_id"] == "ami-1"
    assert inst["private_ip"] == "10.0.0.1"
    assert inst["last_scrape_run_id"] == run
    assert inst["subnet_pk"]
    assert inst["key_pair_id"]
    assert inst["iam_instance_profile_id"]
    assert fetch(db, "SELECT cidr FROM vpc")[0]["cidr"] == "10.0.0.0/16"
    assert fetch(db, "SELECT cidr FROM subnet")[0]["cidr"] == "10.0.0.0/24"
    assert {r["tag_key"] for r in fetch(db, "SELECT tag_key FROM instance_tag")} == {"Name", "env"}
    assert fetch(db, "SELECT COUNT(*) AS n FROM instance_security_group")[0]["n"] == 2
    assert fetch(db, "SELECT volume_id FROM instance_volume") == [{"volume_id": "vol-1"}]
    assert fetch(db, "SELECT eni_id FROM instance_network_interface") == [{"eni_id": "eni-1"}]

    ami = fetch(db, "SELECT * FROM ami")[0]
    assert ami["name"] == "base"
    assert ami["owner_aws_account_id"] == "111111111111"
    assert fetch(db, "SELECT COUNT(*) AS n FROM ami_tag")[0]["n"] == 2
    assert fetch(db, "SELECT snapshot_id FROM ami_block_device_mapping") == [
        {"snapshot_id": "snap-1"}
    ]


def test_reload_is_idempotent_and_advances_last_seen(conn, db):
    data = collected(make_instance(), amis=(make_ami(),))
    run1, run2 = new_run(db), new_run(db)
    do_load(conn, data, run1)
    insert(db, "UPDATE instance SET last_seen_at = '2020-01-01 00:00:00'")
    before = fetch(db, "SELECT first_seen_at FROM instance")[0]

    ic, ac = do_load(conn, data, run2)
    assert (ic.unchanged, ic.updated, ic.created) == (1, 0, 0)
    assert (ac.unchanged, ac.updated, ac.created) == (1, 0, 0)
    after = fetch(db, "SELECT * FROM instance")[0]
    assert fetch(db, "SELECT COUNT(*) AS n FROM instance")[0]["n"] == 1
    assert after["first_seen_at"] == before["first_seen_at"]
    assert after["last_seen_at"].year > 2020
    assert after["last_scrape_run_id"] == run2
    assert fetch(db, "SELECT last_scrape_run_id FROM ami")[0]["last_scrape_run_id"] == run2


def test_removed_children_disappear_and_change_counts_as_updated(conn, db):
    run1, run2 = new_run(db), new_run(db)
    do_load(conn, collected(make_instance(), amis=(make_ami(),)), run1)

    smaller = make_instance(
        state="stopped",
        tags={"Name": "web"},
        security_groups=[("sg-1", "web")],
        volumes=[],
        network_interfaces=[],
    )
    ic, ac = do_load(
        conn, collected(smaller, amis=(make_ami(tags={"team": "a"}, block_mappings=[]),)), run2
    )
    assert (ic.updated, ac.updated) == (1, 1)
    assert fetch(db, "SELECT state FROM instance")[0]["state"] == "stopped"
    assert fetch(db, "SELECT tag_key FROM instance_tag") == [{"tag_key": "Name"}]
    assert fetch(db, "SELECT COUNT(*) AS n FROM instance_security_group")[0]["n"] == 1
    assert fetch(db, "SELECT COUNT(*) AS n FROM instance_volume")[0]["n"] == 0
    assert fetch(db, "SELECT COUNT(*) AS n FROM instance_network_interface")[0]["n"] == 0
    assert fetch(db, "SELECT tag_key FROM ami_tag") == [{"tag_key": "team"}]
    assert fetch(db, "SELECT COUNT(*) AS n FROM ami_block_device_mapping")[0]["n"] == 0


def test_instance_with_unknown_ami_is_stored(conn, db):
    inst = dataclasses.replace(make_instance(), image_id="ami-unknown")
    ic, _ = do_load(conn, collected(inst), new_run(db))
    assert ic.created == 1
    assert fetch(db, "SELECT COUNT(*) AS n FROM ami")[0]["n"] == 0


def test_instance_without_optional_attributes(conn, db):
    bare = make_instance(
        vpc_id=None,
        subnet_id=None,
        key_name=None,
        iam_profile_arn=None,
        private_ip=None,
        tags={},
        security_groups=[],
        volumes=[],
        network_interfaces=[],
    )
    ic, _ = do_load(conn, collected(bare), new_run(db))
    row = fetch(db, "SELECT subnet_pk, key_pair_id, iam_instance_profile_id FROM instance")[0]
    assert ic.created == 1
    assert set(row.values()) == {None}
