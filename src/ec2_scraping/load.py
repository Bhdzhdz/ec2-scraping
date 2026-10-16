"""Transactional upserts of collected data into the 001 schema (MariaDB)."""

from typing import Any

from ec2_scraping.models import AmiRecord, Collected, Counts, InstanceRecord


def _upsert_ref(cur, table: str, keys: dict[str, Any], extra: dict[str, Any] | None = None) -> int:
    """Insert-or-update a reference row on its unique key and return its id."""
    extra = extra or {}
    cols = {**keys, **extra}
    names = ", ".join(f"`{c}`" for c in cols)
    marks = ", ".join(["%s"] * len(cols))
    updates = ["id = LAST_INSERT_ID(id)"] + [
        f"`{c}` = COALESCE(VALUES(`{c}`), `{c}`)" for c in extra
    ]
    cur.execute(
        f"INSERT INTO `{table}` ({names}) VALUES ({marks}) "
        f"ON DUPLICATE KEY UPDATE {', '.join(updates)}",
        tuple(cols.values()),
    )
    return cur.lastrowid


def upsert_account(cur, aws_account_id: str) -> int:
    return _upsert_ref(cur, "account", {"aws_account_id": aws_account_id})


def upsert_region(cur, code: str) -> int:
    return _upsert_ref(cur, "region", {"code": code})


def upsert_availability_zone(cur, region_id: int, name: str) -> int:
    return _upsert_ref(cur, "availability_zone", {"region_id": region_id, "name": name})


def upsert_instance_type(
    cur,
    name: str,
    vcpu: int | None = None,
    memory_mib: int | None = None,
    architecture: str | None = None,
) -> int:
    return _upsert_ref(
        cur,
        "instance_type",
        {"name": name},
        {"vcpu": vcpu, "memory_mib": memory_mib, "architecture": architecture},
    )


def upsert_key_pair(cur, account_id: int, region_id: int, name: str) -> int:
    return _upsert_ref(
        cur, "key_pair", {"account_id": account_id, "region_id": region_id, "name": name}
    )


def upsert_iam_instance_profile(cur, account_id: int, region_id: int, arn: str) -> int:
    return _upsert_ref(
        cur, "iam_instance_profile", {"account_id": account_id, "region_id": region_id, "arn": arn}
    )


def upsert_vpc(cur, account_id: int, region_id: int, vpc_id: str, cidr: str | None = None) -> int:
    return _upsert_ref(
        cur,
        "vpc",
        {"account_id": account_id, "region_id": region_id, "vpc_id": vpc_id},
        {"cidr": cidr},
    )


def upsert_subnet(
    cur, vpc_pk: int, availability_zone_id: int, subnet_id: str, cidr: str | None = None
) -> int:
    return _upsert_ref(
        cur,
        "subnet",
        {"vpc_pk": vpc_pk, "subnet_id": subnet_id},
        {"availability_zone_id": availability_zone_id, "cidr": cidr},
    )


def upsert_security_group(cur, vpc_pk: int, group_id: str, name: str | None = None) -> int:
    return _upsert_ref(
        cur, "security_group", {"vpc_pk": vpc_pk, "group_id": group_id}, {"name": name}
    )


class LoadContext:
    """One account/region load: memoises reference lookups for the whole combination."""

    def __init__(self, cur, run_id: int, account_pk: int, region_pk: int):
        self.cur = cur
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
            ("az", name), lambda: upsert_availability_zone(self.cur, self.region_pk, name)
        )

    def instance_type(self, name: str, info) -> int:
        return self._memo(
            ("type", name),
            lambda: upsert_instance_type(
                self.cur,
                name,
                *((info.vcpu, info.memory_mib, info.architecture) if info else (None, None, None)),
            ),
        )

    def key_pair(self, name: str) -> int:
        return self._memo(
            ("key", name), lambda: upsert_key_pair(self.cur, self.account_pk, self.region_pk, name)
        )

    def iam_profile(self, arn: str) -> int:
        return self._memo(
            ("iam", arn),
            lambda: upsert_iam_instance_profile(self.cur, self.account_pk, self.region_pk, arn),
        )

    def vpc(self, vpc_id: str, cidr: str | None) -> int:
        return self._memo(
            ("vpc", vpc_id),
            lambda: upsert_vpc(self.cur, self.account_pk, self.region_pk, vpc_id, cidr),
        )

    def subnet(self, vpc_pk: int, az_pk: int, subnet_id: str, cidr: str | None) -> int:
        return self._memo(
            ("subnet", vpc_pk, subnet_id),
            lambda: upsert_subnet(self.cur, vpc_pk, az_pk, subnet_id, cidr),
        )

    def security_group(self, vpc_pk: int, group_id: str, name: str | None) -> int:
        return self._memo(
            ("sg", vpc_pk, group_id),
            lambda: upsert_security_group(self.cur, vpc_pk, group_id, name),
        )


