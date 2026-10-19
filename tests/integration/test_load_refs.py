"""Reference upserts are idempotent and return stable ids."""

from tests.schema.conftest import fetch

from ec2_scraping import load


def test_each_reference_upsert_is_idempotent(conn, db):
    account = load.upsert_account(conn, "111111111111")
    region = load.upsert_region(conn, "us-east-1")
    az = load.upsert_availability_zone(conn, region, "us-east-1a")
    itype = load.upsert_instance_type(conn, "t3.micro", 2, 1024, "x86_64")
    key = load.upsert_key_pair(conn, account, region, "k")
    profile = load.upsert_iam_instance_profile(conn, account, region, "arn:x")
    vpc = load.upsert_vpc(conn, account, region, "vpc-1", "10.0.0.0/16")
    subnet = load.upsert_subnet(conn, vpc, az, "subnet-1", "10.0.0.0/24")
    sg = load.upsert_security_group(conn, vpc, "sg-1", "web")

    assert account == load.upsert_account(conn, "111111111111")
    assert region == load.upsert_region(conn, "us-east-1")
    assert az == load.upsert_availability_zone(conn, region, "us-east-1a")
    assert itype == load.upsert_instance_type(conn, "t3.micro")
    assert key == load.upsert_key_pair(conn, account, region, "k")
    assert profile == load.upsert_iam_instance_profile(conn, account, region, "arn:x")
    assert vpc == load.upsert_vpc(conn, account, region, "vpc-1")
    assert subnet == load.upsert_subnet(conn, vpc, az, "subnet-1")
    assert sg == load.upsert_security_group(conn, vpc, "sg-1")
    conn.commit()

    for table in ("account", "region", "instance_type", "vpc", "subnet", "security_group"):
        assert fetch(db, f"SELECT COUNT(*) AS n FROM {table}")[0]["n"] == 1


def test_later_upsert_without_details_keeps_existing_details(conn, db):
    load.upsert_instance_type(conn, "t3.micro", 2, 1024, "x86_64")
    load.upsert_instance_type(conn, "t3.micro")
    conn.commit()
    row = fetch(db, "SELECT vcpu, memory_mib, architecture FROM instance_type")[0]
    assert row == {"vcpu": 2, "memory_mib": 1024, "architecture": "x86_64"}
