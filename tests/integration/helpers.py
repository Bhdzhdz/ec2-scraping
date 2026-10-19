"""Shared builders and fakes for integration tests."""

from datetime import datetime
from typing import Any

from botocore.exceptions import ClientError

from ec2_scraping.models import (
    AmiRecord,
    BlockMapping,
    Collected,
    InstanceRecord,
    NetworkInterfaceRecord,
    VolumeRecord,
)
from ec2_scraping.session import SsoLoginRequired


def make_instance(instance_id: str = "i-1", **kw) -> InstanceRecord:
    base: dict[str, Any] = {
        "instance_id": instance_id,
        "instance_type": "t3.micro",
        "availability_zone": "us-east-1a",
        "image_id": "ami-1",
        "state": "running",
        "architecture": "x86_64",
        "launch_time": datetime(2026, 1, 1),
        "vpc_id": "vpc-1",
        "subnet_id": "subnet-1",
        "key_name": "key",
        "iam_profile_arn": "arn:aws:iam::111111111111:instance-profile/p",
        "private_ip": "10.0.0.1",
        "tags": {"Name": "web", "env": "dev"},
        "security_groups": [("sg-1", "web"), ("sg-2", "db")],
        "volumes": [VolumeRecord("/dev/xvda", "vol-1")],
        "network_interfaces": [NetworkInterfaceRecord("eni-1", "subnet-1", "10.0.0.1", None)],
    }
    base.update(kw)
    return InstanceRecord(**base)


def make_ami(image_id: str = "ami-1", **kw) -> AmiRecord:
    base: dict[str, Any] = {
        "image_id": image_id,
        "owner_aws_account_id": "111111111111",
        "state": "available",
        "architecture": "x86_64",
        "root_device_type": "ebs",
        "virtualization_type": "hvm",
        "name": "base",
        "tags": {"team": "a", "tier": "b"},
        "block_mappings": [BlockMapping("/dev/xvda", "snap-1", 8)],
    }
    base.update(kw)
    return AmiRecord(**base)


def collected(*instances: InstanceRecord, amis: tuple[AmiRecord, ...] = ()) -> Collected:
    return Collected(
        instances=list(instances),
        amis=list(amis),
        vpc_cidrs={"vpc-1": "10.0.0.0/16"},
        subnet_cidrs={"subnet-1": "10.0.0.0/24"},
        sg_names={"sg-1": "web", "sg-2": "db"},
    )


class FakeSession:
    default_region = "us-east-1"

    def __init__(self, profile: str, account_id: str):
        self.profile = profile
        self.account_id = account_id

    def ec2(self, region: str) -> str:
        return region  # the fake collector receives the region as its "client"


def opener(accounts: dict[str, str | Exception]):
    """open_session replacement: profile -> FakeSession, or raise the configured error."""

    def open_session(profile: str) -> FakeSession:
        value = accounts[profile]
        if isinstance(value, Exception):
            raise value
        return FakeSession(profile, value)

    return open_session


def login_required(profile: str) -> SsoLoginRequired:
    return SsoLoginRequired(profile)


def client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, "DescribeInstances")


def scripted_collector(script: dict):
    """collect_fn(region, account_id): script[(account_id, region)] is Collected or an exception."""

    def collect_fn(region: str, account_id: str) -> Collected:
        value = script[(account_id, region)]
        if isinstance(value, BaseException):
            raise value
        return value

    return collect_fn
