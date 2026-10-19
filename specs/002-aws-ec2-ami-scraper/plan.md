# Implementation Plan: AWS EC2/AMI Scraper

**Branch**: `002-aws-ec2-ami-scraper` | **Date**: 2026-10-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-aws-ec2-ami-scraper/spec.md`

## Summary

A Python CLI authenticates with AWS SSO profiles via boto3, pages through read-only EC2 `Describe*` calls per profile/region, maps responses to the 001 SQLAlchemy 2.0 ORM schema, and upserts each combination in one transaction under a single `scrape_run`. One small schema addition (Alembic migration `0002_scrape_scope_status`) records per-combination status so partial runs and missing-resource queries are accurate.

## Technical Context

**Language/Version**: Python 3.12+ (uv)

**Primary Dependencies**: `boto3`, `sqlalchemy>=2.0`, `alembic>=1.13`, `pymysql` (all in `[project].dependencies`); stdlib `argparse`, `logging`

**Storage**: MariaDB only, schema from 001 ORM + Alembic migration `0002_scrape_scope_status`

**Testing**: pytest; unit tests with botocore `Stubber`; integration tests against the real MariaDB (existing `tests/schema` fixtures)

**Target Platform**: Linux CLI, schedulable (cron/CI)

**Project Type**: CLI

**Performance Goals**: 5,000 instances across regions in <10 min (SC-005)

**Constraints**: sequential execution (no concurrency); read-only AWS calls; no long-lived keys; non-interactive; DB DSN from env (`MARIADB_DSN`)

**Scale/Scope**: tens of accounts, tens of regions, thousands of instances

## Constitution Check

| Principle | Status |
|---|---|
| I. Read-Only AWS Access | Pass: only `Describe*`/`sts:GetCallerIdentity`; test asserts no non-describe calls |
| II. Normalized, Idempotent Persistence | Pass: upserts on 001 unique keys via SQLAlchemy 2.0 ORM/Core; 0002 migration re-runnable (MariaDB-only syntax allowed by constitution 1.0.1), 3NF (status depends on the scope key) |
| III. Test-First | Pass: Stubber unit tests + real-DB integration tests |
| IV. Simplicity | Pass: sequential, reuses existing ORM/Alembic stack, one migration |
| V. Spec-Driven | Pass |

Post-design re-check: Pass (no violations).

## Project Structure

### Documentation (this feature)

```text
specs/002-aws-ec2-ami-scraper/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/cli.md
└── tasks.md             # created by $speckit-tasks
```

### Source Code (repository root)

```text
src/ec2_scraping/
├── db/
│   ├── models.py       # SQLAlchemy 2.0 ORM models (including ScrapeRunScope.status/error)
│   ├── session.py      # engine/session factory, connect(), DSN helpers, upgrade_db()
│   └── migrations/versions/0002_scrape_scope_status.py
├── cli.py              # argparse entrypoint, exit codes
├── session.py          # SSO profile session, validity check, account id
├── collect.py          # paginated describe calls -> plain dataclasses
├── models.py           # dataclasses for collected instances/AMIs
├── load.py             # transactional ORM upserts into 001 schema
├── runner.py           # scrape_run lifecycle, per-combination isolation
└── missing.py          # missing-resources ORM query
tests/
├── unit/               # session, collect (Stubber), mapping
└── integration/        # load + runner + missing against MariaDB
```

**Structure Decision**: Single project; `[project.scripts] ec2-scrape = ec2_scraping.cli:main`.

## Complexity Tracking

No violations.
