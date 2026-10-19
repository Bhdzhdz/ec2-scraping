# Research: EC2 and AMI Inventory Schema

## Engine and compatibility
- **Decision**: Target MariaDB 10.6+/MySQL 8.0+ using the common subset (InnoDB, utf8mb4, `CREATE TABLE IF NOT EXISTS`, `DATETIME(0)` in UTC).
- **Rationale**: Clarified in spec; common subset avoids lock-in between the two.
- **Alternatives**: Engine-specific features (MySQL `CHECK` semantics, MariaDB sequences) rejected.

## Keys
- **Decision**: Surrogate `BIGINT UNSIGNED AUTO_INCREMENT` primary keys; AWS identifiers kept as `UNIQUE` natural keys with scope (account, region).
- **Rationale**: Compact FKs for child/tag tables; AWS IDs are only unique per region.
- **Alternatives**: Composite natural PKs everywhere — wide FKs and indexes.

## Soft instance-to-AMI link
- **Decision**: `instance.image_id` + `region_id` stored on instance, no FK to `ami`; join on (region, image_id).
- **Rationale**: Instances commonly reference AMIs the account cannot see (FR-005).
- **Alternatives**: Placeholder AMI rows — pollute AMI inventory.

## Tags
- **Decision**: `instance_tag` and `ami_tag` tables, PK (resource_id, tag_key), index on (tag_key, tag_value). Key `VARCHAR(128)`, value `VARCHAR(256)` (AWS limits).
- **Rationale**: Satisfies FR-006/FR-017; index stays under InnoDB 3072-byte limit with utf8mb4.
- **Alternatives**: JSON column — not 3NF, harder to index.

## Instance type facts
- **Decision**: `instance_type` table keyed by name with vcpu, memory_mib, architecture; nullable until enriched.
- **Rationale**: Removes transitive dependency of facts on the instance (3NF).

## Timestamps
- **Decision**: `first_seen_at`, `last_seen_at`, `last_scrape_run_id` on instance and AMI; deliberate denormalization (FR-020).

## ORM & Migrations (001.1)
- **Decision**: SQLAlchemy 2.0 Declarative (`Mapped` / `mapped_column`) with `sqlalchemy.dialects.mysql` types (`BIGINT(unsigned=True)`, `INTEGER(unsigned=True)`, `ENUM`, `CHAR`) + Alembic migrations (`alembic upgrade head`).
- **Rationale**: Single source of truth in typed Python models while preserving exact MariaDB/MySQL column types, constraints, and indexes; `alembic upgrade head` is idempotent when already at head (SC-001).
- **Alternatives**: Raw SQL files — harder to compose with ORM queries and lacks automatic drift check (`alembic check`).

## Testing
- **Decision**: pytest + SQLAlchemy/Alembic + PyMySQL against a disposable MariaDB (`MARIADB_TEST_DSN`), plus offline metadata/migration verification so unit tests run without a live DB.
