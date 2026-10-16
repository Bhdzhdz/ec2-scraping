"""Collection against a stubbed EC2 client: paging, optional fields, read-only calls."""

from datetime import datetime

import boto3
import pytest
from botocore.stub import Stubber

from ec2_scraping.collect import collect
from ec2_scraping.session import CLIENT_CONFIG, ProfileSession

ACCOUNT = "111111111111"
LAUNCH = datetime(2026, 1, 2, 3, 4, 5)


def _client():
    return boto3.client(
        "ec2", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x"
    )


def _full_instance():
    return {
        "InstanceId": "i-1",
        "InstanceType": "t3.micro",
        "ImageId": "ami-1",
        "State": {"Name": "running"},
        "Architecture": "x86_64",
        "LaunchTime": LAUNCH,
        "Placement": {"AvailabilityZone": "us-east-1a"},
        "VpcId": "vpc-1",
        "SubnetId": "subnet-1",
        "KeyName": "k",
        "IamInstanceProfile": {"Arn": "arn:aws:iam::111111111111:instance-profile/p"},
        "PrivateIpAddress": "10.0.0.1",
        "PublicIpAddress": "1.2.3.4",
        "Monitoring": {"State": "enabled"},
        "Tags": [{"Key": "Name", "Value": "web"}],
        "SecurityGroups": [{"GroupId": "sg-1", "GroupName": "web-sg"}],
        "BlockDeviceMappings": [{"DeviceName": "/dev/xvda", "Ebs": {"VolumeId": "vol-1"}}],
        "NetworkInterfaces": [
            {
                "NetworkInterfaceId": "eni-1",
                "SubnetId": "subnet-1",
                "PrivateIpAddress": "10.0.0.1",
                "Association": {"PublicIp": "1.2.3.4"},
            }
        ],
    }


def _minimal_instance():
    return {
        "InstanceId": "i-2",
        "InstanceType": "t3.small",
        "ImageId": "ami-9",
        "State": {"Name": "stopped"},
        "LaunchTime": LAUNCH,
        "Placement": {"AvailabilityZone": "us-east-1b"},
    }


def _ami(image_id="ami-1"):
    return {
        "ImageId": image_id,
        "OwnerId": ACCOUNT,
        "State": "available",
        "Architecture": "x86_64",
        "RootDeviceType": "ebs",
        "VirtualizationType": "hvm",
        "CreationDate": "2026-01-01T00:00:00.000Z",
        "BlockDeviceMappings": [
            {"DeviceName": "/dev/xvda", "Ebs": {"SnapshotId": "snap-1", "VolumeSize": 8}}
        ],
    }


def _stub_full(stub: Stubber, ami9_error: str = "InvalidAMIID.NotFound") -> None:
    stub.add_response(
        "describe_instances",
        {"Reservations": [{"Instances": [_full_instance()]}], "NextToken": "n1"},
        {},
    )
    stub.add_response(
        "describe_instances",
        {"Reservations": [{"Instances": [_minimal_instance()]}]},
        {"NextToken": "n1"},
    )
    stub.add_response("describe_images", {"Images": [_ami()]}, {"Owners": [ACCOUNT]})
    for _ in range(2):  # batch call, then per-image fallback
        stub.add_client_error(
            "describe_images", ami9_error, expected_params={"ImageIds": ["ami-9"]}
        )
    stub.add_response(
        "describe_instance_types",
        {
            "InstanceTypes": [
                {
                    "InstanceType": "t3.micro",
                    "VCpuInfo": {"DefaultVCpus": 2},
                    "MemoryInfo": {"SizeInMiB": 1024},
                    "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
                }
            ]
        },
        {"InstanceTypes": ["t3.micro", "t3.small"]},
    )
    stub.add_response(
        "describe_vpcs",
        {"Vpcs": [{"VpcId": "vpc-1", "CidrBlock": "10.0.0.0/16"}]},
        {"VpcIds": ["vpc-1"]},
    )
    stub.add_response(
        "describe_subnets",
        {"Subnets": [{"SubnetId": "subnet-1", "CidrBlock": "10.0.0.0/24"}]},
        {"SubnetIds": ["subnet-1"]},
    )
    stub.add_response(
        "describe_security_groups",
        {"SecurityGroups": [{"GroupId": "sg-1", "GroupName": "web-sg"}]},
        {"GroupIds": ["sg-1"]},
    )


def test_collects_all_pages_and_maps_optionals():
    ec2 = _client()
    operations: list[str] = []
    ec2.meta.events.register(
        "before-parameter-build.ec2.*", lambda model, **_: operations.append(model.name)
    )
    with Stubber(ec2) as stub:
        _stub_full(stub)
        data = collect(ec2, ACCOUNT)
        stub.assert_no_pending_responses()

    assert [i.instance_id for i in data.instances] == ["i-1", "i-2"]  # both pages
    full, minimal = data.instances
    assert full.tags == {"Name": "web"}
    assert full.public_ip == "1.2.3.4"
    assert full.network_interfaces[0].public_ip == "1.2.3.4"
    assert minimal.vpc_id is None
    assert minimal.key_name is None
    assert minimal.iam_profile_arn is None
    assert minimal.public_ip is None
    assert minimal.tags == {}
    assert minimal.security_groups == []
    assert [a.image_id for a in data.amis] == ["ami-1"]  # missing ami-9 tolerated
    assert data.amis[0].block_mappings[0].snapshot_id == "snap-1"
    assert data.type_info["t3.micro"].vcpu == 2
    assert data.vpc_cidrs == {"vpc-1": "10.0.0.0/16"}
    assert data.subnet_cidrs == {"subnet-1": "10.0.0.0/24"}
    assert data.sg_names == {"sg-1": "web-sg"}
    assert operations
    assert all(op.startswith("Describe") for op in operations)


def test_unexpected_ami_error_is_not_swallowed():
    ec2 = _client()
    with Stubber(ec2) as stub:
        stub.add_response(
            "describe_instances",
            {"Reservations": [{"Instances": [_minimal_instance()]}]},
            {},
        )
        stub.add_response("describe_images", {"Images": []}, {"Owners": [ACCOUNT]})
        stub.add_client_error("describe_images", "UnauthorizedOperation")
        with pytest.raises(Exception, match="UnauthorizedOperation"):
            collect(ec2, ACCOUNT)


def test_clients_use_adaptive_retries():
    calls = []

    class FakeBoto:
        region_name = "us-east-1"

        def client(self, name, **kwargs):
            calls.append(kwargs)
            return object()

    ProfileSession("p", FakeBoto(), ACCOUNT).ec2("eu-west-1")
    assert calls[0]["config"] is CLIENT_CONFIG
    assert CLIENT_CONFIG.retries == {"mode": "adaptive", "max_attempts": 10}
