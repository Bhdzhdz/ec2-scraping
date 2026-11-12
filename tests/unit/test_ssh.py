"""Unit tests for the async SSH collector: user rotation, key resolution, and probe parsing."""

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import asyncssh
import pytest

from ec2_scraping import cli, load, runner, ssh
from ec2_scraping.db.models import Instance
from ec2_scraping.models import Collected, InstanceRecord

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

SAMPLE_PROBE_OUTPUT = """===SECTION:OS_RELEASE===
NAME="Ubuntu"
VERSION_ID="24.04"
ID=ubuntu
ID_LIKE=debian
PRETTY_NAME="Ubuntu 24.04.1 LTS"
===SECTION:UNAME===
Linux 6.8.0-1015-aws x86_64
===SECTION:HOSTNAME===
ip-10-0-0-1.ec2.internal
===SECTION:UPTIME===
86400.42 172000.00
===SECTION:LOADAVG===
0.15 0.10 0.05 1/200 1234
===SECTION:CPU===
 Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz
===SECTION:MEM===
MemTotal:        8052480 kB
MemAvailable:    6200000 kB
SwapTotal:             0 kB
===SECTION:DISK===
/dev/root 20971520 5242880 15728640 25% /
===SECTION:PKGS===
642
===SECTION:SERVICES===
 cron.service
 ssh.service
 docker.service
===SECTION:PORTS===
0.0.0.0:22
127.0.0.53%lo:53
[::]:443
===SECTION:CONTAINERS===
web|nginx:alpine
redis|redis:7
===SECTION:REBOOT===
yes
===SECTION:USERS===
ubuntu
===SECTION:SUDO===
yes
===SECTION:END===
"""

_EXPECTED_PARSED_FACTS: dict[str, Any] = {
    "ssh_user": "ubuntu",
    "ssh_host": "10.0.0.1",
    "ssh_port": 22,
    "os_id": "ubuntu",
    "os_version": "24.04",
    "os_pretty_name": "Ubuntu 24.04.1 LTS",
    "os_id_like": "debian",
    "kernel": "6.8.0-1015-aws",
    "architecture": "x86_64",
    "hostname": "ip-10-0-0-1.ec2.internal",
    "uptime_seconds": 86400,
    "load_avg": [0.15, 0.1, 0.05],
    "cpu_model": "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz",
    "mem_total_mib": 7863,
    "mem_available_mib": 6054,
    "swap_total_mib": 0,
    "root_disk": {
        "filesystem": "/dev/root",
        "total_mib": 20480,
        "used_mib": 5120,
        "avail_mib": 15360,
        "used_pct": 25,
    },
    "package_count": 642,
    "running_services": ["cron.service", "ssh.service", "docker.service"],
    "listening_ports": [22, 53, 443],
    "listening_port_count": 3,
    "containers": [
        {"name": "web", "image": "nginx:alpine"},
        {"name": "redis", "image": "redis:7"},
    ],
    "container_count": 2,
    "reboot_required": True,
    "passwordless_sudo": True,
    "logged_in_users": ["ubuntu"],
}


class _FakeConn:
    async def run(self, _script: str, **_kw: Any) -> SimpleNamespace:
        return SimpleNamespace(stdout=SAMPLE_PROBE_OUTPUT)


def _inst(**kw: Any) -> InstanceRecord:
    base: dict[str, Any] = {
        "instance_id": "i-1",
        "instance_type": "t3.micro",
        "availability_zone": "us-east-1a",
        "image_id": "ami-1",
        "state": "running",
        "architecture": "x86_64",
        "launch_time": datetime(2026, 1, 1),
        "private_ip": "10.0.0.1",
        "public_ip": "1.2.3.4",
        "key_name": "my-key",
    }
    base.update(kw)
    return InstanceRecord(**base)


def test_parse_probe_output_extracts_all_sections() -> None:
    facts = ssh.parse_probe_output(SAMPLE_PROBE_OUTPUT, "ubuntu", "10.0.0.1", 22)
    assert facts == _EXPECTED_PARSED_FACTS


