"""SQLAlchemy 2.0 Declarative ORM model for the wide analytics EC2 instance inventory schema."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import CHAR, ENUM
from sqlalchemy.orm import Mapped, mapped_column

from ec2_scraping.db.base import Base, UBigInt, UInt

_TABLE_DEFAULTS: dict[str, str] = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

INSTANCE_STATE_VALUES = (
    "pending",
    "running",
    "shutting-down",
    "terminated",
    "stopping",
    "stopped",
)
MONITORING_VALUES = ("disabled", "enabled", "pending")
AMI_STATE_VALUES = (
    "pending",
    "available",
    "invalid",
    "deregistered",
    "transient",
    "failed",
    "error",
    "disabled",
)


class Instance(Base):
    """Wide analytical EC2 instance inventory row (one row per instance on a single table)."""

    __tablename__ = "instance"
    __table_args__ = (
        UniqueConstraint("aws_account_id", "region", "instance_id", name="uq_instance"),
        Index("ix_instance_state", "state"),
        Index("ix_instance_type", "instance_type"),
        Index("ix_instance_image", "region", "image_id"),
        Index("ix_instance_vpc", "region", "vpc_id"),
        Index("ix_instance_last_seen", "last_seen_at"),
        _TABLE_DEFAULTS,
    )

    # 1. Identity & Placement
    id: Mapped[int] = mapped_column(UBigInt, primary_key=True, autoincrement=True)
    aws_account_id: Mapped[str] = mapped_column(CHAR(12), nullable=False)
    region: Mapped[str] = mapped_column(String(32), nullable=False)
    availability_zone: Mapped[str] = mapped_column(String(32), nullable=False)
    instance_id: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # 2. State, Lifecycle & Scheduling
    state: Mapped[str] = mapped_column(ENUM(*INSTANCE_STATE_VALUES), nullable=False)
    state_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state_transition_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lifecycle: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'on-demand'")
    )
    spot_instance_request_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    capacity_reservation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tenancy: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'default'")
    )
    placement_group: Mapped[str | None] = mapped_column(String(255), nullable=True)
    host_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    launch_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    usage_operation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    monitoring: Mapped[str] = mapped_column(
        ENUM(*MONITORING_VALUES), nullable=False, server_default=text("'disabled'")
    )

    # 3. Compute, Hardware & Instance Type Specs
    instance_type: Mapped[str] = mapped_column(String(32), nullable=False)
    instance_family: Mapped[str | None] = mapped_column(String(32), nullable=True)
    architecture: Mapped[str] = mapped_column(String(16), nullable=False)
    vcpu: Mapped[int | None] = mapped_column(UInt, nullable=True)
    cpu_core_count: Mapped[int | None] = mapped_column(UInt, nullable=True)
    cpu_threads_per_core: Mapped[int | None] = mapped_column(UInt, nullable=True)
    memory_mib: Mapped[int | None] = mapped_column(UInt, nullable=True)
    gpu_count: Mapped[int | None] = mapped_column(UInt, nullable=True)
    gpu_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gpu_memory_mib: Mapped[int | None] = mapped_column(UInt, nullable=True)
    instance_storage_gib: Mapped[int | None] = mapped_column(UInt, nullable=True)
    network_performance: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_current_generation: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_burstable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_bare_metal: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    hypervisor: Mapped[str | None] = mapped_column(String(16), nullable=True)
    virtualization_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ena_support: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    sriov_net_support: Mapped[str | None] = mapped_column(String(16), nullable=True)
    boot_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tpm_support: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 4. OS & AMI Metadata
    platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    platform_details: Mapped[str | None] = mapped_column(String(64), nullable=True)
    image_id: Mapped[str] = mapped_column(String(32), nullable=False)
    ami_owner_aws_account_id: Mapped[str | None] = mapped_column(CHAR(12), nullable=True)
    ami_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ami_description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    ami_creation_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ami_state: Mapped[str | None] = mapped_column(ENUM(*AMI_STATE_VALUES), nullable=True)
    ami_architecture: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ami_platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ami_platform_details: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ami_root_device_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ami_virtualization_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ami_is_public: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ami_deprecation_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 5. Networking
    vpc_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    vpc_cidr: Mapped[str | None] = mapped_column(String(43), nullable=True)
    subnet_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subnet_cidr: Mapped[str | None] = mapped_column(String(43), nullable=True)
    private_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    public_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    ipv6_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    private_dns_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    public_dns_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_dest_check: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    eni_count: Mapped[int] = mapped_column(UInt, nullable=False, server_default=text("0"))
    security_group_count: Mapped[int] = mapped_column(
        UInt, nullable=False, server_default=text("0")
    )

    # 6. Storage & EBS Rollups
    ebs_optimized: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    root_device_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    root_device_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    root_volume_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    root_volume_size_gib: Mapped[int | None] = mapped_column(UInt, nullable=True)
    root_volume_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    root_volume_encrypted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ebs_volume_count: Mapped[int] = mapped_column(UInt, nullable=False, server_default=text("0"))
    ebs_total_size_gib: Mapped[int] = mapped_column(UInt, nullable=False, server_default=text("0"))
    ebs_all_encrypted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # 7. Security & Metadata Posture
    key_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    iam_instance_profile_arn: Mapped[str | None] = mapped_column(String(255), nullable=True)
    iam_instance_profile_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    imds_http_tokens: Mapped[str | None] = mapped_column(String(16), nullable=True)
    imds_http_endpoint: Mapped[str | None] = mapped_column(String(16), nullable=True)
    imds_hop_limit: Mapped[int | None] = mapped_column(UInt, nullable=True)
    imds_instance_metadata_tags: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # 8. Multi-Valued AWS Data (JSON)
    tags: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    security_groups: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    volumes: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    network_interfaces: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    # 9. SSH & Pluggable Enrichment Columns
    ssh_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ssh_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ssh_host: Mapped[str | None] = mapped_column(String(45), nullable=True)
    ssh_port: Mapped[int | None] = mapped_column(UInt, nullable=True)
    ssh_os_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ssh_os_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ssh_os_pretty_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssh_kernel: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ssh_hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssh_uptime_seconds: Mapped[int | None] = mapped_column(UBigInt, nullable=True)
    ssh_package_count: Mapped[int | None] = mapped_column(UInt, nullable=True)
    ssh_listening_port_count: Mapped[int | None] = mapped_column(UInt, nullable=True)
    ssh_container_count: Mapped[int | None] = mapped_column(UInt, nullable=True)
    ssh_reboot_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ssh_facts: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ssh_collected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ssh_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_facts: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # 10. Observation Timestamps
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
