# Implementation Plan: EC2 and AMI Inventory Schema (Initial DDL)

**Branch**: `001-ec2-ami-inventory-ddl` | **Date**: 2026-10-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-ec2-ami-inventory-ddl/spec.md`

## Summary

Deliver a 3NF MySQL/MariaDB schema as versioned plain-SQL migration files for EC2 instance and AMI inventory, with reference tables, tag tables, attachments, and scrape-run tracking. Verified by pytest against a throwaway MariaDB container.

## Technical Context

**Language/Version**: SQL (MariaDB 10.6+ / MySQL 8.0+ compatible subset); Python 3.12 for tests only

**Primary Dependencies**: none at runtime; dev: `pymysql` (test driver)

**Storage**: MariaDB/MySQL, InnoDB, utf8mb4

**Testing**: pytest; schema applied to a disposable MariaDB container (`MARIADB_TEST_DSN` env var, tests skipped if unset)

**Target Platform**: Linux server / container

**Project Type**: schema/library (no CLI or API in this feature)

**Performance Goals**: AMI-to-instances and tag key/value lookups under 2 s on 100k instances (SC-004)

**Constraints**: idempotent (`IF NOT EXISTS`), no destructive statements, ordered file names

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

No `contracts/`: there is no external interface; the DDL itself is the contract.

### Source Code (repository root)

```text
db/
└── migrations/
    ├── 0001_reference_tables.sql
    ├── 0002_scrape_runs.sql
    ├── 0003_instances.sql
    ├── 0004_amis.sql
    └── 0005_indexes.sql

tests/
└── schema/
    ├── conftest.py          # applies migrations to test DB
    └── test_schema.py
```

**Structure Decision**: Plain SQL under `db/migrations/`, ordered by numeric prefix; tests under `tests/schema/`.

## Complexity Tracking

No constitution violations. Soft instance-to-AMI link is a deliberate, documented exception (FR-019).
