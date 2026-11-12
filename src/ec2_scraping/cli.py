"""`ec2-scrape` command line interface."""

import argparse
import os
import signal
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, override

from ec2_scraping import db, report, runner, session, ssh

if TYPE_CHECKING:
    from collections.abc import Callable

    from ec2_scraping.models import InstanceEnricher, RunResult

EXIT_OK, EXIT_PARTIAL, EXIT_FAILED, EXIT_USAGE = 0, 1, 2, 64
_EXIT = {"succeeded": EXIT_OK, "partial": EXIT_PARTIAL, "failed": EXIT_FAILED}


def _emit(msg: str, *, err: bool = False, flush: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    stream.write(f"{msg}\n")
    if flush:
        stream.flush()


def _env_list(name: str) -> list[str] | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


class _Parser(argparse.ArgumentParser):
    @override
    def error(self, message: str) -> NoReturn:  # usage errors use exit code 64 per the contract
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def _add_filter_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--dsn",
        help=f"database DSN (default env {db.DSN_ENV}, falling back to {db.DEFAULT_SQLITE_DSN})",
    )
    p.add_argument("--region", action="append", help="filter by region (repeatable)")
    p.add_argument("--account", action="append", help="filter by AWS account ID (repeatable)")
    p.add_argument("--state", action="append", help="filter by instance state (repeatable)")


def _add_ssh_args(p: argparse.ArgumentParser, *, use_env: bool) -> None:
    p.add_argument(
        "--ssh",
        action="store_true",
        default=_env_bool("EC2_SCRAPE_SSH") if use_env else False,
        help="probe running instances over SSH using common usernames to collect OS/system facts",
    )
    p.add_argument(
        "--ssh-user",
        action="append",
        dest="ssh_users",
        default=_env_list("EC2_SCRAPE_SSH_USERS") if use_env else None,
        help="candidate SSH username (repeatable; defaults to common Linux distro usernames)",
    )
    p.add_argument(
        "--ssh-key",
        action="append",
        dest="ssh_keys",
        default=_env_list("EC2_SCRAPE_SSH_KEYS") if use_env else None,
        help="private key file path to offer during SSH auth (repeatable)",
    )
    p.add_argument(
        "--ssh-key-dir",
        default=os.environ.get("EC2_SCRAPE_SSH_KEY_DIR") if use_env else None,
        help="directory of private keys (matches <key_name> or <key_name>.pem first)",
    )
    p.add_argument(
        "--ssh-port",
        type=int,
        default=_env_int("EC2_SCRAPE_SSH_PORT", 22) if use_env else 22,
        help="SSH port (default: 22)",
    )
    p.add_argument(
        "--ssh-timeout",
        type=float,
        default=_env_float("EC2_SCRAPE_SSH_TIMEOUT", 5.0) if use_env else 5.0,
        help="SSH connection timeout in seconds (default: 5.0)",
    )
    p.add_argument(
        "--ssh-concurrency",
        type=int,
        default=_env_int("EC2_SCRAPE_SSH_CONCURRENCY", 32) if use_env else 32,
        help="maximum concurrent SSH instance probes (default: 32)",
    )
    p.add_argument(
        "--ssh-prefer-public-ip",
        action="store_true",
        default=_env_bool("EC2_SCRAPE_SSH_PREFER_PUBLIC_IP") if use_env else False,
        help="connect to public_ip before private_ip when probing over SSH",
    )
    p.add_argument(
        "--ssh-only-unaccessed",
        action="store_true",
        default=_env_bool("EC2_SCRAPE_SSH_ONLY_UNACCESSED") if use_env else False,
        help="only probe instances not yet accessed via SSH and keep previous SSH data",
    )


def _add_scrape_args(p: argparse.ArgumentParser, *, profile_required: bool = True) -> None:
    use_env = not profile_required
    env_profiles = _env_list("EC2_SCRAPE_PROFILES") if use_env else None
    p.add_argument(
        "--profile",
        action="append",
        required=profile_required and not env_profiles,
        default=env_profiles,
        help="AWS SSO profile (repeatable; or env EC2_SCRAPE_PROFILES=p1,p2 in daemon mode)",
    )
    p.add_argument(
        "--region",
        action="append",
        default=_env_list("EC2_SCRAPE_REGIONS") if use_env else None,
        help="region (repeatable; or env EC2_SCRAPE_REGIONS=r1,r2 in daemon mode)",
    )
    p.add_argument(
        "--all-regions",
        action="store_true",
        default=_env_bool("EC2_SCRAPE_ALL_REGIONS") if use_env else False,
        help="all enabled regions (or env EC2_SCRAPE_ALL_REGIONS=1 in daemon mode)",
    )
    p.add_argument(
        "--dsn",
        help=f"database DSN (default env {db.DSN_ENV}, falling back to {db.DEFAULT_SQLITE_DSN})",
    )
    _add_ssh_args(p, use_env=use_env)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="ec2-scrape", description="Inventory EC2 instances.")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    run_p = sub.add_parser("run", help="scrape profiles/regions into the database")
    _add_scrape_args(run_p, profile_required=True)

    daemon_p = sub.add_parser("daemon", help="run continuous periodic scrape cycles as a daemon")
    _add_scrape_args(daemon_p, profile_required=False)
    daemon_p.add_argument(
        "--interval",
        type=float,
        default=_env_float("EC2_SCRAPE_INTERVAL", 3600.0),
        help="seconds between scrape cycles (default: 3600 or env EC2_SCRAPE_INTERVAL)",
    )
    daemon_p.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="stop after N cycles (default: run indefinitely until SIGINT/SIGTERM)",
    )

    summary_p = sub.add_parser("summary", help="print a summary of the stored EC2 inventory")
    _add_filter_args(summary_p)

    export_p = sub.add_parser("export", help="export the stored EC2 inventory to CSV")
    _add_filter_args(export_p)
    export_p.add_argument(
        "-o",
        "--output",
        help="output CSV file path (defaults to stdout; '-' writes to stdout)",
    )
    return parser


