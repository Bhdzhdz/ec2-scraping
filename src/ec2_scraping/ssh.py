"""Async SSH collector: probes common usernames and gathers OS/system facts."""

import asyncio
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import asyncssh

from ec2_scraping.models import EnrichmentResult, InstanceRecord

DEFAULT_SSH_USERS: tuple[str, ...] = (
    "ec2-user",
    "ubuntu",
    "admin",
    "centos",
    "debian",
    "fedora",
    "rocky",
    "almalinux",
    "suse",
    "bitnami",
    "root",
)

DEFAULT_KEY_NAMES: tuple[str, ...] = (
    "id_ed25519",
    "id_ecdsa",
    "id_rsa",
    "id_dsa",
)

PROBE_SCRIPT = r"""
echo "===SECTION:OS_RELEASE==="
cat /etc/os-release 2>/dev/null || cat /usr/lib/os-release 2>/dev/null || true
echo "===SECTION:UNAME==="
uname -s -r -m 2>/dev/null || true
echo "===SECTION:HOSTNAME==="
hostname -f 2>/dev/null || hostname 2>/dev/null || true
echo "===SECTION:UPTIME==="
cat /proc/uptime 2>/dev/null || true
echo "===SECTION:LOADAVG==="
cat /proc/loadavg 2>/dev/null || true
echo "===SECTION:CPU==="
grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2- \
  || lscpu 2>/dev/null | grep -m1 'Model name:' | cut -d: -f2- || true
echo "===SECTION:MEM==="
grep -E '^(MemTotal|MemAvailable|SwapTotal):' /proc/meminfo 2>/dev/null || true
echo "===SECTION:DISK==="
df -P -k / 2>/dev/null | tail -n 1 || true
echo "===SECTION:PKGS==="
if command -v dpkg-query >/dev/null 2>&1; then
  dpkg-query -f '.\n' -W 2>/dev/null | wc -l
elif command -v rpm >/dev/null 2>&1; then
  rpm -qa 2>/dev/null | wc -l
elif command -v apk >/dev/null 2>&1; then
  apk info 2>/dev/null | wc -l
fi
echo "===SECTION:SERVICES==="
if command -v systemctl >/dev/null 2>&1; then
  systemctl list-units --type=service --state=running --no-legend --no-pager 2>/dev/null \
    | awk '{print $1}' | head -n 50
fi
echo "===SECTION:PORTS==="
if command -v ss >/dev/null 2>&1; then
  ss -tlnH 2>/dev/null | awk '{print $4}'
elif command -v netstat >/dev/null 2>&1; then
  netstat -tln 2>/dev/null | awk 'NR>2 {print $4}'
fi
echo "===SECTION:CONTAINERS==="
if command -v docker >/dev/null 2>&1; then
  docker ps --format '{{.Names}}|{{.Image}}' 2>/dev/null || true
elif command -v podman >/dev/null 2>&1; then
  podman ps --format '{{.Names}}|{{.Image}}' 2>/dev/null || true
fi
echo "===SECTION:REBOOT==="
if [ -f /var/run/reboot-required ] || [ -f /run/reboot-required ]; then
  echo "yes"
elif command -v needs-restarting >/dev/null 2>&1; then
  needs-restarting -r >/dev/null 2>&1 && echo "no" || echo "yes"
else
  echo "no"
fi
echo "===SECTION:USERS==="
who 2>/dev/null | awk '{print $1}' | sort -u || true
echo "===SECTION:SUDO==="
sudo -n true >/dev/null 2>&1 && echo "yes" || echo "no"
echo "===SECTION:END==="
""".strip()


def resolve_target_host(inst: InstanceRecord, *, prefer_public_ip: bool = False) -> str | None:
    """Pick the IP/hostname to connect to for an instance."""
    candidates = (
        (inst.public_ip, inst.private_ip, inst.public_dns_name, inst.private_dns_name)
        if prefer_public_ip
        else (inst.private_ip, inst.public_ip, inst.private_dns_name, inst.public_dns_name)
    )
    for host in candidates:
        if host:
            return host
    return None


