"""Unit tests for the async SSH collector: user rotation, key resolution, and probe parsing."""

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import asyncssh
import pytest

from ec2_scraping import cli, load, runner, ssh
from ec2_scraping.db.models import Instance
from ec2_scraping.models import Collected, InstanceRecord

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


def _inst(**kw) -> InstanceRecord:
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


def test_parse_probe_output_extracts_all_sections():
    facts = ssh.parse_probe_output(SAMPLE_PROBE_OUTPUT, "ubuntu", "10.0.0.1", 22)
    assert facts["ssh_user"] == "ubuntu"
    assert facts["ssh_host"] == "10.0.0.1"
    assert facts["ssh_port"] == 22
    assert facts["os_id"] == "ubuntu"
    assert facts["os_version"] == "24.04"
    assert facts["os_pretty_name"] == "Ubuntu 24.04.1 LTS"
    assert facts["os_id_like"] == "debian"
    assert facts["kernel"] == "6.8.0-1015-aws"
    assert facts["architecture"] == "x86_64"
    assert facts["hostname"] == "ip-10-0-0-1.ec2.internal"
    assert facts["uptime_seconds"] == 86400
    assert facts["load_avg"] == [0.15, 0.1, 0.05]
    assert facts["cpu_model"] == "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz"
    assert facts["mem_total_mib"] == 7863
    assert facts["mem_available_mib"] == 6054
    assert facts["swap_total_mib"] == 0
    assert facts["root_disk"] == {
        "filesystem": "/dev/root",
        "total_mib": 20480,
        "used_mib": 5120,
        "avail_mib": 15360,
        "used_pct": 25,
    }
    assert facts["package_count"] == 642
    assert facts["running_services"] == ["cron.service", "ssh.service", "docker.service"]
    assert facts["listening_ports"] == [22, 53, 443]
    assert facts["listening_port_count"] == 3
    assert facts["containers"] == [
        {"name": "web", "image": "nginx:alpine"},
        {"name": "redis", "image": "redis:7"},
    ]
    assert facts["container_count"] == 2
    assert facts["reboot_required"] is True
    assert facts["passwordless_sudo"] is True
    assert facts["logged_in_users"] == ["ubuntu"]


@pytest.mark.parametrize(
    ("ami_name", "expected_first"),
    [
        ("ubuntu/images/hvm-ssd/ubuntu-noble-24.04", "ubuntu"),
        ("debian-12-amd64", "debian"),
        ("CentOS Stream 9", "centos"),
        ("Fedora-Cloud-Base", "fedora"),
        ("Rocky-9-EC2", "rocky"),
        ("AlmaLinux OS 9", "almalinux"),
        ("suse-sles-15", "suse"),
        ("bitnami-wordpress", "bitnami"),
        ("amzn2-ami-hvm", "ec2-user"),
    ],
)
def test_ordered_candidate_users_prioritizes_distro_hint(ami_name, expected_first):
    users = ssh.ordered_candidate_users(_inst(), ami_name=ami_name)
    assert users[0] == expected_first
    assert len(users) == len(ssh.DEFAULT_SSH_USERS)


def test_resolve_target_host_and_client_keys(tmp_path):
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


def test_ssh_collector_rotates_users_and_handles_states():
    attempts: list[tuple[str, str]] = []

    @asynccontextmanager
    async def fake_connect(**kwargs):
        host = kwargs["host"]
        user = kwargs["username"]
        attempts.append((host, user))
        if host == "10.0.0.99":
            raise TimeoutError("timed out")
        if user != "ubuntu":
            raise asyncssh.PermissionDenied("Permission denied")

        class Conn:
            async def run(self, script, check=False):
                return SimpleNamespace(stdout=SAMPLE_PROBE_OUTPUT)

        yield Conn()

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
        _inst(instance_id="i-timeout", private_ip="10.0.0.99"),
    ]
    results = collector.enrich_batch("111111111111", "us-east-1", instances)

    ok = results["i-ok"]
    assert ok.status == "succeeded"
    assert ok.facts is not None
    assert ok.facts["ssh_user"] == "ubuntu"
    assert ok.facts["attempted_users"] == ["ec2-user", "ubuntu"]
    assert results["i-stopped"].status == "skipped"
    assert results["i-win"].status == "skipped"
    assert results["i-noip"].status == "skipped"
    assert results["i-timeout"].status == "failed"
    assert ("10.0.0.99", "ec2-user") in attempts
    assert ("10.0.0.99", "ubuntu") not in attempts  # aborted after timeout


