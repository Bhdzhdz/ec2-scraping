"""Async SSH collector: probes common usernames and gathers OS/system facts.

Provides :class:`SshCollector` and helper functions (:func:`resolve_target_host`,
:func:`resolve_client_keys`, :func:`ordered_candidate_users`) for discovering
target endpoints, private keys, and candidate SSH logins across EC2 instances.
"""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Unpack

import asyncssh

from ec2_scraping.models import EnrichmentResult
from ec2_scraping.ssh_probe import PROBE_SCRIPT, parse_probe_output

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from ec2_scraping.models import InstanceRecord, SshCollectorOptions

type ClientKey = asyncssh.SSHKey | str


__all__ = [
    "DEFAULT_KEY_NAMES",
    "DEFAULT_SSH_USERS",
    "PROBE_SCRIPT",
    "SshCollector",
    "ordered_candidate_users",
    "parse_probe_output",
    "resolve_client_keys",
    "resolve_target_host",
]

DEFAULT_SSH_USERS: tuple[str, ...] = (
    "root",
    "admin",
    "ec2-user",
    "centos",
)

DEFAULT_KEY_NAMES: tuple[str, ...] = (
    "id_ed25519",
    "id_ecdsa",
    "id_rsa",
    "id_dsa",
)

_DISTRO_USER_HINTS: tuple[tuple[str, str], ...] = (
    ("ubuntu", "ubuntu"),
    ("debian", "debian"),
    ("centos", "centos"),
    ("fedora", "fedora"),
    ("rocky", "rocky"),
    ("alma", "almalinux"),
    ("suse", "suse"),
    ("sles", "suse"),
    ("bitnami", "bitnami"),
    ("amzn", "ec2-user"),
    ("amazon", "ec2-user"),
    ("rhel", "ec2-user"),
)


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


def _iter_key_dir(key_dir: str | Path) -> list[Path]:
    """Return sorted non-public-key files in ``key_dir``."""
    base = Path(key_dir).expanduser()
    if not base.is_dir():
        return []
    return [c for c in sorted(base.iterdir()) if c.is_file() and not c.name.endswith(".pub")]


def _candidate_key_paths(
    inst: InstanceRecord,
    key_files: Sequence[str | Path],
    key_dir: str | Path | None,
    ssh_dir: Path,
    dir_files: Iterable[str | Path] | None = None,
) -> list[Path]:
    """Build candidate private key paths in priority order."""
    candidates: list[Path] = []
    if key_dir and inst.key_name:
        base = Path(key_dir).expanduser()
        candidates.extend((base / inst.key_name, base / f"{inst.key_name}.pem"))
    candidates.extend(Path(kf) for kf in key_files)
    if key_dir:
        extra = (Path(p) for p in dir_files) if dir_files is not None else _iter_key_dir(key_dir)
        candidates.extend(extra)
    candidates.extend(ssh_dir / name for name in DEFAULT_KEY_NAMES)
    return candidates


def resolve_client_keys(
    inst: InstanceRecord,
    key_files: Sequence[str | Path] = (),
    key_dir: str | Path | None = None,
    default_ssh_dir: Path | None = None,
) -> list[str]:
    """Build ordered list of existing private key paths to offer for ``inst``."""
    ssh_dir = default_ssh_dir if default_ssh_dir is not None else Path.home() / ".ssh"
    found: list[str] = []
    seen: set[str] = set()
    for p in _candidate_key_paths(inst, key_files, key_dir, ssh_dir):
        exp = p.expanduser()
        resolved = str(exp)
        if resolved not in seen and exp.is_file():
            seen.add(resolved)
            found.append(resolved)
    return found


def _hinted_user(hint: str) -> str | None:
    """Match the first distro token in ``hint`` to its default SSH username."""
    for token, username in _DISTRO_USER_HINTS:
        if token in hint:
            return username
    return None


