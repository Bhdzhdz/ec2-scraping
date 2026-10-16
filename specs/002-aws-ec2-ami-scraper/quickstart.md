# Quickstart: Validate the Scraper

## Prerequisites
- `uv sync`; MariaDB test DB per [001 quickstart](../001-ec2-ami-inventory-ddl/quickstart.md), migrations 0001–0006 applied.
- `export MARIADB_TEST_DSN=...`
- For live check: `aws sso login --profile <name>` (read-only EC2 permissions).

## Automated
- `uv run pytest -q -x --tb=short` (Stubber unit tests + DB integration tests; no AWS needed).

## Live
1. `uv run ec2-scrape run --profile <name> --region us-east-1 --dsn "$MARIADB_TEST_DSN"` → exit 0, summary counts.
2. Re-run → zero duplicates, all unchanged, `last_seen_at` advanced (SC-002).
3. Log out (`aws sso logout`), re-run → names the profile, exit 2, no data changed (SC-004).
4. Two profiles, one logged out → exit 1, other stored (SC-003).
5. `uv run ec2-scrape missing --profile <name> --region us-east-1` after terminating an instance and re-scraping (SC-006).

Interface details: [contracts/cli.md](contracts/cli.md). Schema delta: [data-model.md](data-model.md).
