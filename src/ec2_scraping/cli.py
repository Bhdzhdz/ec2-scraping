"""`ec2-scrape` command line interface."""

import argparse
import sys

from ec2_scraping import db, missing, runner, session
from ec2_scraping.models import RunResult

EXIT_OK, EXIT_PARTIAL, EXIT_FAILED, EXIT_USAGE = 0, 1, 2, 64
_EXIT = {"succeeded": EXIT_OK, "partial": EXIT_PARTIAL, "failed": EXIT_FAILED}


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # usage errors use exit code 64 per the contract
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="ec2-scrape", description="Inventory EC2 instances and AMIs.")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    run_p = sub.add_parser("run", help="scrape profiles/regions into the database")
    run_p.add_argument("--profile", action="append", required=True, help="AWS SSO profile")
    run_p.add_argument("--region", action="append", help="region (repeatable)")
    run_p.add_argument("--all-regions", action="store_true", help="all enabled regions")
    run_p.add_argument("--dsn", help=f"database DSN (default env {db.DSN_ENV})")

    miss_p = sub.add_parser("missing", help="list resources not seen in the latest run")
    miss_p.add_argument("--profile", action="append", help="AWS SSO profile (repeatable)")
    miss_p.add_argument("--region", action="append", help="region (repeatable)")
    miss_p.add_argument("--dsn", help=f"database DSN (default env {db.DSN_ENV})")
    return parser


def format_summary(result: RunResult) -> str:
    lines = [f"Scrape run {result.run_id}: {result.status}"]
    for c in result.combos:
        where = f"{c.profile}/{c.region}" if c.region else c.profile
        if c.status == "succeeded":
            lines.append(
                f"  {where}: instances +{c.instances.created} ~{c.instances.updated} "
                f"={c.instances.unchanged}; amis +{c.amis.created} ~{c.amis.updated} "
                f"={c.amis.unchanged}"
            )
    failures = [c for c in result.combos if c.status != "succeeded"]
    if failures:
        lines.append("Failures:")
        for c in failures:
            where = f"{c.profile}/{c.region}" if c.region else c.profile
            lines.append(f"  {where} [{c.status}]: {c.error}")
    return "\n".join(lines)


def _cmd_run(args, open_session=session.open_session) -> int:
    if args.all_regions and args.region:
        print("ec2-scrape: error: --all-regions cannot be combined with --region", file=sys.stderr)
        return EXIT_USAGE
    conn = db.connect(args.dsn)
    try:
        result = runner.run(
            conn, args.profile, args.region, args.all_regions, open_session=open_session
        )
    finally:
        conn.close()
    print(format_summary(result))
    return _EXIT[result.status]


def _cmd_missing(args, open_session=session.open_session) -> int:
    account_ids = [open_session(p).account_id for p in args.profile or []]
    conn = db.connect(args.dsn)
    try:
        rows = missing.find_missing(conn, account_ids or None, args.region)
    finally:
        conn.close()
    for r in rows:
        print(
            f"{r['kind']}\t{r['aws_account_id']}\t{r['region']}\t{r['resource_id']}\t{r['last_seen_at']}"
        )
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _cmd_run(args) if args.command == "run" else _cmd_missing(args)
    except (db.ConfigError, session.SsoLoginRequired) as exc:
        print(f"ec2-scrape: error: {exc}", file=sys.stderr)
        return EXIT_USAGE if isinstance(exc, db.ConfigError) else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
