# Implementation Plan: EC2 and AMI Inventory Schema (Initial DDL)

**Branch**: `001-ec2-ami-inventory-ddl` | **Date**: 2026-10-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-ec2-ami-inventory-ddl/spec.md`

## Summary

Deliver a 3NF MySQL/MariaDB schema as SQLAlchemy 2.0 Declarative ORM models and Alembic migrations for EC2 instance and AMI inventory, with reference tables, tag tables, attachments, and scrape-run tracking. Verified by pytest against both SQLAlchemy metadata/Alembic and a throwaway MariaDB container.

## Technical Context

**Language/Version**: Python 3.12; SQL target MariaDB 10.6+ / MySQL 8.0+ (InnoDB, utf8mb4)

**Primary Dependencies**: `sqlalchemy>=2.0`, `alembic>=1.13`, `pymysql>=1.1`

**Storage**: MariaDB/MySQL, InnoDB, utf8mb4

**Testing**: pytest; schema applied via Alembic (`alembic upgrade head`) to a disposable MariaDB container (`MARIADB_TEST_DSN` env var, live DB tests skipped if unset) plus unit tests on ORM metadata & migrations

**Target Platform**: Linux server / container

**Project Type**: schema/ORM library

**Performance Goals**: AMI-to-instances and tag key/value lookups under 2 s on 100k instances (SC-004)

**Constraints**: idempotent (`alembic upgrade head` re-runnable), no destructive statements in upgrade, 3NF

**Scale/Scope**: ~100k instances, ~10k AMIs, multiple accounts/regions

## Constitution Check

The constitution at `.specify/memory/constitution.md` is still the unfilled template, so no gates are defined. Result: PASS (no applicable constraints). Re-check after the constitution is ratified.

## Project Structure

### Documentation (this feature)

```text
specs/001-ec2-ami-inventory-ddl/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
└── tasks.md             # created by $speckit-tasks
```

No `contracts/`: there is no external interface; the ORM schema and Alembic migration are the contract.

### Source Code (repository root)

```text
alembic.ini
src/ec2_scraping/
├── __init__.py
└── db/
    ├── __init__.py
    ├── base.py
    ├── models.py
    ├── session.py
    └── migrations/
        ├── env.py
        ├── script.py.mako
        └── versions/
            └── 0001_initial_schema.py

tests/
└── schema/
    ├── conftest.py          # applies Alembic migrations to test DB
    ├── test_orm_metadata.py # offline ORM metadata & DDL compile checks
    ├── test_schema.py
    ├── test_instance.py
    ├── test_ami.py
    ├── test_scrape_history.py
    └── test_performance.py
```

**Structure Decision**: SQLAlchemy 2.0 ORM models in `src/ec2_scraping/db/models.py` with Alembic migrations in `src/ec2_scraping/db/migrations/` ( replacing plain SQL in `db/migrations/`), and schema/ORM tests under `tests/schema/`.

## Complexity Tracking

No constitution violations. Soft instance-to-AMI link is a deliberate, documented exception (FR-019).
