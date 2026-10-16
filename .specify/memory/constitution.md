<!--
Sync Impact Report
Version change: 1.0.0 → 1.0.1
Modified principles: none
Modified sections: Technical Constraints (datastore: MariaDB only, MariaDB syntax allowed)
Added/Removed sections: none
Deferred TODOs: none
-->
# EC2 Scraping Constitution

## Core Principles

### I. Read-Only AWS Access
The scraper MUST only call AWS describe/list operations. It MUST NOT create, modify, or delete any
AWS resource. Rationale: an inventory tool must be safe to run against production accounts.

### II. Normalized, Idempotent Persistence
The inventory schema MUST be in Third Normal Form, with documented exceptions only. All DDL MUST be
versioned plain SQL, re-runnable without data loss, and loads MUST upsert (never duplicate)
resources. Rationale: repeated scrapes must converge on one consistent inventory.

### III. Test-First Verification
Behavior changes MUST be accompanied by tests written before or with the implementation; schema
changes MUST be verified against a real database. Lint, type check, and tests MUST pass before
merge. Rationale: schema and scraping bugs corrupt data silently.

### IV. Simplicity
Features MUST start with the simplest design that satisfies the spec; added dependencies, tables,
or abstractions MUST be justified in the plan. Rationale: small surface area keeps cost and
maintenance low.

### V. Spec-Driven Development
Non-trivial work MUST follow the Spec Kit flow (specify → clarify → plan → tasks → implement), with
artifacts stored in `specs/`. Rationale: decisions stay traceable and reviewable.

## Technical Constraints

- Language: Python 3.12+, managed with `uv`; lint/format with `ruff`; types with `ty`; tests with
  `pytest`.
- Datastore: MariaDB only (InnoDB, utf8mb4). MariaDB-specific syntax (e.g. `ADD COLUMN IF NOT
  EXISTS`) is permitted; MySQL compatibility is NOT required.
- Credentials MUST come from the standard AWS credential chain or environment, and MUST NOT be
  committed to the repository.

## Development Workflow

- Commits MUST follow Conventional Commits (enforced by a commitizen `commit-msg` hook).
- Pre-commit runs ruff and hygiene checks; pre-push runs `ty` and `pytest`.
- Each plan MUST include a Constitution Check against this document.

## Governance

This constitution supersedes other practices. Amendments require a documented change to this file
with a version bump: MAJOR for removing or redefining principles, MINOR for adding or materially
expanding them, PATCH for clarifications. Plans and reviews MUST verify compliance, and
unavoidable violations MUST be justified in the plan's Complexity Tracking. Runtime guidance for
agents lives in `AGENTS.md`.

**Version**: 1.0.1 | **Ratified**: 2026-10-16 | **Last Amended**: 2026-10-16
