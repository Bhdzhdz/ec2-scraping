"""Region resolution and CLI usage errors."""

import boto3
import pytest
from botocore.stub import Stubber

from ec2_scraping import cli
from ec2_scraping.session import ProfileSession, resolve_regions


def test_all_regions_uses_enabled_regions_only():
    ec2 = boto3.client(
        "ec2", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x"
    )

    class Boto:
        region_name = "us-east-1"

        def client(self, *_, **__):
            return ec2

    with Stubber(ec2) as stub:
        stub.add_response(
            "describe_regions",
            {"Regions": [{"RegionName": "us-west-2"}, {"RegionName": "eu-west-1"}]},
            {"AllRegions": False},
        )
        regions = resolve_regions(ProfileSession("p", Boto(), "1"), None, True)
    assert regions == ["eu-west-1", "us-west-2"]


def test_explicit_and_default_regions():
    class Boto:
        region_name = "us-east-2"

    ps = ProfileSession("p", Boto(), "1")
    assert resolve_regions(ps, ["a", "b", "a"], False) == ["a", "b"]
    assert resolve_regions(ps, None, False) == ["us-east-2"]


def test_all_regions_with_region_is_usage_error():
    assert cli.main(["run", "--profile", "p", "--all-regions", "--region", "us-east-1"]) == 64


def test_missing_required_profile_is_usage_error():
    with pytest.raises(SystemExit) as info:
        cli.main(["run"])
    assert info.value.code == 64


def test_missing_dsn_is_config_error(monkeypatch):
    monkeypatch.delenv("MARIADB_DSN", raising=False)
    assert cli.main(["run", "--profile", "p", "--region", "us-east-1"]) == 64
