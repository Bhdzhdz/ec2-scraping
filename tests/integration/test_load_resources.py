"""Single-table instance upserts: analytics attributes, JSON, enrichments, idempotency."""

import dataclasses
import json
from typing import TYPE_CHECKING, Any

from tests.integration.helpers import collected, make_ami, make_instance, make_ssh_enrichment
from tests.schema.conftest import fetch, insert

from ec2_scraping import load
from ec2_scraping.models import EnrichmentResult

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ec2_scraping.models import Collected, Counts

_EXPECTED_ROW_FIELDS: dict[str, Any] = {
    "aws_account_id": "111111111111",
    "region": "us-east-1",
    "instance_id": "i-1",
    "name": "web",
    "instance_type": "t3.micro",
    "instance_family": "t3",
    "vcpu": 2,
    "memory_mib": 1024,
    "state": "running",
    "image_id": "ami-1",
    "private_ip": "10.0.0.1",
    "vpc_id": "vpc-1",
    "vpc_cidr": "10.0.0.0/16",
    "subnet_id": "subnet-1",
    "subnet_cidr": "10.0.0.0/24",
    "key_name": "key",
    "iam_instance_profile_arn": "arn:aws:iam::111111111111:instance-profile/p",
    "iam_instance_profile_name": "p",
    "root_volume_id": "vol-1",
    "root_volume_size_gib": 20,
    "ebs_volume_count": 1,
    "ebs_total_size_gib": 20,
    "ebs_all_encrypted": 1,
    "eni_count": 1,
    "security_group_count": 2,
    "ami_name": "base",
    "ami_owner_aws_account_id": "111111111111",
    "ami_state": "available",
    "ssh_user": "ubuntu",
    "ssh_os_id": "ubuntu",
    "ssh_os_version": "24.04",
    "ssh_os_pretty_name": "Ubuntu 24.04 LTS",
    "ssh_kernel": "6.8.0",
    "ssh_status": "succeeded",
}


def do_load(
    conn: Session,
    data: Collected,
    enrichments: dict[str, dict[str, EnrichmentResult]] | None = None,
) -> Counts:
    counts = load.load_instances(conn, "111111111111", "us-east-1", data, enrichments)
    conn.commit()
    return counts


def test_stores_all_instance_ami_and_enrichment_attributes_on_single_row(
    conn: Session, db: Any
) -> None:
    enrichments = {
        "i-1": {
            "ssh": make_ssh_enrichment(),
            "ssm": EnrichmentResult(status="skipped", error="not managed"),
        }
    }
    ic = do_load(conn, collected(make_instance(), amis=(make_ami(),)), enrichments)
    assert ic.created == 1

    inst = fetch(db, "SELECT * FROM instance")[0]
    assert {k: inst[k] for k in _EXPECTED_ROW_FIELDS} == _EXPECTED_ROW_FIELDS
    assert json.loads(inst["tags"]) == {"Name": "web", "env": "dev"}
    assert json.loads(inst["extra_facts"])["ssm"]["status"] == "skipped"

    view_row = fetch(db, "SELECT * FROM v_instance_analytics")[0]
    assert (view_row["is_imdsv2_enforced"], view_row["is_ssh_accessible"]) == (1, 1)
    assert view_row["instance_age_days"] is not None


def test_reload_is_idempotent_and_advances_last_seen(conn: Session, db: Any) -> None:
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


def test_changed_attribute_counts_as_updated(conn: Session, db: Any) -> None:
    do_load(conn, collected(make_instance(), amis=(make_ami(),)))

    updated_inst = make_instance(state="stopped", name="web-2")
    ic = do_load(conn, collected(updated_inst, amis=(make_ami(name="base-2"),)))
    assert ic.updated == 1
    row = fetch(db, "SELECT state, name, ami_name FROM instance")[0]
    assert row == {"state": "stopped", "name": "web-2", "ami_name": "base-2"}


def test_instance_with_unknown_ami_is_stored(conn: Session, db: Any) -> None:
    inst = dataclasses.replace(make_instance(), image_id="ami-unknown")
    ic = do_load(conn, collected(inst))
    assert ic.created == 1
    row = fetch(db, "SELECT image_id, ami_name, ami_state FROM instance")[0]
    assert row == {"image_id": "ami-unknown", "ami_name": None, "ami_state": None}


def test_instance_without_optional_attributes(conn: Session, db: Any) -> None:
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
