"""Database inventory summary and CSV export helpers."""

import csv
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import IO

from sqlalchemy import select
from sqlalchemy.orm import Session

from ec2_scraping.db.models import Instance

INSTANCE_COLUMNS: tuple[str, ...] = tuple(c.name for c in Instance.__table__.columns)


@dataclass
class InventorySummary:
    total_instances: int = 0
    total_vcpu: int = 0
    total_memory_mib: int = 0
    total_ebs_volumes: int = 0
    total_ebs_size_gib: int = 0
    by_state: dict[str, int] = field(default_factory=dict)
    by_region: dict[str, int] = field(default_factory=dict)
    by_account: dict[str, int] = field(default_factory=dict)
    by_instance_family: dict[str, int] = field(default_factory=dict)
    by_instance_type: dict[str, int] = field(default_factory=dict)
    by_ssh_status: dict[str, int] = field(default_factory=dict)
    by_os: dict[str, int] = field(default_factory=dict)
    by_ami: dict[str, int] = field(default_factory=dict)


def query_instances(
    db: Session,
    *,
    regions: list[str] | None = None,
    accounts: list[str] | None = None,
    states: list[str] | None = None,
) -> list[Instance]:
    """Return matching ``Instance`` rows ordered by account, region, and instance_id."""
    stmt = select(Instance)
    if regions:
        stmt = stmt.where(Instance.region.in_(regions))
    if accounts:
        stmt = stmt.where(Instance.aws_account_id.in_(accounts))
    if states:
        stmt = stmt.where(Instance.state.in_(states))
    stmt = stmt.order_by(Instance.aws_account_id, Instance.region, Instance.instance_id)
    return list(db.scalars(stmt).all())


def _sorted_counts(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))


def _os_label(inst: Instance) -> str:
    if inst.ssh_os_pretty_name:
        return inst.ssh_os_pretty_name
    if inst.ssh_os_id:
        return f"{inst.ssh_os_id} {inst.ssh_os_version}".strip()
    return inst.platform_details or inst.ami_platform_details or inst.platform or "unknown"


def _ami_label(inst: Instance) -> str:
    return f"{inst.image_id} ({inst.ami_name})" if inst.ami_name else inst.image_id


def summarize_instances(
    db: Session,
    *,
    regions: list[str] | None = None,
    accounts: list[str] | None = None,
    states: list[str] | None = None,
) -> InventorySummary:
    """Compute aggregated metrics across matching instances."""
    rows = query_instances(db, regions=regions, accounts=accounts, states=states)
    summary = InventorySummary(total_instances=len(rows))
    states_c: Counter[str] = Counter()
    regions_c: Counter[str] = Counter()
    accounts_c: Counter[str] = Counter()
    families_c: Counter[str] = Counter()
    types_c: Counter[str] = Counter()
    ssh_c: Counter[str] = Counter()
    os_c: Counter[str] = Counter()
    ami_c: Counter[str] = Counter()

    for r in rows:
        summary.total_vcpu += r.vcpu or 0
        summary.total_memory_mib += r.memory_mib or 0
        summary.total_ebs_volumes += r.ebs_volume_count or 0
        summary.total_ebs_size_gib += r.ebs_total_size_gib or 0

        states_c[r.state] += 1
        regions_c[r.region] += 1
        accounts_c[r.aws_account_id] += 1
        family = r.instance_family or (
            r.instance_type.split(".", 1)[0] if r.instance_type else "unknown"
        )
        families_c[family] += 1
        types_c[r.instance_type] += 1
        ssh_c[r.ssh_status or "not-probed"] += 1
        os_c[_os_label(r)] += 1
        ami_c[_ami_label(r)] += 1

    summary.by_state = _sorted_counts(states_c)
    summary.by_region = _sorted_counts(regions_c)
    summary.by_account = _sorted_counts(accounts_c)
    summary.by_instance_family = _sorted_counts(families_c)
    summary.by_instance_type = _sorted_counts(types_c)
    summary.by_ssh_status = _sorted_counts(ssh_c)
    summary.by_os = _sorted_counts(os_c)
    summary.by_ami = _sorted_counts(ami_c)
    return summary


def format_inventory_summary(summary: InventorySummary) -> str:
    """Format an ``InventorySummary`` as a human-readable report."""
    mem_gib = summary.total_memory_mib / 1024
    lines = [
        f"Total instances: {summary.total_instances}",
        "Resources:",
        f"  vCPUs: {summary.total_vcpu}",
        f"  Memory: {mem_gib:.1f} GiB ({summary.total_memory_mib} MiB)",
        f"  EBS: {summary.total_ebs_volumes} volumes, {summary.total_ebs_size_gib} GiB",
    ]
    sections = (
        ("By state", summary.by_state),
        ("By account", summary.by_account),
        ("By region", summary.by_region),
        ("By instance family", summary.by_instance_family),
        ("By instance type", summary.by_instance_type),
        ("By OS / platform", summary.by_os),
        ("By AMI", summary.by_ami),
        ("By SSH status", summary.by_ssh_status),
    )
    for title, mapping in sections:
        if mapping:
            lines.append(f"{title}:")
            for key, count in mapping.items():
                lines.append(f"  {key}: {count}")
    return "\n".join(lines)


def _serialize_cell(val: object) -> str | int | float | bool:
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.isoformat(sep=" ")
    if isinstance(val, dict | list):
        return json.dumps(val, sort_keys=True)
    if isinstance(val, str | int | float | bool):
        return val
    return str(val)


def export_instances_csv(
    db: Session,
    dest: IO[str],
    *,
    regions: list[str] | None = None,
    accounts: list[str] | None = None,
    states: list[str] | None = None,
) -> int:
    """Write matching ``Instance`` rows to ``dest`` as CSV and return the number of rows written."""
    rows = query_instances(db, regions=regions, accounts=accounts, states=states)
    writer = csv.writer(dest, lineterminator="\n")
    writer.writerow(INSTANCE_COLUMNS)
    for r in rows:
        writer.writerow([_serialize_cell(getattr(r, col)) for col in INSTANCE_COLUMNS])
    return len(rows)
