import pymysql
import pytest

from .conftest import add_instance, fetch, insert


def test_round_trip_all_attributes(db):
    pk = add_instance(
        db,
        name="web",
        vcpu=2,
        memory_mib=1024,
        vpc_id="vpc-1",
        vpc_cidr="10.0.0.0/16",
        subnet_id="subnet-1",
        subnet_cidr="10.0.0.0/24",
        key_name="k",
        iam_instance_profile_arn="arn:p",
        platform="windows",
        private_ip="10.0.0.1",
        public_ip="1.2.3.4",
        monitoring="enabled",
        ami_owner_aws_account_id="111111111111",
        ami_name="base",
        ami_description="desc",
        ami_creation_date="2026-01-01 00:00:00",
        ami_state="available",
        ami_architecture="x86_64",
        ami_platform="windows",
        ami_root_device_type="ebs",
        ami_virtualization_type="hvm",
        ami_is_public=1,
        ami_deprecation_time="2027-01-01 00:00:00",
    )
    row = fetch(db, "SELECT * FROM instance WHERE id = %s", (pk,))[0]
    assert row["name"] == "web"
    assert row["vcpu"] == 2 and row["memory_mib"] == 1024
    assert row["vpc_id"] == "vpc-1" and row["vpc_cidr"] == "10.0.0.0/16"
    assert row["subnet_id"] == "subnet-1" and row["subnet_cidr"] == "10.0.0.0/24"
    assert row["state"] == "running" and row["architecture"] == "x86_64"
    assert row["platform"] == "windows" and row["monitoring"] == "enabled"
    assert row["private_ip"] == "10.0.0.1" and row["public_ip"] == "1.2.3.4"
    assert row["key_name"] == "k" and row["iam_instance_profile_arn"] == "arn:p"
    assert row["image_id"] == "ami-1" and row["ami_name"] == "base"
    assert row["ami_owner_aws_account_id"] == "111111111111" and row["ami_is_public"] == 1


def test_optional_fields_nullable(db):
    pk = add_instance(db)
    row = fetch(db, "SELECT * FROM instance WHERE id = %s", (pk,))[0]
    for col in (
        "name",
        "vcpu",
        "memory_mib",
        "vpc_id",
        "vpc_cidr",
        "subnet_id",
        "subnet_cidr",
        "key_name",
        "iam_instance_profile_arn",
        "public_ip",
        "platform",
        "ami_owner_aws_account_id",
        "ami_name",
        "ami_state",
    ):
        assert row[col] is None


def test_duplicate_rejected_and_upsert_in_place(db):
    add_instance(db)
    with pytest.raises(pymysql.err.IntegrityError):
        add_instance(db)
    insert(
        db,
        "INSERT INTO instance (aws_account_id, region, instance_id, instance_type,"
        " availability_zone, image_id, state, architecture, launch_time)"
        " VALUES ('111111111111', 'us-east-1', 'i-1', 't3.micro', 'us-east-1a',"
        " 'ami-1', 'stopped', 'x86_64', '2026-01-01')"
        " ON DUPLICATE KEY UPDATE state = VALUES(state)",
    )
    rows = fetch(db, "SELECT state FROM instance")
    assert rows == [{"state": "stopped"}]