def resolve_client_keys(
    inst: InstanceRecord,
    key_files: Sequence[str | Path] = (),
    key_dir: str | Path | None = None,
    default_ssh_dir: Path | None = None,
) -> list[str]:
    """Build ordered list of existing private key paths to offer for ``inst``."""
    found: list[str] = []
    seen: set[str] = set()

    def _add(p: Path) -> None:
        resolved = str(p.expanduser())
        if resolved not in seen and p.expanduser().is_file():
            seen.add(resolved)
            found.append(resolved)

    if key_dir and inst.key_name:
        base = Path(key_dir).expanduser()
        for candidate in (base / inst.key_name, base / f"{inst.key_name}.pem"):
            _add(candidate)

    for kf in key_files:
        _add(Path(kf))

    if key_dir:
        base = Path(key_dir).expanduser()
        if base.is_dir():
            for child in sorted(base.iterdir()):
                if child.is_file() and not child.name.endswith(".pub"):
                    _add(child)

    ssh_dir = default_ssh_dir if default_ssh_dir is not None else Path.home() / ".ssh"
    for name in DEFAULT_KEY_NAMES:
        _add(ssh_dir / name)

    return found


def ordered_candidate_users(
    inst: InstanceRecord,
    users: Sequence[str] = DEFAULT_SSH_USERS,
    ami_name: str | None = None,
) -> list[str]:
    """Order candidate usernames, prioritizing likely OS matches from AMI/platform hints."""
    hint = f"{ami_name or ''} {inst.platform_details or ''}".lower()
    prioritized: list[str] = []
    if "ubuntu" in hint:
        prioritized.append("ubuntu")
    elif "debian" in hint:
        prioritized.append("debian")
    elif "centos" in hint:
        prioritized.append("centos")
    elif "fedora" in hint:
        prioritized.append("fedora")
    elif "rocky" in hint:
        prioritized.append("rocky")
    elif "alma" in hint:
        prioritized.append("almalinux")
    elif "suse" in hint or "sles" in hint:
        prioritized.append("suse")
    elif "bitnami" in hint:
        prioritized.append("bitnami")
    elif "amzn" in hint or "amazon" in hint or "rhel" in hint:
        prioritized.append("ec2-user")

    ordered: list[str] = []
    for u in (*prioritized, *users):
        if u and u not in ordered:
            ordered.append(u)
    return ordered


def _parse_os_release(raw: str) -> dict[str, str]:
    info: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        info[k.strip()] = v.strip().strip('"').strip("'")
    return info


def _parse_port(addr: str) -> int | None:
    addr = addr.strip()
    if not addr or ":" not in addr:
        return None
    port_str = addr.rsplit(":", 1)[-1]
    return int(port_str) if port_str.isdigit() else None