@pytest.mark.parametrize(
    ("ami_name", "expected_first"),
    [
        ("CentOS Stream 9", "centos"),
        ("amzn2-ami-hvm", "ec2-user"),
        ("ubuntu/images/hvm-ssd/ubuntu-noble-24.04", "ubuntu"),
    ],
)
def test_ordered_candidate_users_prioritizes_distro_hint(
    ami_name: str, expected_first: str
) -> None:
    users = ssh.ordered_candidate_users(_inst(), ami_name=ami_name)
    assert users[0] == expected_first
    assert set(ssh.DEFAULT_SSH_USERS).issubset(set(users))

    restricted = ssh.ordered_candidate_users(
        _inst(), users=("admin", "root"), ami_name="ubuntu/images/hvm-ssd/ubuntu-noble-24.04"
    )
    assert restricted == ["admin", "root"]


def test_ordered_candidate_users_prioritizes_last_known_user() -> None:
    users = ssh.ordered_candidate_users(
        _inst(),
        ami_name="amzn2-ami-hvm",
        last_known_user="centos",
        ami_known_user="ubuntu",
    )
    assert users[:3] == ["centos", "ubuntu", "ec2-user"]

    custom = ssh.ordered_candidate_users(_inst(), last_known_user="deploy")
    assert custom[0] == "deploy"
    assert custom[1:] == list(ssh.DEFAULT_SSH_USERS)


def test_resolve_target_host_and_client_keys(tmp_path: Path) -> None:
    inst = _inst()
    assert ssh.resolve_target_host(inst) == "10.0.0.1"
    assert ssh.resolve_target_host(inst, prefer_public_ip=True) == "1.2.3.4"
    assert ssh.resolve_target_host(_inst(private_ip=None, public_ip=None)) is None

    key_dir = tmp_path / "keys"
    key_dir.mkdir()
    pem = key_dir / "my-key.pem"
    pem.write_text("KEY")
    other = key_dir / "other.pem"
    other.write_text("KEY")
    (key_dir / "other.pem.pub").write_text("PUB")
    explicit = tmp_path / "explicit_id"
    explicit.write_text("KEY")
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    default_key = ssh_dir / "id_ed25519"
    default_key.write_text("KEY")

    keys = ssh.resolve_client_keys(inst, [explicit], key_dir=key_dir, default_ssh_dir=ssh_dir)
    assert keys == [str(pem), str(explicit), str(other), str(default_key)]


def test_ssh_collector_rotates_users_and_handles_states() -> None:
    attempts: list[tuple[str, str]] = []

    @asynccontextmanager
    async def fake_connect(**kwargs: Any) -> AsyncGenerator[_FakeConn]:
        host = kwargs["host"]
        user = kwargs["username"]
        attempts.append((host, user))
        if host == "10.0.0.99":
            msg = "timed out"
            raise TimeoutError(msg)
        if user != "ubuntu":
            msg = "Permission denied"
            raise asyncssh.PermissionDenied(msg)
        yield _FakeConn()

    collector = ssh.SshCollector(
        users=("ec2-user", "ubuntu", "debian"),
        connect_fn=fake_connect,
        concurrency=4,
    )

    instances = [
        _inst(instance_id="i-ok", private_ip="10.0.0.1"),
        _inst(instance_id="i-stopped", state="stopped"),
        _inst(instance_id="i-win", platform="windows"),
        _inst(instance_id="i-noip", private_ip=None, public_ip=None),
        _inst(instance_id="i-timeout", private_ip="10.0.0.99", image_id="ami-other"),
    ]
    results = collector.enrich_batch("111111111111", "us-east-1", instances)

    ok = results["i-ok"]
    assert ok.status == "succeeded"
    assert ok.facts is not None
    assert (ok.facts["ssh_user"], ok.facts["attempted_users"]) == (
        "ubuntu",
        ["ec2-user", "ubuntu"],
    )
    assert (
        results["i-stopped"].status,
        results["i-win"].status,
        results["i-noip"].status,
        results["i-timeout"].status,
    ) == ("skipped", "skipped", "skipped", "failed")
    assert ("10.0.0.99", "ec2-user") in attempts
    assert ("10.0.0.99", "ubuntu") not in attempts


