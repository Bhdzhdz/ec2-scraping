"""Transactional upserts of collected instances and enrichments into the single-table schema."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from ec2_scraping.db.models import Instance
from ec2_scraping.models import Counts

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ec2_scraping.models import (
        AmiRecord,
        Collected,
        EnrichmentResult,
        InstanceRecord,
        TypeInfo,
        VolumeAttachment,
        VolumeInfo,
    )


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


def get_known_ssh_users(
    db: Session, aws_account_id: str, region: str, instance_ids: list[str]
) -> dict[str, str]:
    """Return {instance_id: ssh_user} for instances in (account, region) with a known ssh_user."""
    if not instance_ids:
        return {}
    stmt = select(Instance.instance_id, Instance.ssh_user).where(
        Instance.aws_account_id == aws_account_id,
        Instance.region == region,
        Instance.instance_id.in_(instance_ids),
        Instance.ssh_status == "succeeded",
        Instance.ssh_user.is_not(None),
    )
    return {inst_id: user for inst_id, user in db.execute(stmt).all() if user}


def get_known_ami_ssh_users(db: Session, image_ids: list[str]) -> dict[str, str]:
    """Return {image_id: ssh_user} for AMIs that previously succeeded over SSH."""
    if not image_ids:
        return {}
    stmt = select(Instance.image_id, Instance.ssh_user).where(
        Instance.image_id.in_(image_ids),
        Instance.ssh_status == "succeeded",
        Instance.ssh_user.is_not(None),
    )
    return {img_id: user for img_id, user in db.execute(stmt).all() if img_id and user}


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
        cols = _build_instance_cols(inst, data, inst_enrichments)
        counts.add(_upsert_instance(db, aws_account_id, region, inst.instance_id, cols))
    return counts


def _volume_entry(att: VolumeAttachment, vinfo: VolumeInfo | None) -> dict[str, Any]:
    if not vinfo:
        return {
            "device_name": att.device_name,
            "volume_id": att.volume_id,
            "size_gib": None,
            "volume_type": None,
            "encrypted": None,
            "iops": None,
            "throughput": None,
            "delete_on_termination": att.delete_on_termination,
        }
    return {
        "device_name": att.device_name,
        "volume_id": att.volume_id,
        "size_gib": vinfo.size_gib,
        "volume_type": vinfo.volume_type,
        "encrypted": vinfo.encrypted,
        "iops": vinfo.iops,
        "throughput": vinfo.throughput,
        "delete_on_termination": att.delete_on_termination,
    }


def _root_volume_fields(
    root_vol: dict[str, Any] | None,
) -> tuple[str | None, int | None, str | None, bool | None]:
    if not root_vol:
        return None, None, None, None
    enc = root_vol["encrypted"]
    return (
        root_vol["volume_id"],
        root_vol["size_gib"],
        root_vol["volume_type"],
        bool(enc) if enc is not None else None,
    )


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
    vol_list = [
        _volume_entry(att, data.volume_info.get(att.volume_id))
        for att in sorted(inst.volumes, key=lambda v: v.device_name)
    ]
    total_size = sum(v["size_gib"] or 0 for v in vol_list)
    enc_flags = [bool(v["encrypted"]) for v in vol_list if v["encrypted"] is not None]
    all_encrypted = all(enc_flags) if enc_flags else None
    root_vol = (
        next((v for v in vol_list if v["device_name"] == inst.root_device_name), None)
        if inst.root_device_name
        else None
    )
    root_vol_id, root_size, root_type, root_enc = _root_volume_fields(root_vol)
    return (
        vol_list,
        root_vol_id,
        root_size,
        root_type,
        root_enc,
        len(vol_list),
        total_size,
        all_encrypted,
    )


def _type_columns(tinfo: TypeInfo | None) -> dict[str, Any]:
    if not tinfo:
        return {
            "vcpu": None,
            "memory_mib": None,
            "gpu_count": None,
            "gpu_model": None,
            "gpu_memory_mib": None,
            "instance_storage_gib": None,
            "network_performance": None,
            "is_current_generation": None,
            "is_burstable": None,
            "is_bare_metal": None,
        }
    return {
        "vcpu": tinfo.vcpu,
        "memory_mib": tinfo.memory_mib,
        "gpu_count": tinfo.gpu_count,
        "gpu_model": _clip(tinfo.gpu_model, 64),
        "gpu_memory_mib": tinfo.gpu_memory_mib,
        "instance_storage_gib": tinfo.instance_storage_gib,
        "network_performance": _clip(tinfo.network_performance, 64),
        "is_current_generation": tinfo.is_current_generation,
        "is_burstable": tinfo.is_burstable,
        "is_bare_metal": tinfo.is_bare_metal,
    }


def _ami_columns(ami: AmiRecord | None) -> dict[str, Any]:
    if not ami:
        return {
            "ami_owner_aws_account_id": None,
            "ami_name": None,
            "ami_description": None,
            "ami_creation_date": None,
            "ami_state": None,
            "ami_architecture": None,
            "ami_platform": None,
            "ami_platform_details": None,
            "ami_root_device_type": None,
            "ami_virtualization_type": None,
            "ami_is_public": None,
            "ami_deprecation_time": None,
        }
    return {
        "ami_owner_aws_account_id": ami.owner_aws_account_id,
        "ami_name": _clip(ami.name, 255),
        "ami_description": _clip(ami.description, 1024),
        "ami_creation_date": ami.creation_date,
        "ami_state": ami.state,
        "ami_architecture": ami.architecture,
        "ami_platform": ami.platform,
        "ami_platform_details": _clip(ami.platform_details, 64),
        "ami_root_device_type": ami.root_device_type,
        "ami_virtualization_type": ami.virtualization_type,
        "ami_is_public": bool(ami.is_public),
        "ami_deprecation_time": ami.deprecation_time,
    }


def _enrichment_columns(
    inst_enrichments: dict[str, EnrichmentResult] | None,
) -> dict[str, Any]:
    if not inst_enrichments:
        return {}
    cols: dict[str, Any] = {}
    if "ssh" in inst_enrichments:
        ssh_res = inst_enrichments["ssh"]
        sf = ssh_res.facts or {}
        cols.update(
            {
                "ssh_status": _clip(ssh_res.status, 32),
                "ssh_user": _clip(sf.get("ssh_user"), 64),
                "ssh_host": _clip(sf.get("ssh_host"), 45),
                "ssh_port": sf.get("ssh_port"),
                "ssh_os_id": _clip(sf.get("os_id"), 64),
                "ssh_os_version": _clip(sf.get("os_version"), 64),
                "ssh_os_pretty_name": _clip(sf.get("os_pretty_name"), 255),
                "ssh_kernel": _clip(sf.get("kernel"), 128),
                "ssh_hostname": _clip(sf.get("hostname"), 255),
                "ssh_uptime_seconds": sf.get("uptime_seconds"),
                "ssh_package_count": sf.get("package_count"),
                "ssh_listening_port_count": sf.get("listening_port_count"),
                "ssh_container_count": sf.get("container_count"),
                "ssh_reboot_required": sf.get("reboot_required"),
                "ssh_facts": ssh_res.facts,
                "ssh_error": ssh_res.error,
                "ssh_collected_at": datetime.now(UTC).replace(tzinfo=None, microsecond=0),
            }
        )
    other = {
        k: {"status": v.status, "facts": v.facts, "error": v.error}
        for k, v in inst_enrichments.items()
        if k != "ssh"
    }
    if other:
        cols["extra_facts"] = other
    return cols


def _build_instance_cols(
    inst: InstanceRecord,
    data: Collected,
    inst_enrichments: dict[str, EnrichmentResult] | None = None,
) -> dict[str, Any]:
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
        "cpu_core_count": inst.cpu_core_count,
        "cpu_threads_per_core": inst.cpu_threads_per_core,
        "hypervisor": _clip(inst.hypervisor, 16),
        "virtualization_type": _clip(inst.virtualization_type, 16),
        "ena_support": inst.ena_support,
        "sriov_net_support": _clip(inst.sriov_net_support, 16),
        "boot_mode": _clip(inst.boot_mode, 32),
        "tpm_support": _clip(inst.tpm_support, 32),
        "platform": _clip(inst.platform, 32),
        "platform_details": _clip(inst.platform_details, 64),
        "image_id": inst.image_id,
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
    cols.update(_type_columns(data.type_info.get(inst.instance_type)))
    cols.update(_ami_columns(data.amis.get(inst.image_id)))
    cols.update(_enrichment_columns(inst_enrichments))
    return cols


def _upsert_instance(
    db: Session,
    aws_account_id: str,
    region: str,
    instance_id: str,
    cols: dict[str, Any],
) -> str:
    key = {
        "aws_account_id": aws_account_id,
        "region": region,
        "instance_id": instance_id,
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
