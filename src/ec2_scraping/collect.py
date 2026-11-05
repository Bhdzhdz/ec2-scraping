"""Paginated, read-only EC2 Describe* collection mapped to plain dataclasses."""

from collections.abc import Iterable, Iterator
from datetime import UTC, datetime

from botocore.exceptions import ClientError

from ec2_scraping.models import (
    AmiRecord,
    Collected,
    InstanceRecord,
    NetworkInterfaceRecord,
    TypeInfo,
    VolumeAttachment,
    VolumeInfo,
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
            mac_address=n.get("MacAddress"),
            ipv6_addresses=[
                ip["Ipv6Address"] for ip in n.get("Ipv6Addresses", []) if ip.get("Ipv6Address")
            ],
        )
        for n in raw.get("NetworkInterfaces", [])
    ]
    volumes = [
        VolumeAttachment(
            device_name=b["DeviceName"],
            volume_id=b["Ebs"]["VolumeId"],
            delete_on_termination=b["Ebs"].get("DeleteOnTermination"),
        )
        for b in raw.get("BlockDeviceMappings", [])
        if b.get("Ebs") and b["Ebs"].get("VolumeId")
    ]
    tags = _tags(raw.get("Tags"))
    placement = raw.get("Placement") or {}
    cpu_opts = raw.get("CpuOptions") or {}
    imds = raw.get("MetadataOptions") or {}
    state_reason = raw.get("StateReason") or {}
    monitoring = (raw.get("Monitoring") or {}).get("State", "disabled")
    launch_time = _naive_utc(raw["LaunchTime"])
    assert launch_time is not None

    ipv6 = raw.get("Ipv6Address")
    if not ipv6:
        for nic in nics:
            if nic.ipv6_addresses:
                ipv6 = nic.ipv6_addresses[0]
                break

    return InstanceRecord(
        instance_id=raw["InstanceId"],
        instance_type=raw["InstanceType"],
        availability_zone=placement["AvailabilityZone"],
        image_id=raw["ImageId"],
        state=raw["State"]["Name"],
        architecture=raw.get("Architecture", "unknown"),
        launch_time=launch_time,
        name=tags.get("Name"),
        state_reason_code=state_reason.get("Code"),
        state_transition_reason=raw.get("StateTransitionReason") or None,
        lifecycle=raw.get("InstanceLifecycle") or "on-demand",
        spot_instance_request_id=raw.get("SpotInstanceRequestId"),
        capacity_reservation_id=raw.get("CapacityReservationId"),
        tenancy=placement.get("Tenancy") or "default",
        placement_group=placement.get("GroupName") or None,
        host_id=placement.get("HostId"),
        usage_operation=raw.get("UsageOperation"),
        monitoring=monitoring if monitoring in ("disabled", "enabled", "pending") else "disabled",
        cpu_core_count=cpu_opts.get("CoreCount"),
        cpu_threads_per_core=cpu_opts.get("ThreadsPerCore"),
        hypervisor=raw.get("Hypervisor"),
        virtualization_type=raw.get("VirtualizationType"),
        ena_support=raw.get("EnaSupport"),
        sriov_net_support=raw.get("SriovNetSupport"),
        boot_mode=raw.get("BootMode"),
        tpm_support=raw.get("TpmSupport"),
        platform=raw.get("Platform"),
        platform_details=raw.get("PlatformDetails"),
        vpc_id=raw.get("VpcId"),
        subnet_id=raw.get("SubnetId"),
        private_ip=raw.get("PrivateIpAddress"),
        public_ip=raw.get("PublicIpAddress"),
        ipv6_address=ipv6,
        private_dns_name=raw.get("PrivateDnsName") or None,
        public_dns_name=raw.get("PublicDnsName") or None,
        source_dest_check=raw.get("SourceDestCheck"),
        ebs_optimized=bool(raw.get("EbsOptimized", False)),
        root_device_type=raw.get("RootDeviceType"),
        root_device_name=raw.get("RootDeviceName"),
        key_name=raw.get("KeyName"),
        iam_profile_arn=(raw.get("IamInstanceProfile") or {}).get("Arn"),
        imds_http_tokens=imds.get("HttpTokens"),
        imds_http_endpoint=imds.get("HttpEndpoint"),
        imds_hop_limit=imds.get("HttpPutResponseHopLimit"),
        imds_instance_metadata_tags=imds.get("InstanceMetadataTags"),
        tags=tags,
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
        platform_details=raw.get("PlatformDetails"),
        is_public=bool(raw.get("Public", False)),
        deprecation_time=_naive_utc(raw.get("DeprecationTime")),
    )