Child = tuple[str, str, tuple[str, ...], set[tuple]]  # table, fk column, columns, rows


def _sync(ctx: LoadContext, table: str, key: dict, cols: dict, children: list[Child]) -> str:
    """Upsert one resource and its child rows; return created/updated/unchanged."""
    cur = ctx.cur
    where = " AND ".join(f"`{k}` = %s" for k in key)
    cur.execute(f"SELECT * FROM `{table}` WHERE {where}", tuple(key.values()))
    row = cur.fetchone()

    if row is None:
        all_cols = {**key, **cols, "last_scrape_run_id": ctx.run_id}
        names = ", ".join(f"`{c}`" for c in all_cols)
        marks = ", ".join(["%s"] * len(all_cols))
        cur.execute(f"INSERT INTO `{table}` ({names}) VALUES ({marks})", tuple(all_cols.values()))
        _replace_children(cur, cur.lastrowid, children)
        return "created"

    pk = row["id"]
    changed = any(row[c] != v for c, v in cols.items())
    if not changed:
        for child_table, fk, names, rows in children:
            formated_names = ", ".join(f"`{n}`" for n in names)
            cur.execute(
                f"SELECT {formated_names} FROM `{child_table}` WHERE `{fk}` = %s",
                (pk,),
            )
            if {tuple(r[n] for n in names) for r in cur.fetchall()} != rows:
                changed = True
                break

    sets = ["last_seen_at = NOW()", "last_scrape_run_id = %s"]
    args: list[Any] = [ctx.run_id]
    if changed:
        sets += [f"`{c}` = %s" for c in cols]
        args += list(cols.values())
    cur.execute(f"UPDATE `{table}` SET {', '.join(sets)} WHERE id = %s", (*args, pk))
    if changed:
        _replace_children(cur, pk, children)
        return "updated"
    return "unchanged"


def _replace_children(cur, pk: int, children: list[Child]) -> None:
    for table, fk, names, rows in children:
        cur.execute(f"DELETE FROM `{table}` WHERE `{fk}` = %s", (pk,))
        if rows:
            cols = ", ".join(f"`{n}`" for n in (fk, *names))
            marks = ", ".join(["%s"] * (len(names) + 1))
            cur.executemany(
                f"INSERT INTO `{table}` ({cols}) VALUES ({marks})",
                [(pk, *r) for r in sorted(rows, key=repr)],
            )


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
            "instance_tag",
            "instance_pk",
            ("tag_key", "tag_value"),
            {(_clip(k, 128), _clip(v, 256)) for k, v in inst.tags.items()},
        ),
        ("instance_security_group", "instance_pk", ("security_group_pk",), sg_pks),
        (
            "instance_volume",
            "instance_pk",
            ("device_name", "volume_id", "size_gib", "volume_type"),
            {(v.device_name, v.volume_id, None, None) for v in inst.volumes},
        ),
        (
            "instance_network_interface",
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
    return _sync(ctx, "instance", key, cols, children)


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
        "is_public": int(ami.is_public),
        "deprecation_time": ami.deprecation_time,
    }
    children: list[Child] = [
        (
            "ami_tag",
            "ami_pk",
            ("tag_key", "tag_value"),
            {(_clip(k, 128), _clip(v, 256)) for k, v in ami.tags.items()},
        ),
        (
            "ami_block_device_mapping",
            "ami_pk",
            ("device_name", "snapshot_id", "size_gib"),
            {(b.device_name, b.snapshot_id, b.size_gib) for b in ami.block_mappings},
        ),
    ]
    key = {"account_id": ctx.account_pk, "region_id": ctx.region_pk, "image_id": ami.image_id}
    return _sync(ctx, "ami", key, cols, children)
