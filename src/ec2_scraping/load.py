"""Transactional upserts of collected instances and enrichments into the single-table schema."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ec2_scraping.db.models import Instance
from ec2_scraping.models import Collected, Counts, EnrichmentResult, InstanceRecord


def _clip(value: str | None, size: int) -> str | None:
    return value[:size] if value is not None else None


def _profile_name(arn: str | None) -> str | None:
    if not arn:
        return None
    return _clip(arn.rsplit("/", 1)[-1], 128)


def _instance_family(instance_type: str) -> str | None:
    return _clip(instance_type.split(".", 1)[0], 32) if "." in instance_type else None


def get_accessed_ssh_instance_ids(
    db: Session, aws_account_id: str, region: str, instance_ids: list[str]
) -> set[str]:
    """Return instance_ids in (account, region) that already have ssh_status == 'succeeded'."""
    if not instance_ids:
        return set()
    stmt = select(Instance.instance_id).where(
        Instance.aws_account_id == aws_account_id,
        Instance.region == region,
        Instance.instance_id.in_(instance_ids),
        Instance.ssh_status == "succeeded",
    )
    return set(db.scalars(stmt).all())


def load_instances(
    db: Session,
    aws_account_id: str,
    region: str,
    data: Collected,
    enrichments: dict[str, dict[str, EnrichmentResult]] | None = None,
) -> Counts:
    """Upsert all collected instances for an (account, region) into the `instance` table."""
    counts = Counts()
    for inst in data.instances:
        inst_enrichments = (enrichments or {}).get(inst.instance_id)
        counts.add(_load_instance(db, aws_account_id, region, inst, data, inst_enrichments))
    return counts


def _build_volume_payload(
    inst: InstanceRecord, data: Collected
) -> tuple[
    list[dict[str, Any]],
    str | None,
    int | None,
    str | None,
    bool | None,
    int,
    int,
    bool | None,
]:
    vol_list: list[dict[str, Any]] = []
    root_vol_id: str | None = None
    root_size: int | None = None
    root_type: str | None = None
    root_encrypted: bool | None = None
    total_size = 0
    encrypted_flags: list[bool] = []

    for att in sorted(inst.volumes, key=lambda v: v.device_name):
        vinfo = data.volume_info.get(att.volume_id)
        size_gib = vinfo.size_gib if vinfo else None
        vtype = vinfo.volume_type if vinfo else None
        enc = vinfo.encrypted if vinfo else None
        if size_gib is not None:
            total_size += size_gib
        if enc is not None:
            encrypted_flags.append(bool(enc))
        if inst.root_device_name and att.device_name == inst.root_device_name:
            root_vol_id = att.volume_id
            root_size = size_gib
            root_type = vtype
            root_encrypted = bool(enc) if enc is not None else None
        vol_list.append(
            {
                "device_name": att.device_name,
                "volume_id": att.volume_id,
                "size_gib": size_gib,
                "volume_type": vtype,
                "encrypted": enc,
                "iops": vinfo.iops if vinfo else None,
                "throughput": vinfo.throughput if vinfo else None,
                "delete_on_termination": att.delete_on_termination,
            }
        )

    all_encrypted = all(encrypted_flags) if encrypted_flags else None
    return (
        vol_list,
        root_vol_id,
        root_size,
        root_type,
        root_encrypted,
        len(vol_list),
        total_size,
        all_encrypted,
    )


def _load_instance(
    db: Session,
    aws_account_id: str,
    region: str,
    inst: InstanceRecord,
    data: Collected,
    inst_enrichments: dict[str, EnrichmentResult] | None = None,
) -> str:
    tinfo = data.type_info.get(inst.instance_type)
    ami = data.amis.get(inst.image_id)
    (
        vol_list,
        root_vol_id,
        root_size,
        root_type,
        root_encrypted,
        vol_count,
        total_vol_size,
        all_encrypted,
    ) = _build_volume_payload(inst, data)

    sg_list = [
        {"group_id": gid, "group_name": gname}
        for gid, gname in sorted(inst.security_groups, key=lambda g: g[0])
    ]
    nic_list = [
        {
            "eni_id": n.eni_id,
            "subnet_id": n.subnet_id,
            "private_ip": n.private_ip,
            "public_ip": n.public_ip,
            "mac_address": n.mac_address,
            "ipv6_addresses": n.ipv6_addresses,
        }
        for n in sorted(inst.network_interfaces, key=lambda n: n.eni_id)
    ]

    cols: dict[str, Any] = {
        "name": _clip(inst.name, 256),
        "state": inst.state,
        "state_reason_code": _clip(inst.state_reason_code, 64),
        "state_transition_reason": _clip(inst.state_transition_reason, 255),
        "lifecycle": _clip(inst.lifecycle, 32) or "on-demand",
        "spot_instance_request_id": _clip(inst.spot_instance_request_id, 32),
        "capacity_reservation_id": _clip(inst.capacity_reservation_id, 32),
        "tenancy": _clip(inst.tenancy, 32) or "default",
        "placement_group": _clip(inst.placement_group, 255),
        "host_id": _clip(inst.host_id, 32),
        "launch_time": inst.launch_time,
        "usage_operation": _clip(inst.usage_operation, 64),
        "monitoring": inst.monitoring,
        "instance_type": inst.instance_type,
        "instance_family": _instance_family(inst.instance_type),
        "architecture": inst.architecture,
        "vcpu": tinfo.vcpu if tinfo else None,
        "cpu_core_count": inst.cpu_core_count,
        "cpu_threads_per_core": inst.cpu_threads_per_core,
        "memory_mib": tinfo.memory_mib if tinfo else None,
        "gpu_count": tinfo.gpu_count if tinfo else None,
        "gpu_model": _clip(tinfo.gpu_model, 64) if tinfo else None,
        "gpu_memory_mib": tinfo.gpu_memory_mib if tinfo else None,
        "instance_storage_gib": tinfo.instance_storage_gib if tinfo else None,
        "network_performance": _clip(tinfo.network_performance, 64) if tinfo else None,
        "is_current_generation": tinfo.is_current_generation if tinfo else None,
        "is_burstable": tinfo.is_burstable if tinfo else None,
        "is_bare_metal": tinfo.is_bare_metal if tinfo else None,
        "hypervisor": _clip(inst.hypervisor, 16),
        "virtualization_type": _clip(inst.virtualization_type, 16),
        "ena_support": inst.ena_support,
        "sriov_net_support": _clip(inst.sriov_net_support, 16),
        "boot_mode": _clip(inst.boot_mode, 32),
        "tpm_support": _clip(inst.tpm_support, 32),
        "platform": _clip(inst.platform, 32),
        "platform_details": _clip(inst.platform_details, 64),
        "image_id": inst.image_id,
        "ami_owner_aws_account_id": ami.owner_aws_account_id if ami else None,
        "ami_name": _clip(ami.name, 255) if ami else None,
        "ami_description": _clip(ami.description, 1024) if ami else None,
        "ami_creation_date": ami.creation_date if ami else None,
        "ami_state": ami.state if ami else None,
        "ami_architecture": ami.architecture if ami else None,
        "ami_platform": ami.platform if ami else None,
        "ami_platform_details": _clip(ami.platform_details, 64) if ami else None,
        "ami_root_device_type": ami.root_device_type if ami else None,
        "ami_virtualization_type": ami.virtualization_type if ami else None,
        "ami_is_public": bool(ami.is_public) if ami else None,
        "ami_deprecation_time": ami.deprecation_time if ami else None,
        "availability_zone": inst.availability_zone,
        "vpc_id": inst.vpc_id,
        "vpc_cidr": data.vpc_cidrs.get(inst.vpc_id) if inst.vpc_id else None,
        "subnet_id": inst.subnet_id,
        "subnet_cidr": data.subnet_cidrs.get(inst.subnet_id) if inst.subnet_id else None,
        "private_ip": inst.private_ip,
        "public_ip": inst.public_ip,
        "ipv6_address": inst.ipv6_address,
        "private_dns_name": _clip(inst.private_dns_name, 255),
        "public_dns_name": _clip(inst.public_dns_name, 255),
        "source_dest_check": inst.source_dest_check,
        "eni_count": len(nic_list),
        "security_group_count": len(sg_list),
        "ebs_optimized": bool(inst.ebs_optimized),
        "root_device_type": _clip(inst.root_device_type, 16),
        "root_device_name": _clip(inst.root_device_name, 64),
        "root_volume_id": root_vol_id,
        "root_volume_size_gib": root_size,
        "root_volume_type": root_type,
        "root_volume_encrypted": root_encrypted,
        "ebs_volume_count": vol_count,
        "ebs_total_size_gib": total_vol_size,
        "ebs_all_encrypted": all_encrypted,
        "key_name": _clip(inst.key_name, 255),
        "iam_instance_profile_arn": _clip(inst.iam_profile_arn, 255),
        "iam_instance_profile_name": _profile_name(inst.iam_profile_arn),
        "imds_http_tokens": _clip(inst.imds_http_tokens, 16),
        "imds_http_endpoint": _clip(inst.imds_http_endpoint, 16),
        "imds_hop_limit": inst.imds_hop_limit,
        "imds_instance_metadata_tags": _clip(inst.imds_instance_metadata_tags, 16),
        "tags": dict(sorted(inst.tags.items())),
        "security_groups": sg_list,
        "volumes": vol_list,
        "network_interfaces": nic_list,
    }

    if inst_enrichments:
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        if "ssh" in inst_enrichments:
            ssh_res = inst_enrichments["ssh"]
            sf = ssh_res.facts or {}
            cols["ssh_status"] = _clip(ssh_res.status, 32)
            cols["ssh_user"] = _clip(sf.get("ssh_user"), 64)
            cols["ssh_host"] = _clip(sf.get("ssh_host"), 45)
            cols["ssh_port"] = sf.get("ssh_port")
            cols["ssh_os_id"] = _clip(sf.get("os_id"), 64)
            cols["ssh_os_version"] = _clip(sf.get("os_version"), 64)
            cols["ssh_os_pretty_name"] = _clip(sf.get("os_pretty_name"), 255)
            cols["ssh_kernel"] = _clip(sf.get("kernel"), 128)
            cols["ssh_hostname"] = _clip(sf.get("hostname"), 255)
            cols["ssh_uptime_seconds"] = sf.get("uptime_seconds")
            cols["ssh_package_count"] = sf.get("package_count")
            cols["ssh_listening_port_count"] = sf.get("listening_port_count")
            cols["ssh_container_count"] = sf.get("container_count")
            cols["ssh_reboot_required"] = sf.get("reboot_required")
            cols["ssh_facts"] = ssh_res.facts
            cols["ssh_error"] = ssh_res.error
            cols["ssh_collected_at"] = now
        other = {
            k: {"status": v.status, "facts": v.facts, "error": v.error}
            for k, v in inst_enrichments.items()
            if k != "ssh"
        }
        if other:
            cols["extra_facts"] = other

    key = {
        "aws_account_id": aws_account_id,
        "region": region,
        "instance_id": inst.instance_id,
    }

    existing = db.scalars(select(Instance).filter_by(**key)).first()
    if existing is None:
        db.add(Instance(**key, **cols))
        db.flush()
        return "created"

    changed = any(getattr(existing, c) != v for c, v in cols.items())
    existing.last_seen_at = func.now()  # type: ignore[assignment]
    if changed:
        for c, v in cols.items():
            setattr(existing, c, v)
    db.flush()
    return "updated" if changed else "unchanged"