def test_ssh_collector_all_users_denied_and_single_enrich() -> None:
    def always_denied(**_kwargs: Any) -> Any:
        msg = "denied"
        raise asyncssh.PermissionDenied(msg)

    collector = ssh.SshCollector(users=("ec2-user", "ubuntu"), connect_fn=always_denied)
    res = collector.enrich("111111111111", "us-east-1", _inst())
    assert res.status == "failed"
    assert "authentication failed" in (res.error or "")


def test_cli_build_enrichers() -> None:
    parser = cli.build_parser()
    assert cli._build_enrichers(parser.parse_args(["run", "--profile", "p"])) == []

    args_on = parser.parse_args(
        [
            "run",
            "--profile",
            "p",
            "--ssh",
            "--ssh-user",
            "ubuntu",
            "--ssh-port",
            "2222",
            "--ssh-prefer-public-ip",
        ]
    )
    enrichers = cli._build_enrichers(args_on)
    assert len(enrichers) == 1
    e0 = enrichers[0]
    assert isinstance(e0, ssh.SshCollector)
    assert (e0.users, e0.port, e0.prefer_public_ip, e0.only_unaccessed) == (
        ("ubuntu",),
        2222,
        True,
        False,
    )

    args_unaccessed = parser.parse_args(["run", "--profile", "p", "--ssh-only-unaccessed"])
    enrichers2 = cli._build_enrichers(args_unaccessed)
    assert isinstance(enrichers2[0], ssh.SshCollector)
    assert enrichers2[0].only_unaccessed is True


def test_ssh_only_unaccessed_skips_succeeded_and_preserves_previous_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probed: list[str] = []

    @asynccontextmanager
    async def fake_connect(**kwargs: Any) -> AsyncGenerator[_FakeConn]:
        probed.append(kwargs["host"])
        yield _FakeConn()

    inst_accessed = _inst(instance_id="i-accessed", private_ip="10.0.0.1")
    inst_new = _inst(instance_id="i-new", private_ip="10.0.0.2")
    data = Collected(instances=[inst_accessed, inst_new])

    existing_accessed = Instance(
        aws_account_id="111111111111",
        region="us-east-1",
        instance_id="i-accessed",
        instance_type="t3.micro",
        availability_zone="us-east-1a",
        image_id="ami-1",
        state="running",
        architecture="x86_64",
        launch_time=datetime(2026, 1, 1),
        ssh_status="succeeded",
        ssh_user="ec2-user",
        ssh_os_id="amzn",
        ssh_facts={"ssh_user": "ec2-user", "os_id": "amzn"},
    )
    rows_by_id: dict[str, Instance] = {"i-accessed": existing_accessed}

    monkeypatch.setattr(
        load,
        "get_accessed_ssh_instance_ids",
        lambda *_a: {"i-accessed"},
    )

    db = MagicMock()

    def fake_scalars(stmt: Any) -> SimpleNamespace:
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        matched = [obj for inst_id, obj in rows_by_id.items() if inst_id in sql]
        return SimpleNamespace(all=lambda: matched)

    db.scalars.side_effect = fake_scalars
    db.add.side_effect = lambda obj: rows_by_id.setdefault(obj.instance_id, obj)

    collector = ssh.SshCollector(
        users=("ubuntu",),
        only_unaccessed=True,
        connect_fn=fake_connect,
    )
    enrichments = runner._run_enrichers(db, "111111111111", "us-east-1", data, [collector])

    assert probed == ["10.0.0.2"]
    assert "ssh" not in enrichments["i-accessed"]
    assert enrichments["i-new"]["ssh"].status == "succeeded"

    counts = load.load_instances(db, "111111111111", "us-east-1", data, enrichments)
    assert counts.created == 1
    assert (existing_accessed.ssh_user, existing_accessed.ssh_os_id) == ("ec2-user", "amzn")
    assert existing_accessed.ssh_facts == {"ssh_user": "ec2-user", "os_id": "amzn"}
    assert (rows_by_id["i-new"].ssh_user, rows_by_id["i-new"].ssh_os_id) == ("ubuntu", "ubuntu")


