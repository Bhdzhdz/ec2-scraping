"""`ec2-scrape` command line interface."""

import argparse
import sys
from pathlib import Path

from ec2_scraping import db, report, runner, session, ssh
from ec2_scraping.models import InstanceEnricher, RunResult

EXIT_OK, EXIT_PARTIAL, EXIT_FAILED, EXIT_USAGE = 0, 1, 2, 64
_EXIT = {"succeeded": EXIT_OK, "partial": EXIT_PARTIAL, "failed": EXIT_FAILED}


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # usage errors use exit code 64 per the contract
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


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="ec2-scrape", description="Inventory EC2 instances.")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    run_p = sub.add_parser("run", help="scrape profiles/regions into the database")
    run_p.add_argument("--profile", action="append", required=True, help="AWS SSO profile")
    run_p.add_argument("--region", action="append", help="region (repeatable)")
    run_p.add_argument("--all-regions", action="store_true", help="all enabled regions")
    run_p.add_argument(
        "--dsn",
        help=f"database DSN (default env {db.DSN_ENV}, falling back to {db.DEFAULT_SQLITE_DSN})",
    )
    run_p.add_argument(
        "--ssh",
        action="store_true",
        help="probe running instances over SSH using common usernames to collect OS/system facts",
    )
    run_p.add_argument(
        "--ssh-user",
        action="append",
        dest="ssh_users",
        help="candidate SSH username (repeatable; defaults to common Linux distro usernames)",
    )
    run_p.add_argument(
        "--ssh-key",
        action="append",
        dest="ssh_keys",
        help="private key file path to offer during SSH auth (repeatable)",
    )
    run_p.add_argument(
        "--ssh-key-dir",
        help="directory of private keys (matches <key_name> or <key_name>.pem first)",
    )
    run_p.add_argument("--ssh-port", type=int, default=22, help="SSH port (default: 22)")
    run_p.add_argument(
        "--ssh-timeout",
        type=float,
        default=5.0,
        help="SSH connection timeout in seconds (default: 5.0)",
    )
    run_p.add_argument(
        "--ssh-concurrency",
        type=int,
        default=32,
        help="maximum concurrent SSH instance probes (default: 32)",
    )
    run_p.add_argument(
        "--ssh-prefer-public-ip",
        action="store_true",
        help="connect to public_ip before private_ip when probing over SSH",
    )
    run_p.add_argument(
        "--ssh-only-unaccessed",
        action="store_true",
        help="only probe instances not yet accessed via SSH and keep previous SSH data",
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


def _build_enrichers(args) -> list[InstanceEnricher]:
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


def _cmd_run(args, open_session=session.open_session) -> int:
    if args.all_regions and args.region:
        print("ec2-scrape: error: --all-regions cannot be combined with --region", file=sys.stderr)
        return EXIT_USAGE
    enrichers = _build_enrichers(args)
    conn = db.connect(args.dsn)
    try:
        result = runner.run(
            conn,
            args.profile,
            args.region,
            args.all_regions,
            open_session=open_session,
            enrichers=enrichers,
        )
    finally:
        conn.close()
    print(format_summary(result))
    return _EXIT[result.status]


def _cmd_summary(args) -> int:
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
    print(report.format_inventory_summary(summary))
    return EXIT_OK


def _cmd_export(args) -> int:
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
        return _cmd_run(args)
    except (db.ConfigError, session.SsoLoginRequired) as exc:
        print(f"ec2-scrape: error: {exc}", file=sys.stderr)
        return EXIT_USAGE if isinstance(exc, db.ConfigError) else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