def format_summary(result: RunResult) -> str:
    lines = [f"Scrape run: {result.status}"]
    for c in result.combos:
        where = f"{c.profile}/{c.region}" if c.region else c.profile
        if c.status == "succeeded":
            lines.append(
                f"  {where}: instances +{c.instances.created} ~{c.instances.updated} "
                f"={c.instances.unchanged}"
            )
    failures = [c for c in result.combos if c.status != "succeeded"]
    if failures:
        lines.append("Failures:")
        for c in failures:
            where = f"{c.profile}/{c.region}" if c.region else c.profile
            lines.append(f"  {where} [{c.status}]: {c.error}")
    return "\n".join(lines)


def _build_enrichers(args: argparse.Namespace) -> list[InstanceEnricher]:
    if not (getattr(args, "ssh", False) or getattr(args, "ssh_only_unaccessed", False)):
        return []
    return [
        ssh.SshCollector(
            users=args.ssh_users or ssh.DEFAULT_SSH_USERS,
            key_files=args.ssh_keys or (),
            key_dir=args.ssh_key_dir,
            port=args.ssh_port,
            connect_timeout=args.ssh_timeout,
            concurrency=args.ssh_concurrency,
            prefer_public_ip=args.ssh_prefer_public_ip,
            only_unaccessed=getattr(args, "ssh_only_unaccessed", False),
        )
    ]


def _run_once(
    args: argparse.Namespace,
    open_session: Callable[[str], session.ProfileSession],
    enrichers: list[InstanceEnricher],
) -> RunResult:
    conn = db.connect(args.dsn)
    try:
        return runner.run(
            conn,
            args.profile,
            args.region,
            args.all_regions,
            open_session=open_session,
            enrichers=enrichers,
        )
    finally:
        conn.close()


def _cmd_run(
    args: argparse.Namespace,
    open_session: Callable[[str], session.ProfileSession] = session.open_session,
) -> int:
    if args.all_regions and args.region:
        _emit("ec2-scrape: error: --all-regions cannot be combined with --region", err=True)
        return EXIT_USAGE
    result = _run_once(args, open_session, _build_enrichers(args))
    _emit(format_summary(result))
    return _EXIT[result.status]


def _validate_daemon_args(args: argparse.Namespace) -> bool:
    if not args.profile:
        _emit("ec2-scrape: error: daemon requires --profile or EC2_SCRAPE_PROFILES", err=True)
        return False
    if args.all_regions and args.region:
        _emit("ec2-scrape: error: --all-regions cannot be combined with --region", err=True)
        return False
    if args.interval <= 0:
        _emit("ec2-scrape: error: --interval must be > 0", err=True)
        return False
    return True


def _run_daemon_cycle(
    cycle: int,
    args: argparse.Namespace,
    open_session: Callable[[str], session.ProfileSession],
    enrichers: list[InstanceEnricher],
) -> int:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _emit(f"[{ts}] Starting scrape cycle #{cycle}...", flush=True)
    try:
        result = _run_once(args, open_session, enrichers)
        _emit(format_summary(result), flush=True)
        return _EXIT[result.status]
    except Exception as exc:
        _emit(f"[{ts}] Scrape cycle #{cycle} error: {exc}", err=True, flush=True)
        return EXIT_FAILED


def _cmd_daemon(
    args: argparse.Namespace,
    open_session: Callable[[str], session.ProfileSession] = session.open_session,
    stop_event: threading.Event | None = None,
) -> int:
    if not _validate_daemon_args(args):
        return EXIT_USAGE

    stop = stop_event if stop_event is not None else threading.Event()
    if stop_event is None and threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda _s, _f: stop.set())

    enrichers = _build_enrichers(args)
    cycle = 0
    last_code = EXIT_OK
    while not stop.is_set():
        cycle += 1
        last_code = _run_daemon_cycle(cycle, args, open_session, enrichers)
        if args.max_cycles is not None and cycle >= args.max_cycles:
            break
        if stop.wait(args.interval):
            break

    _emit("Daemon stopped.", flush=True)
    return last_code


def _cmd_summary(args: argparse.Namespace) -> int:
    conn = db.connect(args.dsn)
    try:
        summary = report.summarize_instances(
            conn,
            regions=args.region,
            accounts=args.account,
            states=args.state,
        )
    finally:
        conn.close()
    _emit(report.format_inventory_summary(summary))
    return EXIT_OK


def _cmd_export(args: argparse.Namespace) -> int:
    conn = db.connect(args.dsn)
    try:
        if args.output and args.output != "-":
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="") as fh:
                report.export_instances_csv(
                    conn,
                    fh,
                    regions=args.region,
                    accounts=args.account,
                    states=args.state,
                )
        else:
            report.export_instances_csv(
                conn,
                sys.stdout,
                regions=args.region,
                accounts=args.account,
                states=args.state,
            )
    finally:
        conn.close()
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "summary":
            return _cmd_summary(args)
        if args.command == "export":
            return _cmd_export(args)
        if args.command == "daemon":
            return _cmd_daemon(args)
        return _cmd_run(args)
    except (db.ConfigError, session.SsoLoginRequired) as exc:
        _emit(f"ec2-scrape: error: {exc}", err=True)
        return EXIT_USAGE if isinstance(exc, db.ConfigError) else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
