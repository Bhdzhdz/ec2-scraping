# Tasks: EC2 and AMI Inventory Schema (Initial DDL)

**Input**: Design documents in `/specs/001-ec2-ami-inventory-ddl/`
**Prerequisites**: plan.md, spec.md, data-model.md, research.md, quickstart.md
**Tests**: Included (plan and constitution require schema verification against a real database).

Format: `- [ ] T### [P?] [US?] Description with file path` ([P] = parallelizable)

All tables: InnoDB, utf8mb4, `IF NOT EXISTS`, no destructive statements; `id` is `BIGINT UNSIGNED AUTO_INCREMENT` PK; times are UTC `DATETIME`.

## Phase 1: Setup

- [X] T001 Create `db/migrations/` and `tests/schema/` directories (with `tests/schema/__init__.py`)
- [X] T002 [P] Add dev dependency `pymysql` via `uv add --dev pymysql` in `pyproject.toml`
- [X] T003 [P] Write `tests/schema/conftest.py`: read `MARIADB_TEST_DSN` (skip all tests if unset), drop/recreate test DB, apply `db/migrations/*.sql` in filename order, expose connection fixture

## Phase 2: Foundational (blocks all stories)

- [X] T004 Write `db/migrations/0001_reference_tables.sql` with `account` (aws_account_id CHAR(12) UNIQUE, alias NULL), `region` (code VARCHAR(32) UNIQUE), `availability_zone` (region_id FK, name VARCHAR(32), UNIQUE(region_id, name)), `instance_type` (name VARCHAR(32) UNIQUE, vcpu NULL, memory_mib NULL, architecture NULL)
- [X] T005 Extend `db/migrations/0001_reference_tables.sql` with `key_pair` (name VARCHAR(255), UNIQUE(account_id, region_id, name)), `iam_instance_profile` (arn VARCHAR(255), UNIQUE(account_id, region_id, arn)), `vpc` (vpc_id VARCHAR(32), cidr NULL, UNIQUE(account_id, region_id, vpc_id)), `subnet` (vpc_pk FK, availability_zone_id FK, subnet_id VARCHAR(32), cidr NULL, UNIQUE(vpc_pk, subnet_id)), `security_group` (vpc_pk FK, group_id VARCHAR(32), name NULL, UNIQUE(vpc_pk, group_id))
- [X] T006 Write `db/migrations/0002_scrape_runs.sql` with `scrape_run` (started_at, finished_at NULL, status ENUM('running','succeeded','failed','partial')) and `scrape_run_scope` (scrape_run_id FK ON DELETE CASCADE, account_id, region_id, PK(scrape_run_id, account_id, region_id))
- [X] T007 [P] Test in `tests/schema/test_schema.py`: all migrations apply, then apply a second time without error (SC-001, FR-013)
- [X] T008 [P] Test in `tests/schema/test_schema.py`: reference-table unique keys reject duplicates; scrape_run_scope cascades on scrape_run delete

**Checkpoint**: reference and scrape-run tables exist.

## Phase 3: User Story 1 - EC2 instance inventory (P1) 🎯 MVP

**Goal**: Store instances with attachments and tags, upsert-safe.
**Independent Test**: Load sample instances; query by account, region, state, tag; reload same instance without duplicates.

- [X] T009 [P] [US1] Test in `tests/schema/test_instance.py`: round-trip every FR-002 attribute, including NULL optional fields (key pair, IAM profile, public IP, platform)
- [X] T010 [P] [US1] Test in `tests/schema/test_instance.py`: duplicate (account_id, region_id, instance_id) is rejected and `INSERT ... ON DUPLICATE KEY UPDATE` updates in place (SC-003)
- [X] T011 [P] [US1] Test in `tests/schema/test_instance.py`: tags retrievable and filterable by key and value; deleting an instance cascades to tags, volumes, interfaces, security-group links (FR-012)
- [X] T012 [US1] Write `db/migrations/0003_instances.sql` with `instance`: account_id, region_id, instance_id VARCHAR(32), instance_type_id, availability_zone_id, subnet_id NULL, key_pair_id NULL, iam_instance_profile_id NULL, image_id VARCHAR(32), state ENUM('pending','running','shutting-down','terminated','stopping','stopped'), architecture, platform NULL, launch_time, private_ip NULL, public_ip NULL, monitoring ENUM('disabled','enabled','pending'), first_seen_at, last_seen_at, last_scrape_run_id FK; UNIQUE(account_id, region_id, instance_id); no FK on image_id (FR-019)
- [X] T013 [US1] Extend `db/migrations/0003_instances.sql` with `instance_security_group` (PK(instance_pk, security_group_pk), CASCADE), `instance_volume` (device_name, volume_id, size_gib NULL, volume_type NULL, UNIQUE(instance_pk, device_name), CASCADE), `instance_network_interface` (eni_id, subnet_id NULL, private_ip NULL, public_ip NULL, UNIQUE(instance_pk, eni_id), CASCADE)
- [X] T014 [US1] Extend `db/migrations/0003_instances.sql` with `instance_tag` (tag_key VARCHAR(128), tag_value VARCHAR(256), PK(instance_pk, tag_key), CASCADE, INDEX(tag_key, tag_value))
- [X] T015 [US1] Add indexes on `instance` in `db/migrations/0003_instances.sql`: IDX(state), IDX(instance_type_id), IDX(region_id, image_id), IDX(last_scrape_run_id)

