"""Region resolution, loader, runner, enricher, and CLI tests."""

from datetime import datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from botocore.stub import Stubber
from tests.integration.helpers import make_ssh_enrichment

from ec2_scraping import cli, load, runner
from ec2_scraping.models import (
    AmiRecord,
    Collected,
    InstanceRecord,
    NetworkInterfaceRecord,
    TypeInfo,
    VolumeAttachment,
    VolumeInfo,
)
from ec2_scraping.session import ProfileSession, SsoLoginRequired, resolve_regions

if TYPE_CHECKING:
    from ec2_scraping.db.models import Instance
    from ec2_scraping.models import EnrichmentResult


def test_all_regions_uses_enabled_regions_only() -> None:
    ec2 = boto3.client(
        "ec2",
        region_name="us-east-1",
        aws_access_key_id="x",
        aws_secret_access_key="x",  # noqa: S106
    )

    class Boto:
        region_name = "us-east-1"

        def client(self, *_args: Any, **_kwargs: Any) -> Any:
            return ec2

    with Stubber(ec2) as stub:
        stub.add_response(
            "describe_regions",
            {"Regions": [{"RegionName": "us-west-2"}, {"RegionName": "eu-west-1"}]},
            {"AllRegions": False},
        )
        regions = resolve_regions(ProfileSession("p", Boto(), "1"), None, True)
    assert regions == ["eu-west-1", "us-west-2"]


def test_explicit_and_default_regions() -> None:
    class Boto:
        region_name = "us-east-2"

    ps = ProfileSession("p", Boto(), "1")
    assert resolve_regions(ps, ["a", "b", "a"], False) == ["a", "b"]
    assert resolve_regions(ps, None, False) == ["us-east-2"]


def test_all_regions_with_region_is_usage_error() -> None:
    assert cli.main(["run", "--profile", "p", "--all-regions", "--region", "us-east-1"]) == 64


def test_missing_required_profile_is_usage_error() -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(["run"])
    assert info.value.code == 64


def test_invalid_dsn_is_config_error() -> None:
    assert (
        cli.main(["run", "--profile", "p", "--region", "us-east-1", "--dsn", "postgres://x"]) == 64
    )


def _sample_collected() -> Collected:
    inst_rec = InstanceRecord(
        instance_id="i-1",
        instance_type="g4dn.xlarge",
        availability_zone="us-east-1a",
        image_id="ami-1",
        state="running",
        architecture="x86_64",
        launch_time=datetime(2026, 1, 1),
        name="web",
        vpc_id="vpc-1",
        subnet_id="subnet-1",
        key_name="k",
        iam_profile_arn="arn:aws:iam::111111111111:instance-profile/web-role",
        private_ip="10.0.0.1",
        root_device_type="ebs",
        root_device_name="/dev/xvda",
        ebs_optimized=True,
        imds_http_tokens="required",
        tags={"Name": "web", "env": "prod"},
        security_groups=[("sg-1", "web-sg")],
        volumes=[VolumeAttachment("/dev/xvda", "vol-1", True)],
        network_interfaces=[
            NetworkInterfaceRecord("eni-1", "subnet-1", "10.0.0.1", "1.2.3.4", "0a:1b:2c:3d:4e:5f")
        ],
    )
    ami_rec = AmiRecord(
        image_id="ami-1",
        owner_aws_account_id="111111111111",
        state="available",
        architecture="x86_64",
        root_device_type="ebs",
        virtualization_type="hvm",
        name="base",
    )
    return Collected(
        instances=[inst_rec],
        amis={"ami-1": ami_rec},
        type_info={
            "g4dn.xlarge": TypeInfo(
                vcpu=4,
                memory_mib=16384,
                architecture="x86_64",
                gpu_count=1,
                gpu_model="NVIDIA T4",
                gpu_memory_mib=16384,
            )
        },
        volume_info={"vol-1": VolumeInfo("vol-1", 50, "gp3", True, 3000, 125)},
        vpc_cidrs={"vpc-1": "10.0.0.0/16"},
        subnet_cidrs={"subnet-1": "10.0.0.0/24"},
    )


class _FakeSshEnricher:
    name = "ssh"

    def enrich(self, _account_id: str, _region: str, _inst: InstanceRecord) -> EnrichmentResult:
        return make_ssh_enrichment(
            hostname="web-1",
            uptime_seconds=3600,
            package_count=500,
            listening_port_count=2,
            container_count=1,
            reboot_required=False,
        )


class _FailingCustomEnricher:
    name = "ssm"

    def enrich(self, _account_id: str, _region: str, _inst: InstanceRecord) -> EnrichmentResult:
        msg = "agent offline"
        raise RuntimeError(msg)


class _FakePS:
    default_region = "us-east-1"
    account_id = "111111111111"

    def __init__(self, profile: str) -> None:
        self.profile = profile

    def ec2(self, region: str) -> str:
        return region


def _fake_open(profile: str) -> _FakePS:
    if profile == "sso-expired":
        raise SsoLoginRequired(profile)
    if profile == "bad-profile":
        msg = "boom"
        raise RuntimeError(msg)
    return _FakePS(profile)


