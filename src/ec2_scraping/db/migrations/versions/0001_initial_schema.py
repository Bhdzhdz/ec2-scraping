"""Initial single-table wide analytics EC2 instance inventory schema.

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-10-16 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

from ec2_scraping.db.models import (
    AMI_STATE_VALUES,
    INSTANCE_STATE_VALUES,
    MONITORING_VALUES,
)

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE_OPTS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
UBigInt = mysql.BIGINT(unsigned=True)
UInt = mysql.INTEGER(unsigned=True)

VIEW_NAME = "v_instance_analytics"
CREATE_VIEW_SQL = f"""
CREATE OR REPLACE VIEW {VIEW_NAME} AS
SELECT
    i.*,
    TIMESTAMPDIFF(DAY, i.launch_time, i.last_seen_at) AS instance_age_days,
    TIMESTAMPDIFF(DAY, i.ami_creation_date, i.last_seen_at) AS ami_age_days,
    (i.public_ip IS NOT NULL) AS has_public_ip,
    (i.imds_http_tokens = 'required') AS is_imdsv2_enforced,
    (i.ssh_status = 'succeeded') AS is_ssh_accessible
FROM instance i
"""


def upgrade() -> None:
    op.create_table(
        "instance",
        sa.Column("id", UBigInt, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("aws_account_id", mysql.CHAR(12), nullable=False),
        sa.Column("region", sa.String(32), nullable=False),
        sa.Column("availability_zone", sa.String(32), nullable=False),
        sa.Column("instance_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(256), nullable=True),
        sa.Column("state", mysql.ENUM(*INSTANCE_STATE_VALUES), nullable=False),
        sa.Column("state_reason_code", sa.String(64), nullable=True),
        sa.Column("state_transition_reason", sa.String(255), nullable=True),
        sa.Column(
            "lifecycle",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'on-demand'"),
        ),
        sa.Column("spot_instance_request_id", sa.String(32), nullable=True),
        sa.Column("capacity_reservation_id", sa.String(32), nullable=True),
        sa.Column(
            "tenancy",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'default'"),
        ),
        sa.Column("placement_group", sa.String(255), nullable=True),
        sa.Column("host_id", sa.String(32), nullable=True),
        sa.Column("launch_time", sa.DateTime(), nullable=False),
        sa.Column("usage_operation", sa.String(64), nullable=True),
        sa.Column(
            "monitoring",
            mysql.ENUM(*MONITORING_VALUES),
            nullable=False,
            server_default=sa.text("'disabled'"),
        ),
        sa.Column("instance_type", sa.String(32), nullable=False),
        sa.Column("instance_family", sa.String(32), nullable=True),
        sa.Column("architecture", sa.String(16), nullable=False),
        sa.Column("vcpu", UInt, nullable=True),
        sa.Column("cpu_core_count", UInt, nullable=True),
        sa.Column("cpu_threads_per_core", UInt, nullable=True),
        sa.Column("memory_mib", UInt, nullable=True),
        sa.Column("gpu_count", UInt, nullable=True),
        sa.Column("gpu_model", sa.String(64), nullable=True),
        sa.Column("gpu_memory_mib", UInt, nullable=True),
        sa.Column("instance_storage_gib", UInt, nullable=True),
        sa.Column("network_performance", sa.String(64), nullable=True),
        sa.Column("is_current_generation", sa.Boolean(), nullable=True),
        sa.Column("is_burstable", sa.Boolean(), nullable=True),
        sa.Column("is_bare_metal", sa.Boolean(), nullable=True),
        sa.Column("hypervisor", sa.String(16), nullable=True),
        sa.Column("virtualization_type", sa.String(16), nullable=True),
        sa.Column("ena_support", sa.Boolean(), nullable=True),
        sa.Column("sriov_net_support", sa.String(16), nullable=True),
        sa.Column("boot_mode", sa.String(32), nullable=True),
        sa.Column("tpm_support", sa.String(32), nullable=True),
        sa.Column("platform", sa.String(32), nullable=True),
        sa.Column("platform_details", sa.String(64), nullable=True),
        sa.Column("image_id", sa.String(32), nullable=False),
        sa.Column("ami_owner_aws_account_id", mysql.CHAR(12), nullable=True),
        sa.Column("ami_name", sa.String(255), nullable=True),
        sa.Column("ami_description", sa.String(1024), nullable=True),
        sa.Column("ami_creation_date", sa.DateTime(), nullable=True),
        sa.Column("ami_state", mysql.ENUM(*AMI_STATE_VALUES), nullable=True),
        sa.Column("ami_architecture", sa.String(16), nullable=True),
        sa.Column("ami_platform", sa.String(32), nullable=True),
        sa.Column("ami_platform_details", sa.String(64), nullable=True),
        sa.Column("ami_root_device_type", sa.String(16), nullable=True),
        sa.Column("ami_virtualization_type", sa.String(16), nullable=True),
        sa.Column("ami_is_public", sa.Boolean(), nullable=True),
        sa.Column("ami_deprecation_time", sa.DateTime(), nullable=True),
        sa.Column("vpc_id", sa.String(32), nullable=True),
        sa.Column("vpc_cidr", sa.String(43), nullable=True),
        sa.Column("subnet_id", sa.String(32), nullable=True),
        sa.Column("subnet_cidr", sa.String(43), nullable=True),
        sa.Column("private_ip", sa.String(45), nullable=True),
        sa.Column("public_ip", sa.String(45), nullable=True),
        sa.Column("ipv6_address", sa.String(45), nullable=True),
        sa.Column("private_dns_name", sa.String(255), nullable=True),
        sa.Column("public_dns_name", sa.String(255), nullable=True),
        sa.Column("source_dest_check", sa.Boolean(), nullable=True),
        sa.Column("eni_count", UInt, nullable=False, server_default=sa.text("0")),
        sa.Column("security_group_count", UInt, nullable=False, server_default=sa.text("0")),
        sa.Column("ebs_optimized", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("root_device_type", sa.String(16), nullable=True),
        sa.Column("root_device_name", sa.String(64), nullable=True),
        sa.Column("root_volume_id", sa.String(32), nullable=True),
        sa.Column("root_volume_size_gib", UInt, nullable=True),
        sa.Column("root_volume_type", sa.String(16), nullable=True),
        sa.Column("root_volume_encrypted", sa.Boolean(), nullable=True),
        sa.Column("ebs_volume_count", UInt, nullable=False, server_default=sa.text("0")),
        sa.Column("ebs_total_size_gib", UInt, nullable=False, server_default=sa.text("0")),
        sa.Column("ebs_all_encrypted", sa.Boolean(), nullable=True),
        sa.Column("key_name", sa.String(255), nullable=True),
        sa.Column("iam_instance_profile_arn", sa.String(255), nullable=True),
        sa.Column("iam_instance_profile_name", sa.String(128), nullable=True),
        sa.Column("imds_http_tokens", sa.String(16), nullable=True),
        sa.Column("imds_http_endpoint", sa.String(16), nullable=True),
        sa.Column("imds_hop_limit", UInt, nullable=True),
        sa.Column("imds_instance_metadata_tags", sa.String(16), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("security_groups", sa.JSON(), nullable=True),
        sa.Column("volumes", sa.JSON(), nullable=True),
        sa.Column("network_interfaces", sa.JSON(), nullable=True),
        sa.Column("ssh_status", sa.String(32), nullable=True),
        sa.Column("ssh_user", sa.String(64), nullable=True),
        sa.Column("ssh_host", sa.String(45), nullable=True),
        sa.Column("ssh_port", UInt, nullable=True),
        sa.Column("ssh_os_id", sa.String(64), nullable=True),
        sa.Column("ssh_os_version", sa.String(64), nullable=True),
        sa.Column("ssh_os_pretty_name", sa.String(255), nullable=True),
        sa.Column("ssh_kernel", sa.String(128), nullable=True),
        sa.Column("ssh_hostname", sa.String(255), nullable=True),
        sa.Column("ssh_uptime_seconds", UBigInt, nullable=True),
        sa.Column("ssh_package_count", UInt, nullable=True),
        sa.Column("ssh_listening_port_count", UInt, nullable=True),
        sa.Column("ssh_container_count", UInt, nullable=True),
        sa.Column("ssh_reboot_required", sa.Boolean(), nullable=True),
        sa.Column("ssh_facts", sa.JSON(), nullable=True),
        sa.Column("ssh_collected_at", sa.DateTime(), nullable=True),
        sa.Column("ssh_error", sa.Text(), nullable=True),
        sa.Column("extra_facts", sa.JSON(), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("aws_account_id", "region", "instance_id", name="uq_instance"),
        sa.Index("ix_instance_state", "state"),
        sa.Index("ix_instance_type", "instance_type"),
        sa.Index("ix_instance_image", "region", "image_id"),
        sa.Index("ix_instance_vpc", "region", "vpc_id"),
        sa.Index("ix_instance_last_seen", "last_seen_at"),
        if_not_exists=True,
        **_TABLE_OPTS,
    )
    op.execute(CREATE_VIEW_SQL)


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {VIEW_NAME}")
    op.drop_table("instance", if_exists=True)