def map_type_info(raw: dict) -> TypeInfo:
    archs = (raw.get("ProcessorInfo") or {}).get("SupportedArchitectures") or [None]
    gpus = (raw.get("GpuInfo") or {}).get("Gpus") or []
    gpu_count = sum(g.get("Count", 0) for g in gpus) if gpus else None
    gpu_models = [
        f"{g.get('Manufacturer', '')} {g.get('Name', '')}".strip()
        for g in gpus
        if g.get("Manufacturer") or g.get("Name")
    ]
    gpu_model = ", ".join(dict.fromkeys(gpu_models)) if gpu_models else None
    gpu_mem = (raw.get("GpuInfo") or {}).get("TotalGpuMemoryInMiB")
    storage_gib = (raw.get("InstanceStorageInfo") or {}).get("TotalSizeInGB")
    return TypeInfo(
        vcpu=(raw.get("VCpuInfo") or {}).get("DefaultVCpus"),
        memory_mib=(raw.get("MemoryInfo") or {}).get("SizeInMiB"),
        architecture=archs[0],
        gpu_count=gpu_count,
        gpu_model=gpu_model,
        gpu_memory_mib=gpu_mem,
        instance_storage_gib=storage_gib,
        network_performance=(raw.get("NetworkInfo") or {}).get("NetworkPerformance"),
        is_current_generation=raw.get("CurrentGeneration"),
        is_burstable=raw.get("BurstablePerformanceSupported"),
        is_bare_metal=raw.get("BareMetal"),
    )


def map_volume(raw: dict) -> VolumeInfo:
    return VolumeInfo(
        volume_id=raw["VolumeId"],
        size_gib=raw.get("Size"),
        volume_type=raw.get("VolumeType"),
        encrypted=raw.get("Encrypted"),
        iops=raw.get("Iops"),
        throughput=raw.get("Throughput"),
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
    """Gather instances and the reference/AMI/volume metadata needed to load them."""
    data = Collected()

    for page in ec2.get_paginator("describe_instances").paginate():
        for reservation in page["Reservations"]:
            data.instances.extend(map_instance(i) for i in reservation["Instances"])

    referenced = {i.image_id for i in data.instances}
    for batch in _batches(referenced):
        for raw in _fetch_images(ec2, batch):
            data.amis[raw["ImageId"]] = map_ami(raw)

    for batch in _batches(i.instance_type for i in data.instances):
        for page in ec2.get_paginator("describe_instance_types").paginate(InstanceTypes=batch):
            for t in page["InstanceTypes"]:
                data.type_info[t["InstanceType"]] = map_type_info(t)

    volume_ids = {v.volume_id for i in data.instances for v in i.volumes}
    for batch in _batches(volume_ids):
        for page in ec2.get_paginator("describe_volumes").paginate(VolumeIds=batch):
            for v in page["Volumes"]:
                data.volume_info[v["VolumeId"]] = map_volume(v)

    vpc_ids = {i.vpc_id for i in data.instances if i.vpc_id}
    for batch in _batches(vpc_ids):
        for page in ec2.get_paginator("describe_vpcs").paginate(VpcIds=batch):
            data.vpc_cidrs.update({v["VpcId"]: v["CidrBlock"] for v in page["Vpcs"]})

    subnet_ids = {i.subnet_id for i in data.instances if i.subnet_id}
    for batch in _batches(subnet_ids):
        for page in ec2.get_paginator("describe_subnets").paginate(SubnetIds=batch):
            data.subnet_cidrs.update({s["SubnetId"]: s["CidrBlock"] for s in page["Subnets"]})

    return data
