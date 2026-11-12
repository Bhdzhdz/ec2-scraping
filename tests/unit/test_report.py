"""Unit tests for inventory summary and CSV export (`ec2_scraping.report` and CLI commands)."""

import csv
import io
import json
from datetime import datetime
from typing import TYPE_CHECKING

from tests.integration.helpers import make_ssh_enrichment

from ec2_scraping import cli, load, report
from ec2_scraping.db import connect
from ec2_scraping.models import (
    AmiRecord,
    Collected,
    InstanceRecord,
    TypeInfo,
    VolumeAttachment,
    VolumeInfo,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from sqlalchemy.orm import Session


def _seed_db(session: Session) -> None:
    inst_1 = InstanceRecord(
        instance_id="i-1",
        instance_type="t3.micro",
        availability_zone="us-east-1a",
        image_id="ami-1",
        state="running",
        architecture="x86_64",
        launch_time=datetime(2026, 1, 1, 12, 0, 0),
        name="web-1",
        platform_details="Linux/UNIX",
        tags={"Name": "web-1", "env": "prod"},
        volumes=[VolumeAttachment("/dev/xvda", "vol-1", True)],
    )
    inst_2 = InstanceRecord(
        instance_id="i-2",
        instance_type="m5.large",
        availability_zone="us-east-1b",
        image_id="ami-2",
        state="stopped",
        architecture="x86_64",
        launch_time=datetime(2026, 1, 2, 12, 0, 0),
        name="db-1",
        platform="windows",
        platform_details="Windows",
        volumes=[VolumeAttachment("/dev/sda1", "vol-2", True)],
    )
    data_east = Collected(
        instances=[inst_1, inst_2],
        amis={
            "ami-1": AmiRecord(
                image_id="ami-1",
                owner_aws_account_id="111111111111",
                state="available",
                architecture="x86_64",
                root_device_type="ebs",
                virtualization_type="hvm",
                name="ubuntu-24.04",
            ),
        },
        type_info={
            "t3.micro": TypeInfo(vcpu=2, memory_mib=1024, architecture="x86_64"),
            "m5.large": TypeInfo(vcpu=2, memory_mib=8192, architecture="x86_64"),
        },
        volume_info={
            "vol-1": VolumeInfo("vol-1", 20, "gp3", True),
            "vol-2": VolumeInfo("vol-2", 100, "gp3", False),
        },
    )
    enrichments = {"i-1": {"ssh": make_ssh_enrichment()}}
    load.load_instances(session, "111111111111", "us-east-1", data_east, enrichments)

    inst_3 = InstanceRecord(
        instance_id="i-3",
        instance_type="t3.small",
        availability_zone="us-west-2a",
        image_id="ami-1",
        state="running",
        architecture="x86_64",
        launch_time=datetime(2026, 1, 3, 12, 0, 0),
        name="worker-1",
    )
    data_west = Collected(
        instances=[inst_3],
        type_info={"t3.small": TypeInfo(vcpu=2, memory_mib=2048, architecture="x86_64")},
    )
    load.load_instances(session, "222222222222", "us-west-2", data_west)
    session.commit()


def _assert_summary_counts(s: report.InventorySummary) -> None:
    assert (
        s.total_instances,
        s.total_vcpu,
        s.total_memory_mib,
        s.total_ebs_volumes,
        s.total_ebs_size_gib,
    ) == (3, 6, 11264, 2, 120)
    assert (s.by_state, s.by_account, s.by_region, s.by_instance_family) == (
        {"running": 2, "stopped": 1},
        {"111111111111": 2, "222222222222": 1},
        {"us-east-1": 2, "us-west-2": 1},
        {"t3": 2, "m5": 1},
    )
    assert (s.by_instance_type, s.by_ssh_status, s.by_os, s.by_ami) == (
        {"m5.large": 1, "t3.micro": 1, "t3.small": 1},
        {"not-probed": 2, "succeeded": 1},
        {"Ubuntu 24.04 LTS": 1, "Windows": 1, "unknown": 1},
        {"ami-1": 1, "ami-1 (ubuntu-24.04)": 1, "ami-2": 1},
    )


def _assert_formatted_text(text: str) -> None:
    expected_snippets = (
        "Total instances: 3",
        "vCPUs: 6",
        "Memory: 11.0 GiB (11264 MiB)",
        "EBS: 2 volumes, 120 GiB",
        "By state:\n  running: 2\n  stopped: 1",
        "By OS / platform:\n  Ubuntu 24.04 LTS: 1",
    )
    assert all(snippet in text for snippet in expected_snippets)


def test_summarize_instances_and_formatting(tmp_path: Path) -> None:
    dsn = f"sqlite:///{tmp_path / 'inv.db'}"
    session = connect(dsn)
    try:
        _seed_db(session)
        s = report.summarize_instances(session)
        _assert_summary_counts(s)
        _assert_formatted_text(report.format_inventory_summary(s))

        filtered = report.summarize_instances(
            session, regions=["us-east-1"], accounts=["111111111111"], states=["running"]
        )
        assert (filtered.total_instances, filtered.by_instance_type) == (1, {"t3.micro": 1})
    finally:
        session.close()


def _assert_exported_rows(rows: list[dict[str, str]]) -> None:
    assert [r["instance_id"] for r in rows] == ["i-1", "i-2", "i-3"]
    assert json.loads(rows[0]["tags"]) == {"Name": "web-1", "env": "prod"}
    assert (rows[0]["ssh_os_pretty_name"], rows[1]["state"]) == ("Ubuntu 24.04 LTS", "stopped")


def test_export_instances_csv_and_cli_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dsn = f"sqlite:///{tmp_path / 'inv.db'}"
    session = connect(dsn)
    try:
        _seed_db(session)
        buf = io.StringIO()
        assert report.export_instances_csv(session, buf) == 3
    finally:
        session.close()

    _assert_exported_rows(list(csv.DictReader(io.StringIO(buf.getvalue()))))

    assert cli.main(["summary", "--dsn", dsn, "--state", "running"]) == 0
    assert "Total instances: 2" in capsys.readouterr().out

    csv_path = tmp_path / "out" / "export.csv"
    export_args = [
        "export",
        "--dsn",
        dsn,
        "--region",
        "us-east-1",
        "--account",
        "111111111111",
        "-o",
        str(csv_path),
    ]
    assert cli.main(export_args) == 0
    with csv_path.open(encoding="utf-8", newline="") as fh:
        assert [r["instance_id"] for r in csv.DictReader(fh)] == ["i-1", "i-2"]

    capsys.readouterr()
    assert cli.main(["export", "--dsn", dsn, "--region", "us-west-2"]) == 0
    stdout_rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert [r["instance_id"] for r in stdout_rows] == ["i-3"]
