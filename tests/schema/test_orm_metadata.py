"""Offline unit tests for SQLAlchemy 2.0 ORM models and Alembic migrations (no DB needed)."""

import io
from contextlib import redirect_stdout

import pytest
from alembic import command
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable, UniqueConstraint

from ec2_scraping.db import (
    Account,
    Ami,
    AmiBlockDeviceMapping,
    AmiTag,
    AvailabilityZone,
    Base,
    IamInstanceProfile,
    Instance,
    InstanceNetworkInterface,
    InstanceSecurityGroup,
    InstanceTag,
    InstanceType,
    InstanceVolume,
    KeyPair,
    Region,
    ScrapeRun,
    ScrapeRunScope,
    SecurityGroup,
    Subnet,
    Vpc,
    make_alembic_config,
    make_engine,
    make_session_factory,
    normalize_dsn,
    upgrade_db,
)

EXPECTED_TABLES = {
    "account",
    "region",
    "availability_zone",
    "instance_type",
    "key_pair",
    "iam_instance_profile",
    "vpc",
    "subnet",
    "security_group",
    "scrape_run",
    "scrape_run_scope",
    "instance",
    "instance_security_group",
    "instance_volume",
    "instance_network_interface",
    "instance_tag",
    "ami",
    "ami_block_device_mapping",
    "ami_tag",
}


def test_all_tables_registered_with_innodb_utf8mb4():
    assert set(Base.metadata.tables) == EXPECTED_TABLES
    for table in Base.metadata.tables.values():
        assert table.dialect_options["mysql"]["engine"] == "InnoDB"
        assert table.dialect_options["mysql"]["charset"] == "utf8mb4"
        ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
        assert "ENGINE=InnoDB" in ddl
        assert "CHARSET=utf8mb4" in ddl


def test_soft_instance_to_ami_link_has_no_fk():
    instance_table = Base.metadata.tables["instance"]
    fk_targets = {fk.target_fullname for fk in instance_table.foreign_keys}
    assert not any(t.startswith("ami.") for t in fk_targets)
    index_cols = {idx.name: tuple(c.name for c in idx.columns) for idx in instance_table.indexes}
    assert index_cols["ix_instance_image"] == ("region_id", "image_id")
    assert index_cols["ix_instance_state"] == ("state",)
    assert index_cols["ix_instance_type"] == ("instance_type_id",)
    assert index_cols["ix_instance_last_run"] == ("last_scrape_run_id",)


def test_unique_constraints_and_cascades():
    uqs = {
        t_name: {
            c.name: tuple(col.name for col in c.columns)
            for c in t.constraints
            if isinstance(c, UniqueConstraint)
        }
        for t_name, t in Base.metadata.tables.items()
    }
    assert uqs["account"]["uq_account_aws_id"] == ("aws_account_id",)
    assert uqs["region"]["uq_region_code"] == ("code",)
    assert uqs["availability_zone"]["uq_az_region_name"] == ("region_id", "name")
    assert uqs["instance_type"]["uq_instance_type_name"] == ("name",)
    assert uqs["key_pair"]["uq_key_pair"] == ("account_id", "region_id", "name")
    assert uqs["iam_instance_profile"]["uq_iam_profile"] == ("account_id", "region_id", "arn")
    assert uqs["vpc"]["uq_vpc"] == ("account_id", "region_id", "vpc_id")
    assert uqs["subnet"]["uq_subnet"] == ("vpc_pk", "subnet_id")
    assert uqs["security_group"]["uq_security_group"] == ("vpc_pk", "group_id")
    assert uqs["instance"]["uq_instance"] == ("account_id", "region_id", "instance_id")
    assert uqs["instance_volume"]["uq_instance_volume"] == ("instance_pk", "device_name")
    assert uqs["instance_network_interface"]["uq_instance_eni"] == ("instance_pk", "eni_id")
    assert uqs["ami"]["uq_ami"] == ("account_id", "region_id", "image_id")
    assert uqs["ami_block_device_mapping"]["uq_ami_bdm"] == ("ami_pk", "device_name")

    for table_name in (
        "scrape_run_scope",
        "instance_security_group",
        "instance_volume",
        "instance_network_interface",
        "instance_tag",
        "ami_block_device_mapping",
        "ami_tag",
    ):
        table = Base.metadata.tables[table_name]
        assert any(fk.ondelete == "CASCADE" for fk in table.foreign_keys), table_name


def test_model_classes_instantiable():
    models = (
        Account(aws_account_id="111111111111"),
        Region(code="us-east-1"),
        AvailabilityZone(region_id=1, name="us-east-1a"),
        InstanceType(name="t3.micro"),
        KeyPair(account_id=1, region_id=1, name="kp"),
        IamInstanceProfile(account_id=1, region_id=1, arn="arn:aws:iam::1:instance-profile/p"),
        Vpc(account_id=1, region_id=1, vpc_id="vpc-1"),
        Subnet(vpc_pk=1, availability_zone_id=1, subnet_id="subnet-1"),
        SecurityGroup(vpc_pk=1, group_id="sg-1"),
        ScrapeRun(),
        ScrapeRunScope(scrape_run_id=1, account_id=1, region_id=1),
        Instance(
            account_id=1,
            region_id=1,
            instance_id="i-1",
            instance_type_id=1,
            availability_zone_id=1,
            image_id="ami-1",
            state="running",
            architecture="x86_64",
        ),
        InstanceSecurityGroup(instance_pk=1, security_group_pk=1),
        InstanceVolume(instance_pk=1, device_name="/dev/sda1", volume_id="vol-1"),
        InstanceNetworkInterface(instance_pk=1, eni_id="eni-1"),
        InstanceTag(instance_pk=1, tag_key="Env", tag_value="prod"),
        Ami(
            account_id=1,
            region_id=1,
            image_id="ami-1",
            owner_aws_account_id="111111111111",
            state="available",
            architecture="x86_64",
            root_device_type="ebs",
            virtualization_type="hvm",
        ),
        AmiBlockDeviceMapping(ami_pk=1, device_name="/dev/sda1"),
        AmiTag(ami_pk=1, tag_key="Env", tag_value="prod"),
    )
    assert len(models) == len(EXPECTED_TABLES)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("mysql://u:p@h:3306/db", "mysql+pymysql://u:p@h:3306/db"),
        ("mariadb://u:p@h:3306/db", "mysql+pymysql://u:p@h:3306/db"),
        ("mysql+pymysql://u:p@h:3306/db", "mysql+pymysql://u:p@h:3306/db"),
    ],
)
def test_session_and_dsn_helpers(raw, expected):
    assert normalize_dsn(raw) == expected
    engine = make_engine(raw)
    factory = make_session_factory(engine)
    factory_from_dsn = make_session_factory(raw)
    assert factory.kw["bind"] is engine
    assert factory_from_dsn.kw["bind"].url.drivername == "mysql+pymysql"


def test_offline_alembic_upgrade_and_downgrade_sql():
    buf = io.StringIO()
    with redirect_stdout(buf):
        upgrade_db("mysql://u:p@localhost:3306/inv", "head", sql=True)
    sql_up = buf.getvalue()
    for table_name in EXPECTED_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in sql_up

    cfg = make_alembic_config("mysql://u:p@localhost:3306/inv")
    buf_down = io.StringIO()
    with redirect_stdout(buf_down):
        command.downgrade(cfg, "0001_initial_schema:base", sql=True)
    sql_down = buf_down.getvalue()
    for table_name in EXPECTED_TABLES:
        assert f"DROP TABLE IF EXISTS {table_name}" in sql_down
