"""Plain data holders passed between collection, loading and the runner."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Target:
    profile: str
    region: str


@dataclass(frozen=True)
class VolumeRecord:
    device_name: str
    volume_id: str


@dataclass(frozen=True)
class NetworkInterfaceRecord:
    eni_id: str
    subnet_id: str | None = None
    private_ip: str | None = None
    public_ip: str | None = None


@dataclass(frozen=True)
class BlockMapping:
    device_name: str
    snapshot_id: str | None = None
    size_gib: int | None = None


@dataclass
class InstanceRecord:
    instance_id: str
    instance_type: str
    availability_zone: str
    image_id: str
    state: str
    architecture: str
    launch_time: datetime
    vpc_id: str | None = None
    subnet_id: str | None = None
    key_name: str | None = None
    iam_profile_arn: str | None = None
    platform: str | None = None
    private_ip: str | None = None
    public_ip: str | None = None
    monitoring: str = "disabled"
    tags: dict[str, str] = field(default_factory=dict)
    security_groups: list[tuple[str, str | None]] = field(default_factory=list)
    volumes: list[VolumeRecord] = field(default_factory=list)
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
    is_public: bool = False
    deprecation_time: datetime | None = None
    tags: dict[str, str] = field(default_factory=dict)
    block_mappings: list[BlockMapping] = field(default_factory=list)


@dataclass(frozen=True)
class TypeInfo:
    vcpu: int | None = None
    memory_mib: int | None = None
    architecture: str | None = None


@dataclass
class Collected:
    """Everything gathered for one profile/region combination."""

    instances: list[InstanceRecord] = field(default_factory=list)
    amis: list[AmiRecord] = field(default_factory=list)
    type_info: dict[str, TypeInfo] = field(default_factory=dict)
    vpc_cidrs: dict[str, str] = field(default_factory=dict)
    subnet_cidrs: dict[str, str] = field(default_factory=dict)
    sg_names: dict[str, str] = field(default_factory=dict)


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
    amis: Counts = field(default_factory=Counts)


@dataclass
class RunResult:
    run_id: int
    status: str  # succeeded | partial | failed
    combos: list[ComboResult] = field(default_factory=list)
