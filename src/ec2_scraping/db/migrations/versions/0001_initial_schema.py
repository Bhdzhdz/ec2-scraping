"""Initial 3NF EC2 and AMI inventory schema.

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
    SCRAPE_STATUS_VALUES,
)

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE_OPTS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
UBigInt = mysql.BIGINT(unsigned=True)
UInt = mysql.INTEGER(unsigned=True)


def upgrade() -> None:
    op.create_table(
        "account",
        sa.Column("id", UBigInt, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("aws_account_id", mysql.CHAR(12), nullable=False),
        sa.Column("alias", sa.String(64), nullable=True),
        sa.UniqueConstraint("aws_account_id", name="uq_account_aws_id"),
        if_not_exists=True,
        **_TABLE_OPTS,
    )

    op.create_table(
        "region",
        sa.Column("id", UBigInt, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.UniqueConstraint("code", name="uq_region_code"),
        if_not_exists=True,
        **_TABLE_OPTS,
    )

    op.create_table(
        "availability_zone",
        sa.Column("id", UBigInt, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("region_id", UBigInt, nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["region_id"], ["region.id"], name="fk_az_region"),
        sa.UniqueConstraint("region_id", "name", name="uq_az_region_name"),
        if_not_exists=True,
        **_TABLE_OPTS,
    )

    op.create_table(
        "instance_type",
        sa.Column("id", UBigInt, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("vcpu", UInt, nullable=True),
        sa.Column("memory_mib", UInt, nullable=True),
        sa.Column("architecture", sa.String(16), nullable=True),
        sa.UniqueConstraint("name", name="uq_instance_type_name"),
        if_not_exists=True,
        **_TABLE_OPTS,
    )

    op.create_table(
        "key_pair",
        sa.Column("id", UBigInt, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("account_id", UBigInt, nullable=False),
        sa.Column("region_id", UBigInt, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], name="fk_key_pair_account"),
        sa.ForeignKeyConstraint(["region_id"], ["region.id"], name="fk_key_pair_region"),
        sa.UniqueConstraint("account_id", "region_id", "name", name="uq_key_pair"),
        if_not_exists=True,
        **_TABLE_OPTS,
    )

    op.create_table(
        "iam_instance_profile",
        sa.Column("id", UBigInt, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("account_id", UBigInt, nullable=False),
        sa.Column("region_id", UBigInt, nullable=False),
        sa.Column("arn", sa.String(255), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], name="fk_iam_profile_account"),
        sa.ForeignKeyConstraint(["region_id"], ["region.id"], name="fk_iam_profile_region"),
        sa.UniqueConstraint("account_id", "region_id", "arn", name="uq_iam_profile"),
        if_not_exists=True,
        **_TABLE_OPTS,
    )

    op.create_table(
        "vpc",
        sa.Column("id", UBigInt, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("account_id", UBigInt, nullable=False),
        sa.Column("region_id", UBigInt, nullable=False),
        sa.Column("vpc_id", sa.String(32), nullable=False),
        sa.Column("cidr", sa.String(43), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], name="fk_vpc_account"),
        sa.ForeignKeyConstraint(["region_id"], ["region.id"], name="fk_vpc_region"),
        sa.UniqueConstraint("account_id", "region_id", "vpc_id", name="uq_vpc"),
        if_not_exists=True,
        **_TABLE_OPTS,
    )

    op.create_table(
        "subnet",
        sa.Column("id", UBigInt, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("vpc_pk", UBigInt, nullable=False),
        sa.Column("availability_zone_id", UBigInt, nullable=False),
        sa.Column("subnet_id", sa.String(32), nullable=False),
        sa.Column("cidr", sa.String(43), nullable=True),
        sa.ForeignKeyConstraint(["vpc_pk"], ["vpc.id"], name="fk_subnet_vpc"),
        sa.ForeignKeyConstraint(
            ["availability_zone_id"], ["availability_zone.id"], name="fk_subnet_az"
        ),
        sa.UniqueConstraint("vpc_pk", "subnet_id", name="uq_subnet"),
        if_not_exists=True,
        **_TABLE_OPTS,
    )

    op.create_table(
        "security_group",
        sa.Column("id", UBigInt, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("vpc_pk", UBigInt, nullable=False),
        sa.Column("group_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(["vpc_pk"], ["vpc.id"], name="fk_sg_vpc"),
        sa.UniqueConstraint("vpc_pk", "group_id", name="uq_security_group"),
        if_not_exists=True,
        **_TABLE_OPTS,
    )

    op.create_table(
        "scrape_run",
        sa.Column("id", UBigInt, primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "started_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column(
            "status",
            mysql.ENUM(*SCRAPE_STATUS_VALUES),
            nullable=False,
            server_default=sa.text("'running'"),
        ),
        if_not_exists=True,
        **_TABLE_OPTS,
    )

    op.create_table(
        "scrape_run_scope",
        sa.Column("scrape_run_id", UBigInt, primary_key=True, nullable=False),
        sa.Column("account_id", UBigInt, primary_key=True, nullable=False),
        sa.Column("region_id", UBigInt, primary_key=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["scrape_run_id"], ["scrape_run.id"], name="fk_scope_run", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], name="fk_scope_account"),
        sa.ForeignKeyConstraint(["region_id"], ["region.id"], name="fk_scope_region"),
        if_not_exists=True,
        **_TABLE_OPTS,
    )

    op.create_table(
        "instance",
        sa.Column("id", UBigInt, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("account_id", UBigInt, nullable=False),
        sa.Column("region_id", UBigInt, nullable=False),
        sa.Column("instance_id", sa.String(32), nullable=False),
        sa.Column("instance_type_id", UBigInt, nullable=False),
        sa.Column("availability_zone_id", UBigInt, nullable=False),
        sa.Column("subnet_pk", UBigInt, nullable=True),
        sa.Column("key_pair_id", UBigInt, nullable=True),
        sa.Column("iam_instance_profile_id", UBigInt, nullable=True),
        sa.Column("image_id", sa.String(32), nullable=False),
        sa.Column("state", mysql.ENUM(*INSTANCE_STATE_VALUES), nullable=False),
        sa.Column("architecture", sa.String(16), nullable=False),
        sa.Column("platform", sa.String(32), nullable=True),
        sa.Column("launch_time", sa.DateTime(), nullable=False),
        sa.Column("private_ip", sa.String(45), nullable=True),
        sa.Column("public_ip", sa.String(45), nullable=True),
        sa.Column(
            "monitoring",
            mysql.ENUM(*MONITORING_VALUES),
            nullable=False,
            server_default=sa.text("'disabled'"),
        ),
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
        sa.Column("last_scrape_run_id", UBigInt, nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], name="fk_instance_account"),
        sa.ForeignKeyConstraint(["region_id"], ["region.id"], name="fk_instance_region"),
        sa.ForeignKeyConstraint(
            ["instance_type_id"], ["instance_type.id"], name="fk_instance_type"
        ),
        sa.ForeignKeyConstraint(
            ["availability_zone_id"], ["availability_zone.id"], name="fk_instance_az"
        ),
        sa.ForeignKeyConstraint(["subnet_pk"], ["subnet.id"], name="fk_instance_subnet"),
        sa.ForeignKeyConstraint(["key_pair_id"], ["key_pair.id"], name="fk_instance_key_pair"),
        sa.ForeignKeyConstraint(
            ["iam_instance_profile_id"], ["iam_instance_profile.id"], name="fk_instance_profile"
        ),
        sa.ForeignKeyConstraint(["last_scrape_run_id"], ["scrape_run.id"], name="fk_instance_run"),
        sa.UniqueConstraint("account_id", "region_id", "instance_id", name="uq_instance"),
        sa.Index("ix_instance_state", "state"),
        sa.Index("ix_instance_type", "instance_type_id"),
        sa.Index("ix_instance_image", "region_id", "image_id"),
        sa.Index("ix_instance_last_run", "last_scrape_run_id"),
        if_not_exists=True,
        **_TABLE_OPTS,
    )

    op.create_table(
        "instance_security_group",
        sa.Column("instance_pk", UBigInt, primary_key=True, nullable=False),
        sa.Column("security_group_pk", UBigInt, primary_key=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["instance_pk"], ["instance.id"], name="fk_isg_instance", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["security_group_pk"], ["security_group.id"], name="fk_isg_sg"),
        if_not_exists=True,
        **_TABLE_OPTS,
    )

    op.create_table(
        "instance_volume",
        sa.Column("id", UBigInt, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("instance_pk", UBigInt, nullable=False),
        sa.Column("device_name", sa.String(255), nullable=False),
        sa.Column("volume_id", sa.String(32), nullable=False),
        sa.Column("size_gib", UInt, nullable=True),
        sa.Column("volume_type", sa.String(16), nullable=True),
        sa.ForeignKeyConstraint(
            ["instance_pk"], ["instance.id"], name="fk_iv_instance", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("instance_pk", "device_name", name="uq_instance_volume"),
        if_not_exists=True,
        **_TABLE_OPTS,
    )

    op.create_table(
        "instance_network_interface",
        sa.Column("id", UBigInt, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("instance_pk", UBigInt, nullable=False),
        sa.Column("eni_id", sa.String(32), nullable=False),
        sa.Column("subnet_pk", UBigInt, nullable=True),
        sa.Column("private_ip", sa.String(45), nullable=True),
        sa.Column("public_ip", sa.String(45), nullable=True),
        sa.ForeignKeyConstraint(
            ["instance_pk"], ["instance.id"], name="fk_ini_instance", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["subnet_pk"], ["subnet.id"], name="fk_ini_subnet"),
        sa.UniqueConstraint("instance_pk", "eni_id", name="uq_instance_eni"),
        if_not_exists=True,
        **_TABLE_OPTS,
    )

    op.create_table(
        "instance_tag",
        sa.Column("instance_pk", UBigInt, primary_key=True, nullable=False),
        sa.Column("tag_key", sa.String(128), primary_key=True, nullable=False),
        sa.Column("tag_value", sa.String(256), nullable=False),
        sa.ForeignKeyConstraint(
            ["instance_pk"], ["instance.id"], name="fk_it_instance", ondelete="CASCADE"
        ),
        sa.Index("ix_instance_tag_kv", "tag_key", "tag_value"),
        if_not_exists=True,
        **_TABLE_OPTS,
    )

    op.create_table(
        "ami",
        sa.Column("id", UBigInt, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("account_id", UBigInt, nullable=False),
        sa.Column("region_id", UBigInt, nullable=False),
        sa.Column("image_id", sa.String(32), nullable=False),
        sa.Column("owner_aws_account_id", mysql.CHAR(12), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column("creation_date", sa.DateTime(), nullable=True),
        sa.Column("state", mysql.ENUM(*AMI_STATE_VALUES), nullable=False),
        sa.Column("architecture", sa.String(16), nullable=False),
        sa.Column("platform", sa.String(32), nullable=True),
        sa.Column("root_device_type", sa.String(16), nullable=False),
        sa.Column("virtualization_type", sa.String(16), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("deprecation_time", sa.DateTime(), nullable=True),
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
        sa.Column("last_scrape_run_id", UBigInt, nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], name="fk_ami_account"),
        sa.ForeignKeyConstraint(["region_id"], ["region.id"], name="fk_ami_region"),
        sa.ForeignKeyConstraint(["last_scrape_run_id"], ["scrape_run.id"], name="fk_ami_run"),
        sa.UniqueConstraint("account_id", "region_id", "image_id", name="uq_ami"),
        sa.Index("ix_ami_image", "region_id", "image_id"),
        sa.Index("ix_ami_owner", "owner_aws_account_id"),
        sa.Index("ix_ami_last_run", "last_scrape_run_id"),
        if_not_exists=True,
        **_TABLE_OPTS,
    )

    op.create_table(
        "ami_block_device_mapping",
        sa.Column("id", UBigInt, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("ami_pk", UBigInt, nullable=False),
        sa.Column("device_name", sa.String(255), nullable=False),
        sa.Column("snapshot_id", sa.String(32), nullable=True),
        sa.Column("size_gib", UInt, nullable=True),
        sa.ForeignKeyConstraint(["ami_pk"], ["ami.id"], name="fk_bdm_ami", ondelete="CASCADE"),
        sa.UniqueConstraint("ami_pk", "device_name", name="uq_ami_bdm"),
        if_not_exists=True,
        **_TABLE_OPTS,
    )

    op.create_table(
        "ami_tag",
        sa.Column("ami_pk", UBigInt, primary_key=True, nullable=False),
        sa.Column("tag_key", sa.String(128), primary_key=True, nullable=False),
        sa.Column("tag_value", sa.String(256), nullable=False),
        sa.ForeignKeyConstraint(["ami_pk"], ["ami.id"], name="fk_at_ami", ondelete="CASCADE"),
        sa.Index("ix_ami_tag_kv", "tag_key", "tag_value"),
        if_not_exists=True,
        **_TABLE_OPTS,
    )


def downgrade() -> None:
    for table in (
        "ami_tag",
        "ami_block_device_mapping",
        "ami",
        "instance_tag",
        "instance_network_interface",
        "instance_volume",
        "instance_security_group",
        "instance",
        "scrape_run_scope",
        "scrape_run",
        "security_group",
        "subnet",
        "vpc",
        "iam_instance_profile",
        "key_pair",
        "instance_type",
        "availability_zone",
        "region",
        "account",
    ):
        op.drop_table(table, if_exists=True)
