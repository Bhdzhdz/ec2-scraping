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
        "InstanceType": "g4dn.xlarge",
        "ImageId": "ami-1",
        "State": {"Name": "running"},
        "StateReason": {"Code": "Server.SpotInstanceTermination"},
        "StateTransitionReason": "User initiated",
        "InstanceLifecycle": "spot",
        "SpotInstanceRequestId": "sir-1",
        "CapacityReservationId": "cr-1",
        "Architecture": "x86_64",
        "LaunchTime": LAUNCH,
        "UsageOperation": "RunInstances",
        "Placement": {
            "AvailabilityZone": "us-east-1a",
            "Tenancy": "dedicated",
            "GroupName": "pg-1",
            "HostId": "h-1",
        },
        "CpuOptions": {"CoreCount": 2, "ThreadsPerCore": 2},
        "Hypervisor": "nitro",
        "VirtualizationType": "hvm",
        "EnaSupport": True,
        "SriovNetSupport": "simple",
        "BootMode": "uefi",
        "TpmSupport": "v2.0",
        "Platform": "windows",
        "PlatformDetails": "Windows",
        "VpcId": "vpc-1",
        "SubnetId": "subnet-1",
        "KeyName": "k",
        "IamInstanceProfile": {"Arn": "arn:aws:iam::111111111111:instance-profile/p"},
        "PrivateIpAddress": "10.0.0.1",
        "PublicIpAddress": "1.2.3.4",
        "PrivateDnsName": "ip-10-0-0-1.ec2.internal",
        "PublicDnsName": "ec2-1-2-3-4.compute-1.amazonaws.com",
        "SourceDestCheck": True,
        "EbsOptimized": True,
        "RootDeviceType": "ebs",
        "RootDeviceName": "/dev/xvda",
        "MetadataOptions": {
            "HttpTokens": "required",
            "HttpEndpoint": "enabled",
            "HttpPutResponseHopLimit": 2,
            "InstanceMetadataTags": "enabled",
        },
        "Monitoring": {"State": "enabled"},
        "Tags": [{"Key": "Name", "Value": "web"}, {"Key": "env", "Value": "dev"}],
        "SecurityGroups": [{"GroupId": "sg-1", "GroupName": "web-sg"}],
        "BlockDeviceMappings": [
            {
                "DeviceName": "/dev/xvda",
                "Ebs": {"VolumeId": "vol-1", "DeleteOnTermination": True},
            }
        ],
        "NetworkInterfaces": [
            {
                "NetworkInterfaceId": "eni-1",
                "SubnetId": "subnet-1",
                "PrivateIpAddress": "10.0.0.1",
                "MacAddress": "0a:1b:2c:3d:4e:5f",
                "Association": {"PublicIp": "1.2.3.4"},
                "Ipv6Addresses": [{"Ipv6Address": "2001:db8::1"}],
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
        "Name": "base",
        "PlatformDetails": "Linux/UNIX",
        "CreationDate": "2026-01-01T00:00:00.000Z",
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
    stub.add_client_error(
        "describe_images", ami9_error, expected_params={"ImageIds": ["ami-1", "ami-9"]}
    )
    stub.add_response("describe_images", {"Images": [_ami()]}, {"ImageIds": ["ami-1"]})
    stub.add_client_error("describe_images", ami9_error, expected_params={"ImageIds": ["ami-9"]})
    stub.add_response(
        "describe_instance_types",
        {
            "InstanceTypes": [
                {
                    "InstanceType": "g4dn.xlarge",
                    "CurrentGeneration": True,
                    "BareMetal": False,
                    "BurstablePerformanceSupported": False,
                    "VCpuInfo": {"DefaultVCpus": 4},
                    "MemoryInfo": {"SizeInMiB": 16384},
                    "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
                    "GpuInfo": {
                        "Gpus": [{"Name": "T4", "Manufacturer": "NVIDIA", "Count": 1}],
                        "TotalGpuMemoryInMiB": 16384,
                    },
                    "InstanceStorageInfo": {"TotalSizeInGB": 125},
                    "NetworkInfo": {"NetworkPerformance": "Up to 25 Gigabit"},
                }
            ]
        },
        {"InstanceTypes": ["g4dn.xlarge", "t3.small"]},
    )
    stub.add_response(
        "describe_volumes",
        {
            "Volumes": [
                {
                    "VolumeId": "vol-1",
                    "Size": 50,
                    "VolumeType": "gp3",
                    "Encrypted": True,
                    "Iops": 3000,
                    "Throughput": 125,
                }
            ]
        },
        {"VolumeIds": ["vol-1"]},
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


def test_collects_all_pages_and_maps_analytics_fields():
    ec2 = _client()
    operations: list[str] = []
    ec2.meta.events.register(
        "before-parameter-build.ec2.*", lambda model, **_: operations.append(model.name)
    )
    with Stubber(ec2) as stub:
        _stub_full(stub)
        data = collect(ec2, ACCOUNT)
        stub.assert_no_pending_responses()

    assert [i.instance_id for i in data.instances] == ["i-1", "i-2"]
    full, minimal = data.instances
    assert full.name == "web"
    assert full.tags == {"Name": "web", "env": "dev"}
    assert full.lifecycle == "spot"
    assert full.tenancy == "dedicated"
    assert full.placement_group == "pg-1"
    assert (full.cpu_core_count, full.cpu_threads_per_core) == (2, 2)
    assert full.imds_http_tokens == "required"
    assert full.ipv6_address == "2001:db8::1"
    assert full.public_ip == "1.2.3.4"
    assert full.network_interfaces[0].mac_address == "0a:1b:2c:3d:4e:5f"
    assert full.volumes[0].volume_id == "vol-1"

    assert minimal.name is None
    assert minimal.lifecycle == "on-demand"
    assert minimal.tenancy == "default"
    assert minimal.vpc_id is None
    assert minimal.tags == {}

    assert list(data.amis) == ["ami-1"]
    assert data.amis["ami-1"].platform_details == "Linux/UNIX"

    tinfo = data.type_info["g4dn.xlarge"]
    assert (tinfo.vcpu, tinfo.memory_mib) == (4, 16384)
    assert (tinfo.gpu_count, tinfo.gpu_model) == (1, "NVIDIA T4")
    assert tinfo.instance_storage_gib == 125
    assert tinfo.network_performance == "Up to 25 Gigabit"

    vinfo = data.volume_info["vol-1"]
    assert (vinfo.size_gib, vinfo.volume_type, vinfo.encrypted) == (50, "gp3", True)

    assert data.vpc_cidrs == {"vpc-1": "10.0.0.0/16"}
    assert data.subnet_cidrs == {"subnet-1": "10.0.0.0/24"}
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
        stub.add_client_error("describe_images", "UnauthorizedOperation")
        with pytest.raises(Exception, match="UnauthorizedOperation"):
            collect(ec2, ACCOUNT)


def test_tolerated_client_errors_fall_back_per_item():
    ec2 = _client()
    inst1 = _full_instance()
    inst2 = {
        **_minimal_instance(),
        "VpcId": "vpc-missing",
        "SubnetId": "subnet-missing",
        "BlockDeviceMappings": [
            {
                "DeviceName": "/dev/xvda",
                "Ebs": {"VolumeId": "vol-missing", "DeleteOnTermination": True},
            }
        ],
    }
    with Stubber(ec2) as stub:
        stub.add_response(
            "describe_instances",
            {"Reservations": [{"Instances": [inst1, inst2]}]},
            {},
        )
        stub.add_response("describe_images", {"Images": [_ami()]}, {"ImageIds": ["ami-1", "ami-9"]})

        # describe_instance_types fails on batch, succeeds for g4dn.xlarge, skips t3.small
        stub.add_client_error(
            "describe_instance_types",
            "InvalidInstanceType",
            expected_params={"InstanceTypes": ["g4dn.xlarge", "t3.small"]},
        )
        stub.add_response(
            "describe_instance_types",
            {"InstanceTypes": [{"InstanceType": "g4dn.xlarge", "VCpuInfo": {"DefaultVCpus": 4}}]},
            {"InstanceTypes": ["g4dn.xlarge"]},
        )
        stub.add_client_error(
            "describe_instance_types",
            "InvalidInstanceType",
            expected_params={"InstanceTypes": ["t3.small"]},
        )

        # describe_volumes fails on batch, succeeds for vol-1, skips vol-missing
        stub.add_client_error(
            "describe_volumes",
            "InvalidVolume.NotFound",
            expected_params={"VolumeIds": ["vol-1", "vol-missing"]},
        )
        stub.add_response(
            "describe_volumes",
            {
                "Volumes": [
                    {"VolumeId": "vol-1", "Size": 50, "VolumeType": "gp3", "Encrypted": True}
                ]
            },
            {"VolumeIds": ["vol-1"]},
        )
        stub.add_client_error(
            "describe_volumes",
            "InvalidVolume.NotFound",
            expected_params={"VolumeIds": ["vol-missing"]},
        )

        # describe_vpcs fails on batch, succeeds for vpc-1, tolerated error for vpc-missing
        stub.add_client_error(
            "describe_vpcs",
            "InvalidVpcID.NotFound",
            expected_params={"VpcIds": ["vpc-1", "vpc-missing"]},
        )
        stub.add_response(
            "describe_vpcs",
            {"Vpcs": [{"VpcId": "vpc-1", "CidrBlock": "10.0.0.0/16"}]},
            {"VpcIds": ["vpc-1"]},
        )
        stub.add_client_error(
            "describe_vpcs",
            "InvalidVpcID.NotFound",
            expected_params={"VpcIds": ["vpc-missing"]},
        )

        # describe_subnets fails on batch, succeeds for subnet-1, tolerated error for subnet-missing
        stub.add_client_error(
            "describe_subnets",
            "InvalidSubnetID.NotFound",
            expected_params={"SubnetIds": ["subnet-1", "subnet-missing"]},
        )
        stub.add_response(
            "describe_subnets",
            {"Subnets": [{"SubnetId": "subnet-1", "CidrBlock": "10.0.0.0/24"}]},
            {"SubnetIds": ["subnet-1"]},
        )
        stub.add_client_error(
            "describe_subnets",
            "InvalidSubnetID.NotFound",
            expected_params={"SubnetIds": ["subnet-missing"]},
        )

        data = collect(ec2, ACCOUNT)
        stub.assert_no_pending_responses()

    assert list(data.type_info) == ["g4dn.xlarge"]
    assert list(data.volume_info) == ["vol-1"]
    assert data.vpc_cidrs == {"vpc-1": "10.0.0.0/16"}
    assert data.subnet_cidrs == {"subnet-1": "10.0.0.0/24"}


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
