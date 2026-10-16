import pymysql
import pytest

from .conftest import add_ami, add_instance, fetch, insert


def test_round_trip_and_duplicate(db, ref):
    pk = add_ami(
        db,
        ref,
        name="n",
        description="d",
        creation_date="2026-01-01",
        platform="windows",
        is_public=1,
        deprecation_time="2027-01-01",
    )
    row = fetch(db, "SELECT * FROM ami WHERE id = %s", (pk,))[0]
    assert row["name"] == "n" and row["is_public"] == 1 and row["platform"] == "windows"
    assert row["owner_aws_account_id"] == "111111111111" and row["root_device_type"] == "ebs"
    assert row["virtualization_type"] == "hvm" and row["deprecation_time"] is not None
    assert (
        fetch(db, "SELECT deprecation_time FROM ami WHERE id=%s", (add_ami(db, ref, "ami-2"),))[0][
            "deprecation_time"
        ]
        is None
    )
    with pytest.raises(pymysql.err.IntegrityError):
        add_ami(db, ref)


def test_children_cascade(db, ref):
    pk = add_ami(db, ref)
    insert(
        db,
        "INSERT INTO ami_block_device_mapping (ami_pk, device_name, snapshot_id, size_gib) VALUES (%s, '/dev/sda1', 'snap-1', 8)",
        (pk,),
    )
    insert(db, "INSERT INTO ami_tag VALUES (%s, 'k', 'v')", (pk,))
    insert(db, "DELETE FROM ami WHERE id = %s", (pk,))
    assert fetch(db, "SELECT COUNT(*) AS n FROM ami_block_device_mapping")[0]["n"] == 0
    assert fetch(db, "SELECT COUNT(*) AS n FROM ami_tag")[0]["n"] == 0


JOIN = (
    "SELECT i.instance_id FROM instance i JOIN ami a"
    " ON a.region_id = i.region_id AND a.image_id = i.image_id WHERE a.image_id = %s"
)


def test_soft_link_resolves_after_ami_discovered(db, ref):
    add_instance(db, ref, image_id="ami-x")  # AMI not yet known: must still insert
    assert fetch(db, JOIN, ("ami-x",)) == []
    add_ami(db, ref, "ami-x")
    assert fetch(db, JOIN, ("ami-x",)) == [{"instance_id": "i-1"}]
    add_ami(db, ref, "ami-unused")
    unused = fetch(
        db,
        "SELECT a.image_id FROM ami a LEFT JOIN instance i"
        " ON i.region_id = a.region_id AND i.image_id = a.image_id WHERE i.id IS NULL",
    )
    assert unused == [{"image_id": "ami-unused"}]
