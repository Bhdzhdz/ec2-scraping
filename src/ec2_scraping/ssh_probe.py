"""SSH probe script and output parser for OS/system telemetry."""

from __future__ import annotations

from typing import Any

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
if [ -f /var/lib/dpkg/status ]; then
  grep -c '^Status: install ok installed$' /var/lib/dpkg/status 2>/dev/null || true
elif command -v dpkg-query >/dev/null 2>&1; then
  dpkg-query -f '.\n' -W 2>/dev/null | wc -l
elif [ -f /var/lib/rpm/rpmdb.sqlite ] && command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 /var/lib/rpm/rpmdb.sqlite 'SELECT count(*) FROM Packages;' 2>/dev/null \
    || rpm -qa 2>/dev/null | wc -l
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

_MIN_UNAME_PARTS = 2
_ARCH_UNAME_PARTS = 3
_LOADAVG_PARTS = 3
_DISK_PARTS = 5
_KIB_PER_MIB = 1024


def _parse_os_release(raw: str) -> dict[str, str]:
    info: dict[str, str] = {}
    for raw_line in raw.splitlines():
        line = raw_line.strip()
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


def _split_sections(output: str) -> dict[str, str]:
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
    return sections


def _parse_uname(raw: str) -> tuple[str | None, str | None]:
    parts = raw.split()
    if not parts:
        return None, None
    kernel = parts[1] if len(parts) >= _MIN_UNAME_PARTS else parts[0]
    arch = parts[2] if len(parts) >= _ARCH_UNAME_PARTS else None
    return kernel, arch


def _parse_uptime(raw: str) -> int | None:
    parts = raw.split()
    if not parts:
        return None
    try:
        return int(float(parts[0]))
    except ValueError:
        return None


def _parse_loadavg(raw: str) -> list[float] | None:
    parts = raw.split()
    if len(parts) < _LOADAVG_PARTS:
        return None
    try:
        return [float(parts[0]), float(parts[1]), float(parts[2])]
    except ValueError:
        return None


def _parse_mem(raw: str) -> dict[str, int]:
    mem_info: dict[str, int] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        k, rest = line.split(":", 1)
        toks = rest.split()
        if toks and toks[0].isdigit():
            mem_info[k.strip()] = int(toks[0]) // _KIB_PER_MIB
    return mem_info


def _parse_disk(raw: str) -> dict[str, Any] | None:
    parts = raw.split()
    if len(parts) < _DISK_PARTS or not (parts[1].isdigit() and parts[2].isdigit()):
        return None
    avail_kb = int(parts[3]) if parts[3].isdigit() else None
    pct_str = parts[4].rstrip("%")
    return {
        "filesystem": parts[0],
        "total_mib": int(parts[1]) // _KIB_PER_MIB,
        "used_mib": int(parts[2]) // _KIB_PER_MIB,
        "avail_mib": avail_kb // _KIB_PER_MIB if avail_kb is not None else None,
        "used_pct": int(pct_str) if pct_str.isdigit() else None,
    }


def _parse_containers(raw: str) -> list[dict[str, str]]:
    containers: list[dict[str, str]] = []
    for line in raw.splitlines():
        if "|" in line:
            cname, cimage = line.split("|", 1)
            containers.append({"name": cname.strip(), "image": cimage.strip()})
    return containers


def _parse_yes_no(raw: str) -> bool | None:
    val = raw.strip().lower()
    if val == "yes":
        return True
    return False if val == "no" else None


def _parse_ports(raw: str) -> list[int]:
    ports: set[int] = set()
    for line in raw.splitlines():
        p = _parse_port(line)
        if p is not None:
            ports.add(p)
    return sorted(ports)


def _nonempty_lines(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def parse_probe_output(output: str, user: str, host: str, port: int) -> dict[str, Any]:
    """Parse structured probe output into analytical SSH facts."""
    sections = _split_sections(output)
    os_rel = _parse_os_release(sections.get("OS_RELEASE", ""))
    kernel, arch = _parse_uname(sections.get("UNAME", ""))
    mem_info = _parse_mem(sections.get("MEM", ""))
    pkg_raw = sections.get("PKGS", "").strip()
    listening_ports = _parse_ports(sections.get("PORTS", ""))
    containers = _parse_containers(sections.get("CONTAINERS", ""))

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
        "hostname": sections.get("HOSTNAME", "").strip() or None,
        "uptime_seconds": _parse_uptime(sections.get("UPTIME", "")),
        "load_avg": _parse_loadavg(sections.get("LOADAVG", "")),
        "cpu_model": sections.get("CPU", "").strip() or None,
        "mem_total_mib": mem_info.get("MemTotal"),
        "mem_available_mib": mem_info.get("MemAvailable"),
        "swap_total_mib": mem_info.get("SwapTotal"),
        "root_disk": _parse_disk(sections.get("DISK", "")),
        "package_count": int(pkg_raw) if pkg_raw.isdigit() else None,
        "running_services": _nonempty_lines(sections.get("SERVICES", "")),
        "listening_ports": listening_ports,
        "listening_port_count": len(listening_ports),
        "containers": containers,
        "container_count": len(containers),
        "reboot_required": _parse_yes_no(sections.get("REBOOT", "")),
        "passwordless_sudo": _parse_yes_no(sections.get("SUDO", "")),
        "logged_in_users": _nonempty_lines(sections.get("USERS", "")),
    }