def _dedup_nonempty(items: Iterable[str | None]) -> list[str]:
    """Deduplicate non-empty strings while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def ordered_candidate_users(
    inst: InstanceRecord,
    users: Sequence[str] = DEFAULT_SSH_USERS,
    ami_name: str | None = None,
    last_known_user: str | None = None,
    ami_known_user: str | None = None,
) -> list[str]:
    """Order candidate usernames, prioritizing known users and likely OS matches."""
    hint = f"{ami_name or ''} {inst.platform_details or ''}".lower()
    distro_user = _hinted_user(hint)
    allow_any_hint = tuple(users) == DEFAULT_SSH_USERS
    valid_hint = distro_user if distro_user and (allow_any_hint or distro_user in users) else None
    return _dedup_nonempty((last_known_user, ami_known_user, valid_hint, *users))


class SshCollector:
    """Async SSH enricher that tries candidate usernames and gathers OS/system telemetry."""

    name = "ssh"

    def __init__(self, **opts: Unpack[SshCollectorOptions]) -> None:
        """Initialize SSH collector configuration and internal key caches."""
        self.users = tuple(opts.get("users") or DEFAULT_SSH_USERS)
        self.key_files = tuple(opts.get("key_files") or ())
        self.key_dir: str | Path | None = opts.get("key_dir")
        self.port: int = opts.get("port", 22)
        self.connect_timeout: float = opts.get("connect_timeout", 5.0)
        self.command_timeout: float = opts.get("command_timeout", 15.0)
        self.concurrency: int = max(1, opts.get("concurrency", 32))
        self.prefer_public_ip: bool = bool(opts.get("prefer_public_ip", False))
        self.only_unaccessed: bool = bool(opts.get("only_unaccessed", False))
        self.connect_fn: Callable[..., Any] = opts.get("connect_fn", asyncssh.connect)
        self._file_exists_cache: dict[str, bool] = {}
        self._dir_files_cache: dict[str, list[str]] = {}
        self._parsed_key_cache: dict[str, ClientKey] = {}

    def _is_file_cached(self, p: Path) -> tuple[str, bool]:
        """Return expanded path string and cached existence status."""
        exp = p.expanduser()
        resolved = str(exp)
        if resolved not in self._file_exists_cache:
            self._file_exists_cache[resolved] = exp.is_file()
        return resolved, self._file_exists_cache[resolved]

    def _dir_keys_cached(self, key_dir: str | Path) -> list[str]:
        """List and cache private key files in ``key_dir``."""
        key = str(Path(key_dir).expanduser())
        if key not in self._dir_files_cache:
            files = [str(c) for c in _iter_key_dir(key_dir)]
            for f in files:
                self._file_exists_cache[f] = True
            self._dir_files_cache[key] = files
        return self._dir_files_cache[key]

    def _load_key_cached(self, path: str) -> ClientKey:
        """Load and cache an asyncssh private key object, falling back to the path."""
        if path not in self._parsed_key_cache:
            try:
                self._parsed_key_cache[path] = asyncssh.read_private_key(path)
            except asyncssh.KeyImportError, OSError:
                self._parsed_key_cache[path] = path
        return self._parsed_key_cache[path]

    def _resolve_cached_client_keys(self, inst: InstanceRecord) -> Sequence[ClientKey]:
        """Resolve and cache client keys for ``inst``."""
        dir_files = self._dir_keys_cached(self.key_dir) if self.key_dir else None
        candidates = _candidate_key_paths(
            inst, self.key_files, self.key_dir, Path.home() / ".ssh", dir_files
        )
        found: list[str] = []
        seen: set[str] = set()
        for p in candidates:
            resolved, exists = self._is_file_cached(p)
            if exists and resolved not in seen:
                seen.add(resolved)
                found.append(resolved)
        if self.connect_fn is asyncssh.connect:
            return [self._load_key_cached(p) for p in found]
        return found

    def _check_skippable(self, inst: InstanceRecord) -> tuple[str | None, EnrichmentResult | None]:
        """Check if ``inst`` should be skipped before attempting SSH connection."""
        if inst.state != "running":
            return None, EnrichmentResult(status="skipped", error=f"instance state is {inst.state}")
        if (inst.platform or "").lower() == "windows":
            return None, EnrichmentResult(status="skipped", error="windows platform skipped")
        host = resolve_target_host(inst, prefer_public_ip=self.prefer_public_ip)
        if not host:
            return None, EnrichmentResult(status="skipped", error="no reachable IP or DNS name")
        return host, None

    def _connect_kwargs(
        self, host: str, user: str, client_keys: Sequence[ClientKey]
    ) -> dict[str, Any]:
        """Build connection keyword arguments for asyncssh."""
        kwargs: dict[str, Any] = {
            "host": host,
            "port": self.port,
            "username": user,
            "known_hosts": None,
            "preferred_auth": "publickey",
            "connect_timeout": self.connect_timeout,
            "login_timeout": self.connect_timeout,
        }
        if client_keys:
            kwargs["client_keys"] = client_keys
        return kwargs

    async def _attempt_user(
        self,
        host: str,
        user: str,
        client_keys: Sequence[ClientKey],
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Try connecting and running the probe script as ``user``."""
        try:
            async with self.connect_fn(**self._connect_kwargs(host, user, client_keys)) as conn:
                res = await asyncio.wait_for(
                    conn.run(PROBE_SCRIPT, check=False), timeout=self.command_timeout
                )
                return parse_probe_output(str(res.stdout or ""), user, host, self.port), None
        except asyncssh.PermissionDenied:
            return None, None
        except (TimeoutError, OSError, asyncssh.DisconnectError, asyncssh.Error) as exc:
            if isinstance(exc, asyncssh.Error) and "auth" in str(exc).lower():
                return None, None
            return None, f"{host}:{self.port} ({user}): {type(exc).__name__}: {exc}"

    async def _probe_candidates(
        self,
        host: str,
        candidates: list[str],
        client_keys: Sequence[ClientKey],
        on_success: Callable[[str], None] | None = None,
    ) -> EnrichmentResult:
        """Iterate through candidate usernames until one succeeds or a fatal error occurs."""
        for idx, user in enumerate(candidates):
            facts, fatal_err = await self._attempt_user(host, user, client_keys)
            if facts is not None:
                facts["attempted_users"] = candidates[: idx + 1]
                if on_success:
                    on_success(user)
                return EnrichmentResult(status="succeeded", facts=facts)
            if fatal_err is not None:
                return EnrichmentResult(status="failed", error=fatal_err)
        err = f"authentication failed for users {list(candidates)} on {host}:{self.port}"
        return EnrichmentResult(status="failed", error=err)

    async def _probe_instance(
        self,
        inst: InstanceRecord,
        ami_name: str | None = None,
        last_known_user: str | None = None,
        ami_known_user: str | None = None,
        learned_ami_users: dict[str, str] | None = None,
    ) -> EnrichmentResult:
        """Probe a single EC2 instance over SSH."""
        host, skip_res = self._check_skippable(inst)
        if skip_res is not None or host is None:
            return skip_res or EnrichmentResult(
                status="skipped", error="no reachable IP or DNS name"
            )

        effective_ami_user = ami_known_user or (
            learned_ami_users.get(inst.image_id) if learned_ami_users else None
        )
        client_keys = self._resolve_cached_client_keys(inst)
        candidates = ordered_candidate_users(
            inst,
            self.users,
            ami_name,
            last_known_user=last_known_user,
            ami_known_user=effective_ami_user,
        )

        def _remember(user: str) -> None:
            if learned_ami_users is not None and inst.image_id:
                learned_ami_users.setdefault(inst.image_id, user)

        return await self._probe_candidates(host, candidates, client_keys, _remember)

    async def enrich_many_async(
        self,
        _aws_account_id: str,
        _region: str,
        instances: Sequence[InstanceRecord],
        ami_names: dict[str, str | None] | None = None,
        **user_hints: dict[str, str] | None,
    ) -> dict[str, EnrichmentResult]:
        """Concurrently enrich a batch of instances via SSH."""
        sem = asyncio.Semaphore(self.concurrency)
        ami_names = ami_names or {}
        known_users = user_hints.get("known_users") or {}
        learned_ami_users: dict[str, str] = dict(user_hints.get("known_ami_users") or {})

        async def _guarded(inst: InstanceRecord) -> tuple[str, EnrichmentResult]:
            _, skip_res = self._check_skippable(inst)
            if skip_res is not None:
                return inst.instance_id, skip_res
            async with sem:
                res = await self._probe_instance(
                    inst,
                    ami_names.get(inst.image_id),
                    last_known_user=known_users.get(inst.instance_id),
                    learned_ami_users=learned_ami_users,
                )
                return inst.instance_id, res

        pairs = await asyncio.gather(*(_guarded(i) for i in instances))
        return dict(pairs)

    def enrich_batch(
        self,
        aws_account_id: str,
        region: str,
        instances: Sequence[InstanceRecord],
        ami_names: dict[str, str | None] | None = None,
        **user_hints: dict[str, str] | None,
    ) -> dict[str, EnrichmentResult]:
        """Synchronously enrich a batch of instances via SSH."""
        return asyncio.run(
            self.enrich_many_async(aws_account_id, region, instances, ami_names, **user_hints)
        )

    def enrich(
        self,
        aws_account_id: str,
        region: str,
        instance: InstanceRecord,
        last_known_user: str | None = None,
    ) -> EnrichmentResult:
        """Synchronously enrich a single instance via SSH."""
        del aws_account_id, region
        return asyncio.run(self._probe_instance(instance, last_known_user=last_known_user))