def test_ssh_collector_all_users_denied_and_single_enrich():
    @asynccontextmanager
    async def always_denied(**kwargs):
        raise asyncssh.PermissionDenied("denied")
        yield  # pragma: no cover

    collector = ssh.SshCollector(users=("ec2-user", "ubuntu"), connect_fn=always_denied)
    res = collector.enrich("111111111111", "us-east-1", _inst())
    assert res.status == "failed"
    assert "authentication failed" in (res.error or "")


def test_cli_build_enrichers():
    parser = cli.build_parser()
    args_off = parser.parse_args(["run", "--profile", "p"])
    assert cli._build_enrichers(args_off) == []

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
    assert isinstance(enrichers[0], ssh.SshCollector)
    assert enrichers[0].users == ("ubuntu",)
    assert enrichers[0].port == 2222
    assert enrichers[0].prefer_public_ip is True
    assert enrichers[0].only_unaccessed is False

    args_unaccessed = parser.parse_args(["run", "--profile", "p", "--ssh-only-unaccessed"])
    enrichers2 = cli._build_enrichers(args_unaccessed)
    assert len(enrichers2) == 1
    assert isinstance(enrichers2[0], ssh.SshCollector)
    assert enrichers2[0].only_unaccessed is True


def test_ssh_only_unaccessed_skips_succeeded_and_preserves_previous_data(monkeypatch):
    probed: list[str] = []

    @asynccontextmanager
    async def fake_connect(**kwargs):
        probed.append(kwargs["host"])

        class Conn:
            async def run(self, script, check=False):
                return SimpleNamespace(stdout=SAMPLE_PROBE_OUTPUT)

        yield Conn()

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
        lambda db, acc, reg, ids: {"i-accessed"},
    )

    db = MagicMock()

    def fake_scalars(stmt):
        # _load_instance queries by (aws_account_id, region, instance_id)
        for inst_id, obj in rows_by_id.items():
            if inst_id in str(stmt.compile(compile_kwargs={"literal_binds": True})):
                return SimpleNamespace(first=lambda obj=obj: obj)
        return SimpleNamespace(first=lambda: None)

    db.scalars.side_effect = fake_scalars
    db.add.side_effect = lambda obj: rows_by_id.setdefault(obj.instance_id, obj)

    collector = ssh.SshCollector(
        users=("ubuntu",),
        only_unaccessed=True,
        connect_fn=fake_connect,
    )
    enrichments = runner._run_enrichers(db, "111111111111", "us-east-1", data, [collector])

    # Only i-new was probed; i-accessed was skipped by the enricher
    assert probed == ["10.0.0.2"]
    assert "ssh" not in enrichments["i-accessed"]
    assert enrichments["i-new"]["ssh"].status == "succeeded"

    counts = load.load_instances(db, "111111111111", "us-east-1", data, enrichments)
    assert counts.created == 1
    assert existing_accessed.ssh_user == "ec2-user"
    assert existing_accessed.ssh_os_id == "amzn"
    assert existing_accessed.ssh_facts == {"ssh_user": "ec2-user", "os_id": "amzn"}
    assert rows_by_id["i-new"].ssh_user == "ubuntu"
    assert rows_by_id["i-new"].ssh_os_id == "ubuntu"
