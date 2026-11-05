"""Plain data holders passed between collection, loading, enrichment and the runner."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class Target:
    profile: str
    region: str


@dataclass(frozen=True)
class VolumeAttachment:
    device_name: str
    volume_id: str
    delete_on_termination: bool | None = None


@dataclass(frozen=True)
class VolumeInfo:
    volume_id: str
    size_gib: int | None = None
    volume_type: str | None = None
    encrypted: bool | None = None
    iops: int | None = None
    throughput: int | None = None


@dataclass(frozen=True)
class NetworkInterfaceRecord:
    eni_id: str
    subnet_id: str | None = None
    private_ip: str | None = None
    public_ip: str | None = None
    mac_address: str | None = None
    ipv6_addresses: list[str] = field(default_factory=list)


@dataclass
class InstanceRecord:
    instance_id: str
    instance_type: str
    availability_zone: str
    image_id: str
    state: str
    architecture: str
    launch_time: datetime
    name: str | None = None
    state_reason_code: str | None = None
    state_transition_reason: str | None = None
    lifecycle: str = "on-demand"
    spot_instance_request_id: str | None = None
    capacity_reservation_id: str | None = None
    tenancy: str = "default"
    placement_group: str | None = None
    host_id: str | None = None
    usage_operation: str | None = None
    monitoring: str = "disabled"
    cpu_core_count: int | None = None
    cpu_threads_per_core: int | None = None
    hypervisor: str | None = None
    virtualization_type: str | None = None
    ena_support: bool | None = None
    sriov_net_support: str | None = None
    boot_mode: str | None = None
    tpm_support: str | None = None
    platform: str | None = None
    platform_details: str | None = None
    vpc_id: str | None = None
    subnet_id: str | None = None
    private_ip: str | None = None
    public_ip: str | None = None
    ipv6_address: str | None = None
    private_dns_name: str | None = None
    public_dns_name: str | None = None
    source_dest_check: bool | None = None
    ebs_optimized: bool = False
    root_device_type: str | None = None
    root_device_name: str | None = None
    key_name: str | None = None
    iam_profile_arn: str | None = None
    imds_http_tokens: str | None = None
    imds_http_endpoint: str | None = None
    imds_hop_limit: int | None = None
    imds_instance_metadata_tags: str | None = None
    tags: dict[str, str] = field(default_factory=dict)
    security_groups: list[tuple[str, str | None]] = field(default_factory=list)
    volumes: list[VolumeAttachment] = field(default_factory=list)
    network_interfaces: list[NetworkInterfaceRecord] = field(default_factory=list)


@dataclass
class AmiRecord:
    image_id: str
    owner_aws_account_id: str
    state: str
    architecture: str
    root_device_type: str
    virtualization_type: str
    name: str | None = None
    description: str | None = None
    creation_date: datetime | None = None
    platform: str | None = None
    platform_details: str | None = None
    is_public: bool = False
    deprecation_time: datetime | None = None


@dataclass(frozen=True)
class TypeInfo:
    vcpu: int | None = None
    memory_mib: int | None = None
    architecture: str | None = None
    gpu_count: int | None = None
    gpu_model: str | None = None
    gpu_memory_mib: int | None = None
    instance_storage_gib: int | None = None
    network_performance: str | None = None
    is_current_generation: bool | None = None
    is_burstable: bool | None = None
    is_bare_metal: bool | None = None


@dataclass
class Collected:
    """Everything gathered for one profile/region combination."""

    instances: list[InstanceRecord] = field(default_factory=list)
    amis: dict[str, AmiRecord] = field(default_factory=dict)
    type_info: dict[str, TypeInfo] = field(default_factory=dict)
    volume_info: dict[str, VolumeInfo] = field(default_factory=dict)
    vpc_cidrs: dict[str, str] = field(default_factory=dict)
    subnet_cidrs: dict[str, str] = field(default_factory=dict)


@dataclass
class EnrichmentResult:
    """Payload returned by an instance enricher (e.g. SSH collector)."""

    status: str  # succeeded | failed | skipped
    facts: dict[str, Any] | None = None
    error: str | None = None


class InstanceEnricher(Protocol):
    """Strategy interface for post-AWS instance data collection (e.g. SSH, SSM)."""

    name: str  # e.g. "ssh" or custom key stored under extra_facts[name]

    def enrich(
        self, aws_account_id: str, region: str, instance: InstanceRecord
    ) -> EnrichmentResult: ...


@dataclass
class Counts:
    created: int = 0
    updated: int = 0
    unchanged: int = 0

    def add(self, outcome: str) -> None:
        setattr(self, outcome, getattr(self, outcome) + 1)


@dataclass
class ComboResult:
    profile: str
    region: str | None
    status: str  # succeeded | failed | skipped
    error: str | None = None
    instances: Counts = field(default_factory=Counts)


@dataclass
class RunResult:
    status: str  # succeeded | partial | failed
    combos: list[ComboResult] = field(default_factory=list)