def parse_probe_output(output: str, user: str, host: str, port: int) -> dict[str, Any]:
    """Parse structured probe output into analytical SSH facts."""
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in output.splitlines():
        if line.startswith("===SECTION:") and line.endswith("==="):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = line.removeprefix("===SECTION:").removesuffix("===")
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None and current != "END":
        sections[current] = "\n".join(buf).strip()

    os_rel = _parse_os_release(sections.get("OS_RELEASE", ""))
    uname_parts = sections.get("UNAME", "").split()
    kernel = uname_parts[1] if len(uname_parts) >= 2 else (uname_parts[0] if uname_parts else None)
    arch = uname_parts[2] if len(uname_parts) >= 3 else None

    uptime_seconds: int | None = None
    uptime_raw = sections.get("UPTIME", "").split()
    if uptime_raw:
        try:
            uptime_seconds = int(float(uptime_raw[0]))
        except ValueError:
            uptime_seconds = None

    load_avg: list[float] | None = None
    load_parts = sections.get("LOADAVG", "").split()
    if len(load_parts) >= 3:
        try:
            load_avg = [float(load_parts[0]), float(load_parts[1]), float(load_parts[2])]
        except ValueError:
            load_avg = None

    mem_info: dict[str, int] = {}
    for line in sections.get("MEM", "").splitlines():
        if ":" in line:
            k, rest = line.split(":", 1)
            toks = rest.split()
            if toks and toks[0].isdigit():
                mem_info[k.strip()] = int(toks[0]) // 1024  # kB -> MiB

    root_disk: dict[str, Any] | None = None
    disk_parts = sections.get("DISK", "").split()
    if len(disk_parts) >= 5 and disk_parts[1].isdigit() and disk_parts[2].isdigit():
        total_kb = int(disk_parts[1])
        used_kb = int(disk_parts[2])
        avail_kb = int(disk_parts[3]) if disk_parts[3].isdigit() else None
        pct_str = disk_parts[4].rstrip("%")
        root_disk = {
            "filesystem": disk_parts[0],
            "total_mib": total_kb // 1024,
            "used_mib": used_kb // 1024,
            "avail_mib": avail_kb // 1024 if avail_kb is not None else None,
            "used_pct": int(pct_str) if pct_str.isdigit() else None,
        }

    pkg_raw = sections.get("PKGS", "").strip()
    package_count = int(pkg_raw) if pkg_raw.isdigit() else None

    services = [s.strip() for s in sections.get("SERVICES", "").splitlines() if s.strip()]

    ports_set: set[int] = set()
    for line in sections.get("PORTS", "").splitlines():
        p = _parse_port(line)
        if p is not None:
            ports_set.add(p)
    listening_ports = sorted(ports_set)

    containers: list[dict[str, str]] = []
    for line in sections.get("CONTAINERS", "").splitlines():
        if "|" in line:
            cname, cimage = line.split("|", 1)
            containers.append({"name": cname.strip(), "image": cimage.strip()})

    reboot_raw = sections.get("REBOOT", "").strip().lower()
    reboot_required = True if reboot_raw == "yes" else (False if reboot_raw == "no" else None)

    sudo_raw = sections.get("SUDO", "").strip().lower()
    passwordless_sudo = True if sudo_raw == "yes" else (False if sudo_raw == "no" else None)

    logged_in_users = [u.strip() for u in sections.get("USERS", "").splitlines() if u.strip()]
    cpu_model = sections.get("CPU", "").strip() or None
    hostname = sections.get("HOSTNAME", "").strip() or None

    return {
        "ssh_user": user,
        "ssh_host": host,
        "ssh_port": port,
        "os_id": os_rel.get("ID"),
        "os_version": os_rel.get("VERSION_ID"),
        "os_pretty_name": os_rel.get("PRETTY_NAME") or os_rel.get("NAME"),
        "os_id_like": os_rel.get("ID_LIKE"),
        "kernel": kernel,
        "architecture": arch,
        "hostname": hostname,
        "uptime_seconds": uptime_seconds,
        "load_avg": load_avg,
        "cpu_model": cpu_model,
        "mem_total_mib": mem_info.get("MemTotal"),
        "mem_available_mib": mem_info.get("MemAvailable"),
        "swap_total_mib": mem_info.get("SwapTotal"),
        "root_disk": root_disk,
        "package_count": package_count,
        "running_services": services,
        "listening_ports": listening_ports,
        "listening_port_count": len(listening_ports),
        "containers": containers,
        "container_count": len(containers),
        "reboot_required": reboot_required,
        "passwordless_sudo": passwordless_sudo,
        "logged_in_users": logged_in_users,
    }


