"""Transactional upserts of collected data into the 3NF schema using SQLAlchemy 2.0."""

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from ec2_scraping.db.base import Base
from ec2_scraping.db.models import (
    Account,
    Ami,
    AmiBlockDeviceMapping,
    AmiTag,
    AvailabilityZone,
    IamInstanceProfile,
    Instance,
    InstanceNetworkInterface,
    InstanceSecurityGroup,
    InstanceTag,
    InstanceType,
    InstanceVolume,
    KeyPair,
    Region,
    SecurityGroup,
    Subnet,
    Vpc,
)
from ec2_scraping.models import AmiRecord, Collected, Counts, InstanceRecord


def _upsert_ref(
    db: Session,
    model: type[Base],
    keys: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> int:
    """Insert-or-update a reference row on its unique key and return its id."""
    extra = extra or {}
    cols = {**keys, **extra}
    table = model.__table__  # type: ignore[attr-defined]
    stmt = mysql_insert(model).values(**cols)
    updates: dict[str, Any] = {"id": func.last_insert_id(table.c.id)}
    for col_name in extra:
        updates[col_name] = func.coalesce(stmt.inserted[col_name], table.c[col_name])
    res: Any = db.execute(stmt.on_duplicate_key_update(**updates))
    return int(res.lastrowid)


def upsert_account(db: Session, aws_account_id: str) -> int:
    return _upsert_ref(db, Account, {"aws_account_id": aws_account_id})


def upsert_region(db: Session, code: str) -> int:
    return _upsert_ref(db, Region, {"code": code})


def upsert_availability_zone(db: Session, region_id: int, name: str) -> int:
    return _upsert_ref(db, AvailabilityZone, {"region_id": region_id, "name": name})


def upsert_instance_type(
    db: Session,
    name: str,
    vcpu: int | None = None,
    memory_mib: int | None = None,
    architecture: str | None = None,
) -> int:
    return _upsert_ref(
        db,
        InstanceType,
        {"name": name},
        {"vcpu": vcpu, "memory_mib": memory_mib, "architecture": architecture},
    )


def upsert_key_pair(db: Session, account_id: int, region_id: int, name: str) -> int:
    return _upsert_ref(
        db, KeyPair, {"account_id": account_id, "region_id": region_id, "name": name}
    )


def upsert_iam_instance_profile(db: Session, account_id: int, region_id: int, arn: str) -> int:
    return _upsert_ref(
        db, IamInstanceProfile, {"account_id": account_id, "region_id": region_id, "arn": arn}
    )


def upsert_vpc(
    db: Session, account_id: int, region_id: int, vpc_id: str, cidr: str | None = None
) -> int:
    return _upsert_ref(
        db,
        Vpc,
        {"account_id": account_id, "region_id": region_id, "vpc_id": vpc_id},
        {"cidr": cidr},
    )


def upsert_subnet(
    db: Session, vpc_pk: int, availability_zone_id: int, subnet_id: str, cidr: str | None = None
) -> int:
    return _upsert_ref(
        db,
        Subnet,
        {"vpc_pk": vpc_pk, "subnet_id": subnet_id},
        {"availability_zone_id": availability_zone_id, "cidr": cidr},
    )


def upsert_security_group(db: Session, vpc_pk: int, group_id: str, name: str | None = None) -> int:
    return _upsert_ref(db, SecurityGroup, {"vpc_pk": vpc_pk, "group_id": group_id}, {"name": name})


class LoadContext:
    """One account/region load: memoises reference lookups for the whole combination."""

    def __init__(self, db: Session, run_id: int, account_pk: int, region_pk: int):
        self.db = db
        self.run_id = run_id
        self.account_pk = account_pk
        self.region_pk = region_pk
        self._cache: dict[tuple, int] = {}

    def _memo(self, key: tuple, make) -> int:
        if key not in self._cache:
            self._cache[key] = make()
        return self._cache[key]

    def az(self, name: str) -> int:
        return self._memo(
            ("az", name), lambda: upsert_availability_zone(self.db, self.region_pk, name)
        )

    def instance_type(self, name: str, info) -> int:
        return self._memo(
            ("type", name),
            lambda: upsert_instance_type(
                self.db,
                name,
                *((info.vcpu, info.memory_mib, info.architecture) if info else (None, None, None)),
            ),
        )

    def key_pair(self, name: str) -> int:
        return self._memo(
            ("key", name), lambda: upsert_key_pair(self.db, self.account_pk, self.region_pk, name)
        )

    def iam_profile(self, arn: str) -> int:
        return self._memo(
            ("iam", arn),
            lambda: upsert_iam_instance_profile(self.db, self.account_pk, self.region_pk, arn),
        )

    def vpc(self, vpc_id: str, cidr: str | None) -> int:
        return self._memo(
            ("vpc", vpc_id),
            lambda: upsert_vpc(self.db, self.account_pk, self.region_pk, vpc_id, cidr),
        )

    def subnet(self, vpc_pk: int, az_pk: int, subnet_id: str, cidr: str | None) -> int:
        return self._memo(
            ("subnet", vpc_pk, subnet_id),
            lambda: upsert_subnet(self.db, vpc_pk, az_pk, subnet_id, cidr),
        )

    def security_group(self, vpc_pk: int, group_id: str, name: str | None) -> int:
        return self._memo(
            ("sg", vpc_pk, group_id),
            lambda: upsert_security_group(self.db, vpc_pk, group_id, name),
        )


Child = tuple[type[Base], str, tuple[str, ...], set[tuple]]


def _sync(
    ctx: LoadContext,
    model: type[Instance | Ami],
    key: dict[str, Any],
    cols: dict[str, Any],
    children: list[Child],
) -> str:
    """Upsert one resource and its child rows; return created/updated/unchanged."""
    db = ctx.db
    existing = db.scalars(select(model).filter_by(**key)).first()

    if existing is None:
        obj = model(**key, **cols, last_scrape_run_id=ctx.run_id)
        db.add(obj)
        db.flush()
        _replace_children(db, obj.id, children)
        return "created"

    pk = existing.id
    changed = any(getattr(existing, c) != v for c, v in cols.items())
    if not changed:
        for child_model, fk, names, rows in children:
            child_cols = [getattr(child_model, n) for n in names]
            fk_col = getattr(child_model, fk)
            stored = {tuple(r) for r in db.execute(select(*child_cols).where(fk_col == pk)).all()}
            if stored != rows:
                changed = True
                break

    existing.last_seen_at = func.now()  # type: ignore[assignment]
    existing.last_scrape_run_id = ctx.run_id
    if changed:
        for c, v in cols.items():
            setattr(existing, c, v)
    db.flush()
    if changed:
        _replace_children(db, pk, children)
        return "updated"
    return "unchanged"


def _replace_children(db: Session, pk: int, children: list[Child]) -> None:
    for child_model, fk, names, rows in children:
        fk_col = getattr(child_model, fk)
        db.execute(delete(child_model).where(fk_col == pk))
        if rows:
            for r in sorted(rows, key=repr):
                db.add(child_model(**{fk: pk, **dict(zip(names, r, strict=True))}))
    db.flush()


def _clip(value: str | None, size: int) -> str | None:
    return value[:size] if value is not None else None


def load_instances(ctx: LoadContext, data: Collected) -> Counts:
    counts = Counts()
    for inst in data.instances:
        counts.add(_load_instance(ctx, inst, data))
    return counts


def _load_instance(ctx: LoadContext, inst: InstanceRecord, data: Collected) -> str:
    az_pk = ctx.az(inst.availability_zone)
    vpc_pk = ctx.vpc(inst.vpc_id, data.vpc_cidrs.get(inst.vpc_id)) if inst.vpc_id else None

    def subnet_pk(subnet_id: str | None) -> int | None:
        if not subnet_id or vpc_pk is None:
            return None
        return ctx.subnet(vpc_pk, az_pk, subnet_id, data.subnet_cidrs.get(subnet_id))

    sg_pks = set()
    if vpc_pk is not None:
        for group_id, name in inst.security_groups:
            sg_pks.add((ctx.security_group(vpc_pk, group_id, data.sg_names.get(group_id) or name),))

    cols = {
        "instance_type_id": ctx.instance_type(
            inst.instance_type, data.type_info.get(inst.instance_type)
        ),
        "availability_zone_id": az_pk,
        "subnet_pk": subnet_pk(inst.subnet_id),
        "key_pair_id": ctx.key_pair(inst.key_name) if inst.key_name else None,
        "iam_instance_profile_id": ctx.iam_profile(inst.iam_profile_arn)
        if inst.iam_profile_arn
        else None,
        "image_id": inst.image_id,
        "state": inst.state,
        "architecture": inst.architecture,
        "platform": inst.platform,
        "launch_time": inst.launch_time,
        "private_ip": inst.private_ip,
        "public_ip": inst.public_ip,
        "monitoring": inst.monitoring,
    }
    children: list[Child] = [
        (
            InstanceTag,
            "instance_pk",
            ("tag_key", "tag_value"),
            {(_clip(k, 128), _clip(v, 256)) for k, v in inst.tags.items()},
        ),
        (InstanceSecurityGroup, "instance_pk", ("security_group_pk",), sg_pks),
        (
            InstanceVolume,
            "instance_pk",
            ("device_name", "volume_id", "size_gib", "volume_type"),
            {(v.device_name, v.volume_id, None, None) for v in inst.volumes},
        ),
        (
            InstanceNetworkInterface,
            "instance_pk",
            ("eni_id", "subnet_pk", "private_ip", "public_ip"),
            {
                (n.eni_id, subnet_pk(n.subnet_id), n.private_ip, n.public_ip)
                for n in inst.network_interfaces
            },
        ),
    ]
    key = {
        "account_id": ctx.account_pk,
        "region_id": ctx.region_pk,
        "instance_id": inst.instance_id,
    }
    return _sync(ctx, Instance, key, cols, children)


def load_amis(ctx: LoadContext, data: Collected) -> Counts:
    counts = Counts()
    for ami in data.amis:
        counts.add(_load_ami(ctx, ami))
    return counts


def _load_ami(ctx: LoadContext, ami: AmiRecord) -> str:
    cols = {
        "owner_aws_account_id": ami.owner_aws_account_id,
        "name": _clip(ami.name, 255),
        "description": _clip(ami.description, 1024),
        "creation_date": ami.creation_date,
        "state": ami.state,
        "architecture": ami.architecture,
        "platform": ami.platform,
        "root_device_type": ami.root_device_type,
        "virtualization_type": ami.virtualization_type,
        "is_public": bool(ami.is_public),
        "deprecation_time": ami.deprecation_time,
    }
    children: list[Child] = [
        (
            AmiTag,
            "ami_pk",
            ("tag_key", "tag_value"),
            {(_clip(k, 128), _clip(v, 256)) for k, v in ami.tags.items()},
        ),
        (
            AmiBlockDeviceMapping,
            "ami_pk",
            ("device_name", "snapshot_id", "size_gib"),
            {(b.device_name, b.snapshot_id, b.size_gib) for b in ami.block_mappings},
        ),
    ]
    key = {"account_id": ctx.account_pk, "region_id": ctx.region_pk, "image_id": ami.image_id}
    return _sync(ctx, Ami, key, cols, children)