**Checkpoint**: US1 tests pass independently.

## Phase 4: User Story 2 - AMI inventory linked to instances (P1)

**Goal**: Store AMIs and join instances to them, including AMIs not yet discovered.
**Independent Test**: List instances per AMI and AMIs with no instances.

- [X] T016 [P] [US2] Test in `tests/schema/test_ami.py`: round-trip every FR-004 attribute incl. NULL deprecation_time; duplicate (account_id, region_id, image_id) rejected; block device mappings and tags cascade on AMI delete
- [X] T017 [P] [US2] Test in `tests/schema/test_ami.py`: instances join to AMIs on (region_id, image_id); an instance whose AMI is absent still inserts, and the join resolves after the AMI is later inserted (FR-005)
- [X] T018 [US2] Write `db/migrations/0004_amis.sql` with `ami`: account_id, region_id, image_id VARCHAR(32), owner_aws_account_id CHAR(12), name NULL, description NULL, creation_date NULL, state, architecture, platform NULL, root_device_type, virtualization_type, is_public BOOL, deprecation_time NULL, first_seen_at, last_seen_at, last_scrape_run_id FK; UNIQUE(account_id, region_id, image_id); IDX(region_id, image_id), IDX(owner_aws_account_id)
- [X] T019 [US2] Extend `db/migrations/0004_amis.sql` with `ami_block_device_mapping` (device_name, snapshot_id NULL, size_gib NULL, UNIQUE(ami_pk, device_name), CASCADE) and `ami_tag` (tag_key VARCHAR(128), tag_value VARCHAR(256), PK(ami_pk, tag_key), CASCADE, INDEX(tag_key, tag_value))

**Checkpoint**: US1 and US2 independently pass.

## Phase 5: User Story 3 - Scrape history tracking (P2)

**Goal**: Identify resources not seen in the latest run.
**Independent Test**: Two runs, one instance absent in the second, found by one query.

- [X] T020 [US3] Test in `tests/schema/test_scrape_history.py`: after two runs where an instance and an AMI appear only in run 1, `WHERE last_scrape_run_id <> :run2` returns exactly those rows, and first_seen_at is unchanged on reload (SC-005)
- [X] T021 [US3] Fix any gaps found by T020 in `db/migrations/0002_scrape_runs.sql`, `0003_instances.sql`, or `0004_amis.sql` (e.g. defaults for first_seen_at/last_seen_at)

## Phase 6: Polish & Cross-Cutting

- [X] T022 Write `db/migrations/0005_indexes.sql` for any extra indexes found necessary by T023 (idempotent; may be empty with a comment)
- [X] T023 Performance test in `tests/schema/test_performance.py`: seed 100,000 instances, assert AMI-to-instances and tag key=value queries each finish under 2 s (SC-004)
- [X] T024 [P] Add a `db/README.md` documenting migration order and soft instance-to-AMI link, and note the DB test setup in `README.md`
- [X] T025 Run quickstart.md validation, then `uv run ruff check --fix . && uv run ruff format . && uv run ty check && uv run pytest -q -x --tb=short`

## Dependencies & Order

- Phase 1 → Phase 2 → stories → Polish.
- US1 and US2 are independent after Phase 2 (different migration files); US3 needs both.
- Within a story, tests (marked [P]) are written first and should fail before the migration tasks.
- T004→T005 and T012→T013→T014→T015 edit the same files and are sequential.

## Parallel Examples

- Setup: T002 and T003 together.
- US1 tests: T009, T010, T011 together.
- After Phase 2: US1 (T009–T015) and US2 (T016–T019) in parallel.

## Implementation Strategy

- **MVP**: Phases 1–3 (instance inventory); validate before continuing.
- Then add AMIs (US2), then history (US3), then polish and performance.
