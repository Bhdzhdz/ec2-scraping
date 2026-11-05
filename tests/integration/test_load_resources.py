"""Single-table instance upserts: analytics attributes, JSON, enrichments, idempotency."""

import dataclasses
import json

from tests.integration.helpers import collected, make_ami, make_instance
from tests.schema.conftest import fetch, insert

from ec2_scraping import load
from ec2_scraping.models import EnrichmentResult


def do_load(conn, data, enrichments=None):
    counts = load.load_instances(conn, "111111111111", "us-east-1", data, enrichments)
    conn.commit()
    return counts


def test_stores_all_instance_ami_and_enrichment_attributes_on_single_row(conn, db):
    enrichments = {
        "i-1": {
            "ssh": EnrichmentResult(
                status="succeeded",
                facts={
                    "ssh_user": "ubuntu",
                    "ssh_host": "10.0.0.1",
                    "ssh_port": 22,
                    "os_id": "ubuntu",
                    "os_version": "24.04",
                    "os_pretty_name": "Ubuntu 24.04 LTS",
                    "kernel": "6.8.0",
                },
            ),
            "ssm": EnrichmentResult(status="skipped", error="not managed"),
        }
    }
    ic = do_load(conn, collected(make_instance(), amis=(make_ami(),)), enrichments)
    assert ic.created == 1

    inst = fetch(db, "SELECT * FROM instance")[0]
    assert inst["aws_account_id"] == "111111111111"
    assert inst["region"] == "us-east-1"
    assert inst["instance_id"] == "i-1"
    assert inst["name"] == "web"
    assert inst["instance_type"] == "t3.micro"
    assert inst["instance_family"] == "t3"
    assert inst["vcpu"] == 2
    assert inst["memory_mib"] == 1024
    assert inst["state"] == "running"
    assert inst["image_id"] == "ami-1"
    assert inst["private_ip"] == "10.0.0.1"
    assert inst["vpc_id"] == "vpc-1"
    assert inst["vpc_cidr"] == "10.0.0.0/16"
    assert inst["subnet_id"] == "subnet-1"
    assert inst["subnet_cidr"] == "10.0.0.0/24"
    assert inst["key_name"] == "key"
    assert inst["iam_instance_profile_arn"] == "arn:aws:iam::111111111111:instance-profile/p"
    assert inst["iam_instance_profile_name"] == "p"
    assert inst["root_volume_id"] == "vol-1"
    assert inst["root_volume_size_gib"] == 20
    assert inst["ebs_volume_count"] == 1
    assert inst["ebs_total_size_gib"] == 20
    assert inst["ebs_all_encrypted"] == 1
    assert inst["eni_count"] == 1
    assert inst["security_group_count"] == 2
    assert inst["ami_name"] == "base"
    assert inst["ami_owner_aws_account_id"] == "111111111111"
    assert inst["ami_state"] == "available"
    assert json.loads(inst["tags"]) == {"Name": "web", "env": "dev"}
    assert inst["ssh_user"] == "ubuntu"
    assert inst["ssh_os_id"] == "ubuntu"
    assert inst["ssh_os_version"] == "24.04"
    assert inst["ssh_os_pretty_name"] == "Ubuntu 24.04 LTS"
    assert inst["ssh_kernel"] == "6.8.0"
    assert inst["ssh_status"] == "succeeded"
    assert json.loads(inst["extra_facts"])["ssm"]["status"] == "skipped"

    view_row = fetch(db, "SELECT * FROM v_instance_analytics")[0]
    assert view_row["is_imdsv2_enforced"] == 1
    assert view_row["is_ssh_accessible"] == 1
    assert view_row["instance_age_days"] is not None


def test_reload_is_idempotent_and_advances_last_seen(conn, db):
    data = collected(make_instance(), amis=(make_ami(),))
    do_load(conn, data)
    insert(db, "UPDATE instance SET last_seen_at = '2020-01-01 00:00:00'")
    before = fetch(db, "SELECT first_seen_at FROM instance")[0]

    ic = do_load(conn, data)
    assert (ic.unchanged, ic.updated, ic.created) == (1, 0, 0)
    after = fetch(db, "SELECT * FROM instance")[0]
    assert fetch(db, "SELECT COUNT(*) AS n FROM instance")[0]["n"] == 1
    assert after["first_seen_at"] == before["first_seen_at"]
    assert after["last_seen_at"].year > 2020


def test_changed_attribute_counts_as_updated(conn, db):
    do_load(conn, collected(make_instance(), amis=(make_ami(),)))

    updated_inst = make_instance(state="stopped", name="web-2")
    ic = do_load(conn, collected(updated_inst, amis=(make_ami(name="base-2"),)))
    assert ic.updated == 1
    row = fetch(db, "SELECT state, name, ami_name FROM instance")[0]
    assert row == {"state": "stopped", "name": "web-2", "ami_name": "base-2"}


def test_instance_with_unknown_ami_is_stored(conn, db):
    inst = dataclasses.replace(make_instance(), image_id="ami-unknown")
    ic = do_load(conn, collected(inst))
    assert ic.created == 1
    row = fetch(db, "SELECT image_id, ami_name, ami_state FROM instance")[0]
    assert row == {"image_id": "ami-unknown", "ami_name": None, "ami_state": None}


def test_instance_without_optional_attributes(conn, db):
    bare = make_instance(
        name=None,
        vpc_id=None,
        subnet_id=None,
        key_name=None,
        iam_profile_arn=None,
        private_ip=None,
        volumes=[],
        security_groups=[],
        network_interfaces=[],
        tags={},
    )
    ic = do_load(conn, collected(bare))
    row = fetch(
        db,
        "SELECT name, vpc_id, vpc_cidr, subnet_id, subnet_cidr, key_name, iam_instance_profile_arn"
        " FROM instance",
    )[0]
    assert ic.created == 1
    assert set(row.values()) == {None}
