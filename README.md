# EC2 Scraping

Collect an inventory of EC2 instances across AWS accounts/regions, enrich running Linux instances over SSH, and store everything in a single-table SQLite or MariaDB/MySQL schema for reporting and CSV export.

## Usage

### Scrape EC2 Inventory (`run`)

```bash
# Scrape a profile's default region (uses EC2_SCRAPE_DSN or sqlite:///ec2_inventory.db)
uv run ec2-scrape run --profile my-sso-profile

# Scrape multiple profiles across all enabled regions
uv run ec2-scrape run --profile acc-a --profile acc-b --all-regions

# Enable SSH telemetry collection (OS, kernel, uptime, packages, services, ports, containers)
uv run ec2-scrape run --profile my-sso-profile --ssh --ssh-key-dir ~/.ssh

# Only probe instances not yet accessed over SSH (preserves existing SSH data)
uv run ec2-scrape run --profile my-sso-profile --ssh-only-unaccessed --ssh-key-dir ~/.ssh
```

#### SSH Enrichment Options
- `--ssh`: Probe running Linux instances over SSH to gather OS/system telemetry.
- `--ssh-only-unaccessed`: Only probe instances without `ssh_status = 'succeeded'`, keeping previous SSH telemetry intact.
- `--ssh-user <user>`: Candidate SSH username (repeatable; defaults to `root`, `admin`, `ec2-user`, `centos`, plus distro hints).
- `--ssh-key <path>`: Explicit private key file path to offer (repeatable).
- `--ssh-key-dir <dir>`: Directory of private keys (prioritizes `<key_name>` or `<key_name>.pem` matching the instance's AWS key pair).
- `--ssh-port <port>`: SSH port (default: `22`).
- `--ssh-timeout <sec>`: TCP/SSH login timeout in seconds (default: `5.0`).
- `--ssh-concurrency <n>`: Maximum concurrent SSH instance probes (default: `32`).
- `--ssh-prefer-public-ip`: Connect via `public_ip` before `private_ip`.

When probing over SSH, candidate usernames are ordered per instance by:
1. Last known working `ssh_user` for that `instance_id` in the database
2. Known working `ssh_user` for the instance's `image_id` (from the database or learned live during the current batch)
3. Distro hint inferred from the AMI name / platform details (`ubuntu`, `debian`, `ec2-user`, `centos`, `fedora`, `rocky`, `almalinux`, `suse`, `bitnami`)
4. Remaining configured candidate users

### Summarize & Export (`summary` / `export`)

```bash
# Print an aggregated inventory summary (by state, region, type, OS, SSH status)
uv run ec2-scrape summary
uv run ec2-scrape summary --region us-east-1 --state running

# Export stored inventory to CSV (stdout or file)
uv run ec2-scrape export -o inventory.csv
```

## Development

```bash
uv sync                              # install deps
uv run pre-commit install            # hooks (commit + pre-push)
./scripts/map.sh                     # compact AST map (files, line ranges, typed signatures)
./scripts/check.sh --fix src/file.py # fast single-file gate + matching test
./scripts/check.sh --fix             # format/fix + run all 11 repo quality gates quietly
```

Individual checks:

```bash
uv run ruff check . && uv run ruff format .
uv run ty check
uv run deptry .                        # unused / missing / misplaced deps
uv run vulture                         # dead / unused code
uv run lint-imports                    # module import boundaries
uv run pylint                          # duplicate-code check (R0801)
uv run codeaudit cimode src            # SAST security scan
uv run xenon -b B -m A -a A src tests  # cyclomatic complexity gates
uv run radon mi -n B -s src tests      # maintainability index check (rank A required)
uv run pytest -q path::test_name       # fast single test (no coverage table)
uv run pytest --cov                    # full test suite + >=80% branch coverage
```

Pre-commit runs ruff + hygiene checks; pre-push and CI run `./scripts/check.sh`.

## Database Schema & Migrations

The single-table MariaDB/MySQL/SQLite schema is defined as a SQLAlchemy 2.0 ORM model in `src/ec2_scraping/db/models.py` with Alembic migrations in `src/ec2_scraping/db/migrations/` (see [`db/README.md`](db/README.md)).

```bash
# Apply migrations to a target database:
DATABASE_URL="mysql+pymysql://root:pw@127.0.0.1:3307/inv" uv run alembic upgrade head

# Run live DB schema tests against a disposable MariaDB instance:
MARIADB_TEST_DSN="mysql://root:pw@127.0.0.1:3307/inv" uv run pytest tests/schema -q
```

## Native Daemon & Systemd

`ec2-scrape daemon` runs continuous scrape cycles at a configurable interval and handles `SIGINT`/`SIGTERM` cleanly. All flags can also be configured via environment variables (see [`deploy/ec2-scraping.env.example`](deploy/ec2-scraping.env.example)).

| Environment Variable | Equivalent Flag | Default |
| --- | --- | --- |
| `EC2_SCRAPE_PROFILES` | `--profile` (comma-separated) | *(required in daemon mode)* |
| `EC2_SCRAPE_REGIONS` | `--region` (comma-separated) | profile default region |
| `EC2_SCRAPE_ALL_REGIONS` | `--all-regions` (`1`/`true`) | `false` |
| `EC2_SCRAPE_DSN` | `--dsn` | `sqlite:///ec2_inventory.db` |
| `EC2_SCRAPE_INTERVAL` | `--interval` (seconds) | `3600` |
| `EC2_SCRAPE_SSH` | `--ssh` (`1`/`true`) | `false` |
| `EC2_SCRAPE_SSH_ONLY_UNACCESSED` | `--ssh-only-unaccessed` (`1`/`true`) | `false` |
| `EC2_SCRAPE_SSH_KEY_DIR` | `--ssh-key-dir` | `None` |
| `EC2_SCRAPE_SSH_KEYS` | `--ssh-key` (comma-separated) | `None` |
| `EC2_SCRAPE_SSH_USERS` | `--ssh-user` (comma-separated) | `root,admin,ec2-user,centos` |
| `EC2_SCRAPE_SSH_PORT` | `--ssh-port` | `22` |
| `EC2_SCRAPE_SSH_TIMEOUT` | `--ssh-timeout` | `5.0` |
| `EC2_SCRAPE_SSH_CONCURRENCY` | `--ssh-concurrency` | `32` |
| `EC2_SCRAPE_SSH_PREFER_PUBLIC_IP` | `--ssh-prefer-public-ip` (`1`/`true`) | `false` |

```bash
# Run directly in the foreground (every 30 minutes)
uv run ec2-scrape daemon --profile my-sso-profile --all-regions --ssh --interval 1800

# Install as a systemd service:
sudo mkdir -p /etc/ec2-scraping /var/lib/ec2-scraping
sudo cp deploy/ec2-scraping.env.example /etc/ec2-scraping/ec2-scraping.env
sudo cp deploy/ec2-scrape.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ec2-scrape.service
sudo journalctl -u ec2-scrape.service -f
```

## Docker

The container image defaults to running `ec2-scrape daemon` and stores SQLite data in `/data/ec2_inventory.db` (or connects to MariaDB/MySQL via `EC2_SCRAPE_DSN`).

```bash
docker build -t ec2-scraping .

# Run as a background daemon container (mounting AWS config/SSO cache and SSH keys)
docker run -d --name ec2-scraper --restart unless-stopped \
  -e EC2_SCRAPE_PROFILES="my-sso-profile" \
  -e EC2_SCRAPE_ALL_REGIONS="1" \
  -e EC2_SCRAPE_SSH="1" \
  -e EC2_SCRAPE_SSH_KEY_DIR="/keys" \
  -e EC2_SCRAPE_INTERVAL="3600" \
  -v ~/.aws:/home/app/.aws:ro \
  -v ~/.ssh:/keys:ro \
  -v ec2_scrape_data:/data \
  ec2-scraping

# Or run a one-off summary / export against the volume:
docker run --rm -v ec2_scrape_data:/data ec2-scraping summary
docker run --rm -v ec2_scrape_data:/data ec2-scraping export
```