def _assert_initial_load(db: Any, data: Collected, stored: list[Instance]) -> Instance:
    c1 = load.load_instances(db, "111111111111", "us-east-1", data)
    assert (c1.created, c1.updated, c1.unchanged) == (1, 0, 0)
    row = stored[0]
    assert (row.instance_family, row.iam_instance_profile_name, row.root_volume_id) == (
        "g4dn",
        "web-role",
        "vol-1",
    )
    assert (row.root_volume_size_gib, row.ebs_total_size_gib, row.ebs_all_encrypted) == (
        50,
        50,
        True,
    )
    assert (row.eni_count, row.security_group_count) == (1, 1)
    c2 = load.load_instances(db, "111111111111", "us-east-1", data)
    assert (c2.created, c2.updated, c2.unchanged) == (0, 0, 1)
    return row


def _assert_enriched_row(row: Instance) -> None:
    assert (row.ssh_status, row.ssh_user, row.ssh_os_id, row.ssh_os_version) == (
        "succeeded",
        "ubuntu",
        "ubuntu",
        "24.04",
    )
    assert (row.ssh_os_pretty_name, row.ssh_kernel, row.ssh_hostname) == (
        "Ubuntu 24.04 LTS",
        "6.8.0",
        "web-1",
    )
    assert (
        row.ssh_uptime_seconds,
        row.ssh_package_count,
        row.ssh_listening_port_count,
        row.ssh_container_count,
        row.ssh_reboot_required,
    ) == (3600, 500, 2, 1, False)
    assert row.extra_facts is not None
    assert row.extra_facts["ssm"]["status"] == "failed"


def test_load_instances_enrichers_runner_and_cli_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _sample_collected()
    stored: list[Instance] = []

    class FakeScalars:
        def all(self) -> list[Instance]:
            return list(stored)

    db = MagicMock()
    db.scalars.side_effect = lambda _: FakeScalars()
    db.add.side_effect = stored.append

    row = _assert_initial_load(db, data, stored)

    def fake_collect(region: str, _account_id: str) -> Collected:
        if region == "opt-in":
            raise ClientError({"Error": {"Code": "OptInRequired"}}, "DescribeInstances")
        if region == "offline":
            raise EndpointConnectionError(endpoint_url="https://ec2.offline")
        return data

    res = runner.run(
        db,
        ["ok", "sso-expired", "bad-profile"],
        ["us-east-1", "opt-in", "offline"],
        open_session=_fake_open,
        collect_fn=fake_collect,
        enrichers=[_FakeSshEnricher(), _FailingCustomEnricher()],
    )
    assert res.status == "partial"
    _assert_enriched_row(row)

    summary = cli.format_summary(res)
    assert "Scrape run: partial" in summary
    assert "ok/us-east-1: instances" in summary
    assert "Failures:" in summary

    monkeypatch.setattr(cli.db, "connect", lambda _dsn: db)
    monkeypatch.setattr(cli.runner, "run", lambda *_a, **_kw: res)
    assert (
        cli.main(["run", "--profile", "ok", "--region", "us-east-1", "--dsn", "mysql://u@h/d"]) == 1
    )


def test_empty_inputs_and_chunked_accessed_ids() -> None:
    inst_ids = [f"i-{n}" for n in range(1200)] + ["i-0"]
    db = MagicMock()
    assert load.get_accessed_ssh_instance_ids(db, "111111111111", "us-east-1", []) == set()
    assert load.get_known_ssh_users(db, "111111111111", "us-east-1", []) == {}
    assert load.get_known_ami_ssh_users(db, []) == {}
    assert load.load_instances(db, "111111111111", "us-east-1", Collected()).created == 0
    assert (db.scalars.call_count, db.execute.call_count) == (0, 0)

    db.scalars.side_effect = [
        MagicMock(all=lambda: ["i-0", "i-499"]),
        MagicMock(all=lambda: ["i-500"]),
        MagicMock(all=lambda: ["i-1199"]),
    ]
    accessed = load.get_accessed_ssh_instance_ids(db, "111111111111", "us-east-1", inst_ids)
    assert accessed == {"i-0", "i-499", "i-500", "i-1199"}
    assert db.scalars.call_count == 3


def test_chunked_known_ssh_users_and_ami_users() -> None:
    inst_ids = [f"i-{n}" for n in range(1200)] + ["i-0"]
    img_ids = [f"ami-{n}" for n in range(1200)] + ["ami-0"]
    db = MagicMock()
    db.execute.side_effect = [
        MagicMock(all=lambda: [("i-0", "ubuntu"), ("i-1", "")]),
        MagicMock(all=lambda: [("i-500", "ec2-user")]),
        MagicMock(all=lambda: [("i-1199", "admin")]),
    ]
    users = load.get_known_ssh_users(db, "111111111111", "us-east-1", inst_ids)
    assert users == {"i-0": "ubuntu", "i-500": "ec2-user", "i-1199": "admin"}
    assert db.execute.call_count == 3

    db.execute.reset_mock()
    db.execute.side_effect = [
        MagicMock(all=lambda: [("ami-0", "ubuntu"), (None, "root")]),
        MagicMock(all=lambda: [("ami-500", "ec2-user")]),
        MagicMock(all=lambda: [("ami-1199", "debian")]),
    ]
    ami_users = load.get_known_ami_ssh_users(db, img_ids)
    assert ami_users == {"ami-0": "ubuntu", "ami-500": "ec2-user", "ami-1199": "debian"}
    assert db.execute.call_count == 3