def test_ssh_retries_last_known_user_first() -> None:
    attempts: list[tuple[str, str]] = []

    @asynccontextmanager
    async def fake_connect(**kwargs: Any) -> AsyncGenerator[_FakeConn]:
        host = kwargs["host"]
        user = kwargs["username"]
        attempts.append((host, user))
        if user != "debian":
            msg = "Permission denied"
            raise asyncssh.PermissionDenied(msg)
        yield _FakeConn()

    inst = _inst(instance_id="i-known", private_ip="10.0.0.10")
    data = Collected(instances=[inst])

    db = MagicMock()
    db.execute.side_effect = [
        SimpleNamespace(all=lambda: [("i-known", "debian")]),
        SimpleNamespace(all=list),
    ]

    collector = ssh.SshCollector(
        users=("ec2-user", "ubuntu", "debian"),
        connect_fn=fake_connect,
    )
    enrichments = runner._run_enrichers(db, "111111111111", "us-east-1", data, [collector])

    assert attempts == [("10.0.0.10", "debian")]
    res = enrichments["i-known"]["ssh"]
    assert res.status == "succeeded"
    assert res.facts is not None
    assert (res.facts["ssh_user"], res.facts["attempted_users"]) == ("debian", ["debian"])


def test_ssh_live_ami_learning_and_cached_keys(tmp_path: Path) -> None:
    attempts: list[tuple[str, str]] = []
    seen_kwargs: list[dict[str, Any]] = []

    @asynccontextmanager
    async def fake_connect(**kwargs: Any) -> AsyncGenerator[_FakeConn]:
        host = kwargs["host"]
        user = kwargs["username"]
        attempts.append((host, user))
        seen_kwargs.append(kwargs)
        if user != "centos":
            msg = "Permission denied"
            raise asyncssh.PermissionDenied(msg)
        yield _FakeConn()

    key_dir = tmp_path / "keys"
    key_dir.mkdir()
    pem = key_dir / "my-key.pem"
    pem.write_text("DUMMY_KEY")

    collector = ssh.SshCollector(
        users=("root", "admin", "ec2-user", "centos"),
        key_dir=key_dir,
        concurrency=1,
        connect_timeout=3.5,
        connect_fn=fake_connect,
    )

    instances = [
        _inst(instance_id="i-1", private_ip="10.0.0.1", image_id="ami-shared"),
        _inst(instance_id="i-2", private_ip="10.0.0.2", image_id="ami-shared"),
    ]
    results = collector.enrich_batch("111111111111", "us-east-1", instances)

    assert results["i-1"].facts is not None
    assert results["i-1"].facts["attempted_users"] == ["root", "admin", "ec2-user", "centos"]
    assert results["i-2"].facts is not None
    assert results["i-2"].facts["attempted_users"] == ["centos"]
    assert (seen_kwargs[0]["connect_timeout"], seen_kwargs[0]["login_timeout"]) == (3.5, 3.5)
    assert collector._load_key_cached(str(pem)) == str(pem)
    assert collector._load_key_cached(str(pem)) == str(pem)


def test_cli_daemon_env_and_max_cycles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EC2_SCRAPE_PROFILES", "prof-a,prof-b")
    monkeypatch.setenv("EC2_SCRAPE_REGIONS", "us-east-1")
    monkeypatch.setenv("EC2_SCRAPE_SSH", "true")
    monkeypatch.setenv("EC2_SCRAPE_INTERVAL", "0.01")

    monkeypatch.setattr(cli.db, "connect", lambda _dsn: MagicMock())
    calls: list[tuple[list[str], list[str] | None]] = []

    def fake_run(
        _conn: Any, profiles: list[str], regions: list[str] | None, *_a: Any, **_kw: Any
    ) -> runner.RunResult:
        calls.append((profiles, regions))
        return runner.RunResult(status="succeeded", combos=[])

    monkeypatch.setattr(cli.runner, "run", fake_run)
    rc = cli.main(["daemon", "--max-cycles", "2"])
    assert rc == 0
    assert calls == [(["prof-a", "prof-b"], ["us-east-1"]), (["prof-a", "prof-b"], ["us-east-1"])]

    monkeypatch.delenv("EC2_SCRAPE_PROFILES", raising=False)
    assert cli.main(["daemon", "--max-cycles", "1"]) == cli.EXIT_USAGE
    assert cli.main(["daemon", "--profile", "p", "--interval", "0"]) == cli.EXIT_USAGE
    assert (
        cli.main(["daemon", "--profile", "p", "--region", "us-east-1", "--all-regions"])
        == cli.EXIT_USAGE
    )
