"""SQLAlchemy 2.0 Declarative ORM models for the 3NF EC2 and AMI inventory schema."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import CHAR, ENUM
from sqlalchemy.orm import Mapped, mapped_column

from ec2_scraping.db.base import Base, UBigInt, UInt

_TABLE_DEFAULTS: dict[str, str] = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

SCRAPE_STATUS_VALUES = ("running", "succeeded", "failed", "partial")
SCRAPE_SCOPE_STATUS_VALUES = ("succeeded", "failed", "skipped")
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


class Account(Base):
    __tablename__ = "account"
    __table_args__ = (
        UniqueConstraint("aws_account_id", name="uq_account_aws_id"),
        _TABLE_DEFAULTS,
    )

    id: Mapped[int] = mapped_column(UBigInt, primary_key=True, autoincrement=True)
    aws_account_id: Mapped[str] = mapped_column(CHAR(12), nullable=False)
    alias: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Region(Base):
    __tablename__ = "region"
    __table_args__ = (
        UniqueConstraint("code", name="uq_region_code"),
        _TABLE_DEFAULTS,
    )

    id: Mapped[int] = mapped_column(UBigInt, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)


class AvailabilityZone(Base):
    __tablename__ = "availability_zone"
    __table_args__ = (
        UniqueConstraint("region_id", "name", name="uq_az_region_name"),
        _TABLE_DEFAULTS,
    )

    id: Mapped[int] = mapped_column(UBigInt, primary_key=True, autoincrement=True)
    region_id: Mapped[int] = mapped_column(
        UBigInt, ForeignKey("region.id", name="fk_az_region"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(32), nullable=False)


class InstanceType(Base):
    __tablename__ = "instance_type"
    __table_args__ = (
        UniqueConstraint("name", name="uq_instance_type_name"),
        _TABLE_DEFAULTS,
    )

    id: Mapped[int] = mapped_column(UBigInt, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    vcpu: Mapped[int | None] = mapped_column(UInt, nullable=True)
    memory_mib: Mapped[int | None] = mapped_column(UInt, nullable=True)
    architecture: Mapped[str | None] = mapped_column(String(16), nullable=True)


class KeyPair(Base):
    __tablename__ = "key_pair"
    __table_args__ = (
        UniqueConstraint("account_id", "region_id", "name", name="uq_key_pair"),
        _TABLE_DEFAULTS,
    )

    id: Mapped[int] = mapped_column(UBigInt, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        UBigInt, ForeignKey("account.id", name="fk_key_pair_account"), nullable=False
    )
    region_id: Mapped[int] = mapped_column(
        UBigInt, ForeignKey("region.id", name="fk_key_pair_region"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class IamInstanceProfile(Base):
    __tablename__ = "iam_instance_profile"
    __table_args__ = (
        UniqueConstraint("account_id", "region_id", "arn", name="uq_iam_profile"),
        _TABLE_DEFAULTS,
    )

    id: Mapped[int] = mapped_column(UBigInt, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        UBigInt, ForeignKey("account.id", name="fk_iam_profile_account"), nullable=False
    )
    region_id: Mapped[int] = mapped_column(
        UBigInt, ForeignKey("region.id", name="fk_iam_profile_region"), nullable=False
    )
    arn: Mapped[str] = mapped_column(String(255), nullable=False)


class Vpc(Base):
    __tablename__ = "vpc"
    __table_args__ = (
        UniqueConstraint("account_id", "region_id", "vpc_id", name="uq_vpc"),
        _TABLE_DEFAULTS,
    )

    id: Mapped[int] = mapped_column(UBigInt, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        UBigInt, ForeignKey("account.id", name="fk_vpc_account"), nullable=False
    )
    region_id: Mapped[int] = mapped_column(
        UBigInt, ForeignKey("region.id", name="fk_vpc_region"), nullable=False
    )
    vpc_id: Mapped[str] = mapped_column(String(32), nullable=False)
    cidr: Mapped[str | None] = mapped_column(String(43), nullable=True)


class Subnet(Base):
    __tablename__ = "subnet"
    __table_args__ = (
        UniqueConstraint("vpc_pk", "subnet_id", name="uq_subnet"),
        _TABLE_DEFAULTS,
    )

    id: Mapped[int] = mapped_column(UBigInt, primary_key=True, autoincrement=True)
    vpc_pk: Mapped[int] = mapped_column(
        UBigInt, ForeignKey("vpc.id", name="fk_subnet_vpc"), nullable=False
    )
    availability_zone_id: Mapped[int] = mapped_column(
        UBigInt, ForeignKey("availability_zone.id", name="fk_subnet_az"), nullable=False
    )
    subnet_id: Mapped[str] = mapped_column(String(32), nullable=False)
    cidr: Mapped[str | None] = mapped_column(String(43), nullable=True)


class SecurityGroup(Base):
    __tablename__ = "security_group"
    __table_args__ = (
        UniqueConstraint("vpc_pk", "group_id", name="uq_security_group"),
        _TABLE_DEFAULTS,
    )

    id: Mapped[int] = mapped_column(UBigInt, primary_key=True, autoincrement=True)
    vpc_pk: Mapped[int] = mapped_column(
        UBigInt, ForeignKey("vpc.id", name="fk_sg_vpc"), nullable=False
    )
    group_id: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ScrapeRun(Base):
    __tablename__ = "scrape_run"
    __table_args__ = (_TABLE_DEFAULTS,)

    id: Mapped[int] = mapped_column(UBigInt, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(
        ENUM(*SCRAPE_STATUS_VALUES), nullable=False, server_default=text("'running'")
    )


class ScrapeRunScope(Base):
    __tablename__ = "scrape_run_scope"
    __table_args__ = (_TABLE_DEFAULTS,)

    scrape_run_id: Mapped[int] = mapped_column(
        UBigInt,
        ForeignKey("scrape_run.id", name="fk_scope_run", ondelete="CASCADE"),
        primary_key=True,
    )
    account_id: Mapped[int] = mapped_column(
        UBigInt, ForeignKey("account.id", name="fk_scope_account"), primary_key=True
    )
    region_id: Mapped[int] = mapped_column(
        UBigInt, ForeignKey("region.id", name="fk_scope_region"), primary_key=True
    )
    status: Mapped[str] = mapped_column(
        ENUM(*SCRAPE_SCOPE_STATUS_VALUES), nullable=False, server_default=text("'succeeded'")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Instance(Base):
    """EC2 instance inventory row.

    Note: ``image_id`` deliberately has NO foreign key to ``ami`` (FR-019);
    join on ``(region_id, image_id)``.
    """

    __tablename__ = "instance"
    __table_args__ = (
        UniqueConstraint("account_id", "region_id", "instance_id", name="uq_instance"),
        Index("ix_instance_state", "state"),
        Index("ix_instance_type", "instance_type_id"),
        Index("ix_instance_image", "region_id", "image_id"),
        Index("ix_instance_last_run", "last_scrape_run_id"),
        _TABLE_DEFAULTS,
    )

    id: Mapped[int] = mapped_column(UBigInt, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        UBigInt, ForeignKey("account.id", name="fk_instance_account"), nullable=False
    )
    region_id: Mapped[int] = mapped_column(
        UBigInt, ForeignKey("region.id", name="fk_instance_region"), nullable=False
    )
    instance_id: Mapped[str] = mapped_column(String(32), nullable=False)
    instance_type_id: Mapped[int] = mapped_column(
        UBigInt, ForeignKey("instance_type.id", name="fk_instance_type"), nullable=False
    )
    availability_zone_id: Mapped[int] = mapped_column(
        UBigInt, ForeignKey("availability_zone.id", name="fk_instance_az"), nullable=False
    )
    subnet_pk: Mapped[int | None] = mapped_column(
        UBigInt, ForeignKey("subnet.id", name="fk_instance_subnet"), nullable=True
    )
    key_pair_id: Mapped[int | None] = mapped_column(
        UBigInt, ForeignKey("key_pair.id", name="fk_instance_key_pair"), nullable=True
    )
    iam_instance_profile_id: Mapped[int | None] = mapped_column(
        UBigInt,
        ForeignKey("iam_instance_profile.id", name="fk_instance_profile"),
        nullable=True,
    )
    image_id: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(ENUM(*INSTANCE_STATE_VALUES), nullable=False)
    architecture: Mapped[str] = mapped_column(String(16), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    launch_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    private_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    public_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    monitoring: Mapped[str] = mapped_column(
        ENUM(*MONITORING_VALUES), nullable=False, server_default=text("'disabled'")
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    last_scrape_run_id: Mapped[int | None] = mapped_column(
        UBigInt, ForeignKey("scrape_run.id", name="fk_instance_run"), nullable=True
    )


class InstanceSecurityGroup(Base):
    __tablename__ = "instance_security_group"
    __table_args__ = (_TABLE_DEFAULTS,)

    instance_pk: Mapped[int] = mapped_column(
        UBigInt,
        ForeignKey("instance.id", name="fk_isg_instance", ondelete="CASCADE"),
        primary_key=True,
    )
    security_group_pk: Mapped[int] = mapped_column(
        UBigInt, ForeignKey("security_group.id", name="fk_isg_sg"), primary_key=True
    )


class InstanceVolume(Base):
    __tablename__ = "instance_volume"
    __table_args__ = (
        UniqueConstraint("instance_pk", "device_name", name="uq_instance_volume"),
        _TABLE_DEFAULTS,
    )

    id: Mapped[int] = mapped_column(UBigInt, primary_key=True, autoincrement=True)
    instance_pk: Mapped[int] = mapped_column(
        UBigInt,
        ForeignKey("instance.id", name="fk_iv_instance", ondelete="CASCADE"),
        nullable=False,
    )
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    volume_id: Mapped[str] = mapped_column(String(32), nullable=False)
    size_gib: Mapped[int | None] = mapped_column(UInt, nullable=True)
    volume_type: Mapped[str | None] = mapped_column(String(16), nullable=True)


class InstanceNetworkInterface(Base):
    __tablename__ = "instance_network_interface"
    __table_args__ = (
        UniqueConstraint("instance_pk", "eni_id", name="uq_instance_eni"),
        _TABLE_DEFAULTS,
    )

    id: Mapped[int] = mapped_column(UBigInt, primary_key=True, autoincrement=True)
    instance_pk: Mapped[int] = mapped_column(
        UBigInt,
        ForeignKey("instance.id", name="fk_ini_instance", ondelete="CASCADE"),
        nullable=False,
    )
    eni_id: Mapped[str] = mapped_column(String(32), nullable=False)
    subnet_pk: Mapped[int | None] = mapped_column(
        UBigInt, ForeignKey("subnet.id", name="fk_ini_subnet"), nullable=True
    )
    private_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    public_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)


class InstanceTag(Base):
    __tablename__ = "instance_tag"
    __table_args__ = (
        Index("ix_instance_tag_kv", "tag_key", "tag_value"),
        _TABLE_DEFAULTS,
    )

    instance_pk: Mapped[int] = mapped_column(
        UBigInt,
        ForeignKey("instance.id", name="fk_it_instance", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    tag_value: Mapped[str] = mapped_column(String(256), nullable=False)


class Ami(Base):
    __tablename__ = "ami"
    __table_args__ = (
        UniqueConstraint("account_id", "region_id", "image_id", name="uq_ami"),
        Index("ix_ami_image", "region_id", "image_id"),
        Index("ix_ami_owner", "owner_aws_account_id"),
        Index("ix_ami_last_run", "last_scrape_run_id"),
        _TABLE_DEFAULTS,
    )

    id: Mapped[int] = mapped_column(UBigInt, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        UBigInt, ForeignKey("account.id", name="fk_ami_account"), nullable=False
    )
    region_id: Mapped[int] = mapped_column(
        UBigInt, ForeignKey("region.id", name="fk_ami_region"), nullable=False
    )
    image_id: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_aws_account_id: Mapped[str] = mapped_column(CHAR(12), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    creation_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    state: Mapped[str] = mapped_column(ENUM(*AMI_STATE_VALUES), nullable=False)
    architecture: Mapped[str] = mapped_column(String(16), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    root_device_type: Mapped[str] = mapped_column(String(16), nullable=False)
    virtualization_type: Mapped[str] = mapped_column(String(16), nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    deprecation_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    last_scrape_run_id: Mapped[int | None] = mapped_column(
        UBigInt, ForeignKey("scrape_run.id", name="fk_ami_run"), nullable=True
    )


class AmiBlockDeviceMapping(Base):
    __tablename__ = "ami_block_device_mapping"
    __table_args__ = (
        UniqueConstraint("ami_pk", "device_name", name="uq_ami_bdm"),
        _TABLE_DEFAULTS,
    )

    id: Mapped[int] = mapped_column(UBigInt, primary_key=True, autoincrement=True)
    ami_pk: Mapped[int] = mapped_column(
        UBigInt,
        ForeignKey("ami.id", name="fk_bdm_ami", ondelete="CASCADE"),
        nullable=False,
    )
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    snapshot_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    size_gib: Mapped[int | None] = mapped_column(UInt, nullable=True)


class AmiTag(Base):
    __tablename__ = "ami_tag"
    __table_args__ = (
        Index("ix_ami_tag_kv", "tag_key", "tag_value"),
        _TABLE_DEFAULTS,
    )

    ami_pk: Mapped[int] = mapped_column(
        UBigInt,
        ForeignKey("ami.id", name="fk_at_ami", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    tag_value: Mapped[str] = mapped_column(String(256), nullable=False)