class SshCollector:
    """Async SSH enricher that tries candidate usernames and gathers OS/system telemetry."""

    name = "ssh"

    def __init__(
        self,
        *,
        users: Sequence[str] = DEFAULT_SSH_USERS,
        key_files: Sequence[str | Path] = (),
        key_dir: str | Path | None = None,
        port: int = 22,
        connect_timeout: float = 5.0,
        command_timeout: float = 15.0,
        concurrency: int = 32,
        prefer_public_ip: bool = False,
        only_unaccessed: bool = False,
        connect_fn: Callable = asyncssh.connect,
    ):
        self.users = tuple(users) if users else DEFAULT_SSH_USERS
        self.key_files = tuple(key_files)
        self.key_dir = key_dir
        self.port = port
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self.concurrency = max(1, concurrency)
        self.prefer_public_ip = prefer_public_ip
        self.only_unaccessed = only_unaccessed
        self.connect_fn = connect_fn

    async def _probe_instance(
        self,
        inst: InstanceRecord,
        ami_name: str | None = None,
    ) -> EnrichmentResult:
        if inst.state != "running":
            return EnrichmentResult(status="skipped", error=f"instance state is {inst.state}")
        if (inst.platform or "").lower() == "windows":
            return EnrichmentResult(status="skipped", error="windows platform skipped")

        host = resolve_target_host(inst, prefer_public_ip=self.prefer_public_ip)
        if not host:
            return EnrichmentResult(status="skipped", error="no reachable IP or DNS name")

        client_keys = resolve_client_keys(inst, self.key_files, self.key_dir)
        candidates = ordered_candidate_users(inst, self.users, ami_name)

        tried_errors: list[str] = []
        for user in candidates:
            try:
                connect_kwargs: dict[str, Any] = {
                    "host": host,
                    "port": self.port,
                    "username": user,
                    "known_hosts": None,
                    "preferred_auth": "publickey",
                    "login_timeout": self.connect_timeout,
                }
                if client_keys:
                    connect_kwargs["client_keys"] = client_keys

                async with self.connect_fn(**connect_kwargs) as conn:
                    res = await asyncio.wait_for(
                        conn.run(PROBE_SCRIPT, check=False),
                        timeout=self.command_timeout,
                    )
                    stdout = res.stdout if isinstance(res.stdout, str) else str(res.stdout or "")
                    facts = parse_probe_output(stdout, user, host, self.port)
                    facts["attempted_users"] = candidates[: candidates.index(user) + 1]
                    return EnrichmentResult(status="succeeded", facts=facts)
            except asyncssh.PermissionDenied as exc:
                tried_errors.append(f"{user}: {exc}")
                continue
            except (TimeoutError, OSError, asyncssh.DisconnectError, asyncssh.Error) as exc:
                # Network/socket failure or non-auth disconnect: abort further username retries
                if isinstance(exc, asyncssh.Error) and "auth" in str(exc).lower():
                    tried_errors.append(f"{user}: {exc}")
                    continue
                return EnrichmentResult(
                    status="failed",
                    error=f"{host}:{self.port} ({user}): {type(exc).__name__}: {exc}",
                )

        return EnrichmentResult(
            status="failed",
            error=f"authentication failed for users {list(candidates)} on {host}:{self.port}",
        )

    async def enrich_many_async(
        self,
        aws_account_id: str,
        region: str,
        instances: Sequence[InstanceRecord],
        ami_names: dict[str, str | None] | None = None,
    ) -> dict[str, EnrichmentResult]:
        sem = asyncio.Semaphore(self.concurrency)
        ami_names = ami_names or {}

        async def _guarded(inst: InstanceRecord) -> tuple[str, EnrichmentResult]:
            async with sem:
                res = await self._probe_instance(inst, ami_names.get(inst.image_id))
                return inst.instance_id, res

        pairs = await asyncio.gather(*(_guarded(i) for i in instances))
        return dict(pairs)

    def enrich_batch(
        self,
        aws_account_id: str,
        region: str,
        instances: Sequence[InstanceRecord],
        ami_names: dict[str, str | None] | None = None,
    ) -> dict[str, EnrichmentResult]:
        return asyncio.run(self.enrich_many_async(aws_account_id, region, instances, ami_names))

    def enrich(
        self, aws_account_id: str, region: str, instance: InstanceRecord
    ) -> EnrichmentResult:
        return asyncio.run(self._probe_instance(instance))
