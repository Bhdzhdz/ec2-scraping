"""Paginated, read-only EC2 Describe* collection mapped to plain dataclasses."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

type RawDict = dict[str, Any]

BATCH = 100
_TOLERATED = {
    "InvalidAMIID.Malformed",
    "InvalidAMIID.NotFound",
    "InvalidAMIID.Unavailable",
    "InvalidInstanceType",
    "InvalidSubnetID.NotFound",
    "InvalidVolume.NotFound",
    "InvalidVpcID.NotFound",
}


def _naive_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.replace(microsecond=0)


def _tags(items: list[RawDict] | None) -> dict[str, str]:
    return {t["Key"]: t.get("Value", "") for t in items or []}


def _batches[T: str](values: Iterable[T], size: int = BATCH) -> Iterator[list[T]]:
    ordered = sorted(set(values))
    for i in range(0, len(ordered), size):
        yield ordered[i : i + size]


def _map_nics(raw_nics: list[RawDict]) -> list[NetworkInterfaceRecord]:
    return [
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
        for n in raw_nics
    ]


def _map_volumes(raw_bdms: list[RawDict]) -> list[VolumeAttachment]:
    return [
        VolumeAttachment(
            device_name=b["DeviceName"],
            volume_id=b["Ebs"]["VolumeId"],
            delete_on_termination=b["Ebs"].get("DeleteOnTermination"),
        )
        for b in raw_bdms
        if b.get("Ebs") and b["Ebs"].get("VolumeId")
    ]


def _first_ipv6(raw: RawDict, nics: list[NetworkInterfaceRecord]) -> str | None:
    if ipv6 := raw.get("Ipv6Address"):
        return ipv6
    for nic in nics:
        if nic.ipv6_addresses:
            return nic.ipv6_addresses[0]
    return None


def _opt_str(value: str | None, default: str | None = None) -> str | None:
    return value or default


def _sub_get(raw: RawDict, key: str, subkey: str, default: Any = None) -> Any:
    sub = raw.get(key)
    return sub.get(subkey, default) if sub else default


def _monitoring_state(raw: RawDict) -> str:
    state = _sub_get(raw, "Monitoring", "State", "disabled")
    return state if state in ("disabled", "enabled", "pending") else "disabled"


def map_instance(raw: RawDict) -> InstanceRecord:
    nics = _map_nics(raw.get("NetworkInterfaces", []))
    volumes = _map_volumes(raw.get("BlockDeviceMappings", []))
    tags = _tags(raw.get("Tags"))
    placement = raw["Placement"]
    cpu_opts = raw.get("CpuOptions", {})
    imds = raw.get("MetadataOptions", {})
    launch_time = _naive_utc(raw["LaunchTime"])
    if launch_time is None:
        msg = "LaunchTime is required"
        raise ValueError(msg)

    return InstanceRecord(
        instance_id=raw["InstanceId"],
        instance_type=raw["InstanceType"],
        availability_zone=placement["AvailabilityZone"],
        image_id=raw["ImageId"],
        state=raw["State"]["Name"],
        architecture=raw.get("Architecture", "unknown"),
        launch_time=launch_time,
        name=tags.get("Name"),
        state_reason_code=_sub_get(raw, "StateReason", "Code"),
        state_transition_reason=_opt_str(raw.get("StateTransitionReason")),
        lifecycle=_opt_str(raw.get("InstanceLifecycle"), "on-demand") or "on-demand",
        spot_instance_request_id=raw.get("SpotInstanceRequestId"),
        capacity_reservation_id=raw.get("CapacityReservationId"),
        tenancy=_opt_str(placement.get("Tenancy"), "default") or "default",
        placement_group=_opt_str(placement.get("GroupName")),
        host_id=placement.get("HostId"),
        usage_operation=raw.get("UsageOperation"),
        monitoring=_monitoring_state(raw),
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
        ipv6_address=_first_ipv6(raw, nics),
        private_dns_name=_opt_str(raw.get("PrivateDnsName")),
        public_dns_name=_opt_str(raw.get("PublicDnsName")),
        source_dest_check=raw.get("SourceDestCheck"),
        ebs_optimized=bool(raw.get("EbsOptimized", False)),
        root_device_type=raw.get("RootDeviceType"),
        root_device_name=raw.get("RootDeviceName"),
        key_name=raw.get("KeyName"),
        iam_profile_arn=_sub_get(raw, "IamInstanceProfile", "Arn"),
        imds_http_tokens=imds.get("HttpTokens"),
        imds_http_endpoint=imds.get("HttpEndpoint"),
        imds_hop_limit=imds.get("HttpPutResponseHopLimit"),
        imds_instance_metadata_tags=imds.get("InstanceMetadataTags"),
        tags=tags,
        security_groups=[(g["GroupId"], g.get("GroupName")) for g in raw.get("SecurityGroups", [])],
        volumes=volumes,
        network_interfaces=nics,
    )


def map_ami(raw: RawDict) -> AmiRecord:
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


def _gpu_summary(gpu_info: RawDict | None) -> tuple[int | None, str | None, int | None]:
    if not gpu_info:
        return None, None, None
    gpus = gpu_info.get("Gpus") or []
    gpu_count = sum(g.get("Count", 0) for g in gpus) if gpus else None
    models = [
        f"{g.get('Manufacturer', '')} {g.get('Name', '')}".strip()
        for g in gpus
        if g.get("Manufacturer") or g.get("Name")
    ]
    gpu_model = ", ".join(dict.fromkeys(models)) if models else None
    return gpu_count, gpu_model, gpu_info.get("TotalGpuMemoryInMiB")


def map_type_info(raw: RawDict) -> TypeInfo:
    archs = (raw.get("ProcessorInfo") or {}).get("SupportedArchitectures") or [None]
    gpu_count, gpu_model, gpu_mem = _gpu_summary(raw.get("GpuInfo"))
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


def map_volume(raw: RawDict) -> VolumeInfo:
    return VolumeInfo(
        volume_id=raw["VolumeId"],
        size_gib=raw.get("Size"),
        volume_type=raw.get("VolumeType"),
        encrypted=raw.get("Encrypted"),
        iops=raw.get("Iops"),
        throughput=raw.get("Throughput"),
    )


def _error_code(exc: ClientError) -> str | None:
    return exc.response.get("Error", {}).get("Code")


def _fetch_batch(
    ec2: Any,
    operation: str,
    param_name: str,
    result_key: str,
    items: list[str],
) -> list[RawDict]:
    """Describe a batch of resource IDs; fall back to single-item calls on tolerated errors."""

    def _call(ids: list[str]) -> list[RawDict]:
        out: list[RawDict] = []
        for page in ec2.get_paginator(operation).paginate(**{param_name: ids}):
            out.extend(page.get(result_key, []))
        return out

    try:
        return _call(items)
    except ClientError as exc:
        if _error_code(exc) not in _TOLERATED:
            raise
    found: list[RawDict] = []
    for item in items:
        try:
            found.extend(_call([item]))
        except ClientError as exc:
            if _error_code(exc) not in _TOLERATED:
                raise
    return found


def _fetch_images(ec2: Any, image_ids: list[str]) -> list[RawDict]:
    """Describe referenced AMIs; tolerate ones that are missing or not visible."""
    try:
        return ec2.describe_images(ImageIds=image_ids).get("Images", [])
    except ClientError as exc:
        if _error_code(exc) not in _TOLERATED:
            raise
    found: list[RawDict] = []
    for image_id in image_ids:
        try:
            found.extend(ec2.describe_images(ImageIds=[image_id]).get("Images", []))
        except ClientError as exc:
            if _error_code(exc) not in _TOLERATED:
                raise
    return found


def _collect_all_batches(
    ec2: Any,
    operation: str,
    param_name: str,
    result_key: str,
    ids: Iterable[str],
) -> Iterator[RawDict]:
    for batch in _batches(ids):
        yield from _fetch_batch(ec2, operation, param_name, result_key, batch)


def _collect_instances(ec2: Any) -> list[InstanceRecord]:
    instances: list[InstanceRecord] = []
    for page in ec2.get_paginator("describe_instances").paginate():
        for reservation in page["Reservations"]:
            instances.extend(map_instance(i) for i in reservation["Instances"])
    return instances


def _collect_amis(ec2: Any, instances: list[InstanceRecord]) -> dict[str, AmiRecord]:
    return {
        raw["ImageId"]: map_ami(raw)
        for batch in _batches(i.image_id for i in instances)
        for raw in _fetch_images(ec2, batch)
    }


def _collect_vpc_cidrs(ec2: Any, ids: list[str]) -> dict[str, str]:
    return {
        v["VpcId"]: v["CidrBlock"]
        for v in _collect_all_batches(ec2, "describe_vpcs", "VpcIds", "Vpcs", ids)
    }


def _collect_subnet_cidrs(ec2: Any, ids: list[str]) -> dict[str, str]:
    return {
        s["SubnetId"]: s["CidrBlock"]
        for s in _collect_all_batches(ec2, "describe_subnets", "SubnetIds", "Subnets", ids)
    }


def collect(ec2: Any, _account_id: str = "") -> Collected:
    """Gather instances and the reference/AMI/volume metadata needed to load them."""
    instances = _collect_instances(ec2)
    amis = _collect_amis(ec2, instances)
    type_ids = [i.instance_type for i in instances]
    vol_ids = [v.volume_id for i in instances for v in i.volumes]
    vpc_ids = [i.vpc_id for i in instances if i.vpc_id]
    sub_ids = [i.subnet_id for i in instances if i.subnet_id]
    type_info = {
        t["InstanceType"]: map_type_info(t)
        for t in _collect_all_batches(
            ec2, "describe_instance_types", "InstanceTypes", "InstanceTypes", type_ids
        )
    }
    volume_info = {
        v["VolumeId"]: map_volume(v)
        for v in _collect_all_batches(ec2, "describe_volumes", "VolumeIds", "Volumes", vol_ids)
    }
    return Collected(
        instances=instances,
        amis=amis,
        type_info=type_info,
        volume_info=volume_info,
        vpc_cidrs=_collect_vpc_cidrs(ec2, vpc_ids),
        subnet_cidrs=_collect_subnet_cidrs(ec2, sub_ids),
    )
