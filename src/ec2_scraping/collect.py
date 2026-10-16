"""Paginated, read-only EC2 Describe* collection mapped to plain dataclasses."""

from collections.abc import Iterable, Iterator
from datetime import UTC, datetime

from botocore.exceptions import ClientError

from ec2_scraping.models import (
    AmiRecord,
    BlockMapping,
    Collected,
    InstanceRecord,
    NetworkInterfaceRecord,
    TypeInfo,
    VolumeRecord,
)

BATCH = 100
_TOLERATED = {"InvalidAMIID.NotFound", "InvalidAMIID.Unavailable", "InvalidAMIID.Malformed"}


def _naive_utc(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.replace(microsecond=0)


def _tags(items: list[dict] | None) -> dict[str, str]:
    return {t["Key"]: t.get("Value", "") for t in items or []}


def _batches(values: Iterable[str], size: int = BATCH) -> Iterator[list[str]]:
    ordered = sorted(set(values))
    for i in range(0, len(ordered), size):
        yield ordered[i : i + size]


def map_instance(raw: dict) -> InstanceRecord:
    nics = [
        NetworkInterfaceRecord(
            eni_id=n["NetworkInterfaceId"],
            subnet_id=n.get("SubnetId"),
            private_ip=n.get("PrivateIpAddress"),
            public_ip=(n.get("Association") or {}).get("PublicIp"),
        )
        for n in raw.get("NetworkInterfaces", [])
    ]
    volumes = [
        VolumeRecord(b["DeviceName"], b["Ebs"]["VolumeId"])
        for b in raw.get("BlockDeviceMappings", [])
        if b.get("Ebs")
    ]
    monitoring = (raw.get("Monitoring") or {}).get("State", "disabled")
    return InstanceRecord(
        instance_id=raw["InstanceId"],
        instance_type=raw["InstanceType"],
        availability_zone=raw["Placement"]["AvailabilityZone"],
        image_id=raw["ImageId"],
        state=raw["State"]["Name"],
        architecture=raw.get("Architecture", "unknown"),
        launch_time=_naive_utc(raw["LaunchTime"]),
        vpc_id=raw.get("VpcId"),
        subnet_id=raw.get("SubnetId"),
        key_name=raw.get("KeyName"),
        iam_profile_arn=(raw.get("IamInstanceProfile") or {}).get("Arn"),
        platform=raw.get("Platform"),
        private_ip=raw.get("PrivateIpAddress"),
        public_ip=raw.get("PublicIpAddress"),
        monitoring=monitoring if monitoring in ("disabled", "enabled", "pending") else "disabled",
        tags=_tags(raw.get("Tags")),
        security_groups=[(g["GroupId"], g.get("GroupName")) for g in raw.get("SecurityGroups", [])],
        volumes=volumes,
        network_interfaces=nics,
    )


def map_ami(raw: dict) -> AmiRecord:
    return AmiRecord(
        image_id=raw["ImageId"],
        owner_aws_account_id=raw["OwnerId"],
        state=raw["State"],
        architecture=raw.get("Architecture", "unknown"),
        root_device_type=raw.get("RootDeviceType", "unknown"),
        virtualization_type=raw.get("VirtualizationType", "unknown"),
        name=raw.get("Name"),
        description=raw.get("Description"),
        creation_date=_naive_utc(raw.get("CreationDate")),
        platform=raw.get("Platform"),
        is_public=bool(raw.get("Public", False)),
        deprecation_time=_naive_utc(raw.get("DeprecationTime")),
        tags=_tags(raw.get("Tags")),
        block_mappings=[
            BlockMapping(
                b["DeviceName"],
                (b.get("Ebs") or {}).get("SnapshotId"),
                (b.get("Ebs") or {}).get("VolumeSize"),
            )
            for b in raw.get("BlockDeviceMappings", [])
        ],
    )


def _fetch_images(ec2, image_ids: list[str]) -> list[dict]:
    """Describe referenced AMIs; tolerate ones that are missing or not visible."""
    try:
        return ec2.describe_images(ImageIds=image_ids)["Images"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in _TOLERATED:
            raise
    found: list[dict] = []
    for image_id in image_ids:
        try:
            found += ec2.describe_images(ImageIds=[image_id])["Images"]
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in _TOLERATED:
                raise
    return found


def collect(ec2, account_id: str) -> Collected:
    """Gather instances, AMIs and the reference metadata needed to load them."""
    data = Collected()

    for page in ec2.get_paginator("describe_instances").paginate():
        for reservation in page["Reservations"]:
            data.instances.extend(map_instance(i) for i in reservation["Instances"])

    owned: dict[str, AmiRecord] = {}
    for page in ec2.get_paginator("describe_images").paginate(Owners=[account_id]):
        for raw in page["Images"]:
            owned[raw["ImageId"]] = map_ami(raw)

    referenced = {i.image_id for i in data.instances} - owned.keys()
    for batch in _batches(referenced):
        for raw in _fetch_images(ec2, batch):
            owned.setdefault(raw["ImageId"], map_ami(raw))
    data.amis = list(owned.values())

    for batch in _batches(i.instance_type for i in data.instances):
        for page in ec2.get_paginator("describe_instance_types").paginate(InstanceTypes=batch):
            for t in page["InstanceTypes"]:
                archs = t.get("ProcessorInfo", {}).get("SupportedArchitectures") or [None]
                data.type_info[t["InstanceType"]] = TypeInfo(
                    vcpu=t.get("VCpuInfo", {}).get("DefaultVCpus"),
                    memory_mib=t.get("MemoryInfo", {}).get("SizeInMiB"),
                    architecture=archs[0],
                )

    vpc_ids = {i.vpc_id for i in data.instances if i.vpc_id}
    for batch in _batches(vpc_ids):
        for page in ec2.get_paginator("describe_vpcs").paginate(VpcIds=batch):
            data.vpc_cidrs.update({v["VpcId"]: v["CidrBlock"] for v in page["Vpcs"]})

    subnet_ids = {s for i in data.instances for s in _subnets(i)}
    for batch in _batches(subnet_ids):
        for page in ec2.get_paginator("describe_subnets").paginate(SubnetIds=batch):
            data.subnet_cidrs.update({s["SubnetId"]: s["CidrBlock"] for s in page["Subnets"]})

    group_ids = {g for i in data.instances for g, _ in i.security_groups}
    for batch in _batches(group_ids):
        for page in ec2.get_paginator("describe_security_groups").paginate(GroupIds=batch):
            data.sg_names.update({g["GroupId"]: g["GroupName"] for g in page["SecurityGroups"]})

    return data


def _subnets(inst: InstanceRecord) -> set[str]:
    ids = {n.subnet_id for n in inst.network_interfaces if n.subnet_id}
    if inst.subnet_id:
        ids.add(inst.subnet_id)
    return ids
