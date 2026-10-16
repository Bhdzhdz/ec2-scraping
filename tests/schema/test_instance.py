import pymysql
import pytest

from .conftest import add_instance, fetch, insert


def test_round_trip_all_attributes(db, ref):
    key = insert(
        db,
        "INSERT INTO key_pair (account_id, region_id, name) VALUES (%s, %s, 'k')",
        (ref["account"], ref["region"]),
    )
    prof = insert(
        db,
        "INSERT INTO iam_instance_profile (account_id, region_id, arn) VALUES (%s, %s, 'arn:p')",
        (ref["account"], ref["region"]),
    )
    pk = add_instance(
        db,
        ref,
        subnet_pk=ref["subnet"],
        key_pair_id=key,
        iam_instance_profile_id=prof,
        platform="windows",
        private_ip="10.0.0.1",
        public_ip="1.2.3.4",
        monitoring="enabled",
    )
    row = fetch(db, "SELECT * FROM instance WHERE id = %s", (pk,))[0]
    assert row["state"] == "running" and row["architecture"] == "x86_64"
    assert row["platform"] == "windows" and row["monitoring"] == "enabled"
    assert row["private_ip"] == "10.0.0.1" and row["public_ip"] == "1.2.3.4"
    assert row["key_pair_id"] == key and row["iam_instance_profile_id"] == prof
    assert row["subnet_pk"] == ref["subnet"] and row["image_id"] == "ami-1"


def test_optional_fields_nullable(db, ref):
    pk = add_instance(db, ref)
    row = fetch(db, "SELECT * FROM instance WHERE id = %s", (pk,))[0]
    for col in ("key_pair_id", "iam_instance_profile_id", "public_ip", "platform", "subnet_pk"):
        assert row[col] is None


def test_duplicate_rejected_and_upsert_in_place(db, ref):
    add_instance(db, ref)
    with pytest.raises(pymysql.err.IntegrityError):
        add_instance(db, ref)
    insert(
        db,
        "INSERT INTO instance (account_id, region_id, instance_id, instance_type_id,"
        " availability_zone_id, image_id, state, architecture, launch_time)"
        " VALUES (%s, %s, 'i-1', %s, %s, 'ami-1', 'stopped', 'x86_64', '2026-01-01')"
        " ON DUPLICATE KEY UPDATE state = VALUES(state)",
        (ref["account"], ref["region"], ref["itype"], ref["az"]),
    )
    rows = fetch(db, "SELECT state FROM instance")
    assert rows == [{"state": "stopped"}]


def test_tags_and_cascade(db, ref):
    pk = add_instance(db, ref)
    insert(db, "INSERT INTO instance_tag VALUES (%s, 'Env', 'prod')", (pk,))
    insert(db, "INSERT INTO instance_tag VALUES (%s, 'Team', 'a')", (pk,))
    insert(db, "INSERT INTO instance_security_group VALUES (%s, %s)", (pk, ref["sg"]))
    insert(
        db,
        "INSERT INTO instance_volume (instance_pk, device_name, volume_id, size_gib) VALUES (%s, '/dev/sda1', 'vol-1', 8)",
        (pk,),
    )
    insert(
        db,
        "INSERT INTO instance_network_interface (instance_pk, eni_id) VALUES (%s, 'eni-1')",
        (pk,),
    )
    found = fetch(
        db, "SELECT instance_pk FROM instance_tag WHERE tag_key='Env' AND tag_value='prod'"
    )
    assert found == [{"instance_pk": pk}]
    with pytest.raises(pymysql.err.IntegrityError):
        insert(db, "INSERT INTO instance_tag VALUES (%s, 'Env', 'x')", (pk,))
    insert(db, "DELETE FROM instance WHERE id = %s", (pk,))
    for table in (
        "instance_tag",
        "instance_security_group",
        "instance_volume",
        "instance_network_interface",
    ):
        assert fetch(db, f"SELECT COUNT(*) AS n FROM {table}")[0]["n"] == 0
