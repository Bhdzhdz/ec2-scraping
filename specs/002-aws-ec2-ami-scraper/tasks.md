# Tasks: AWS EC2/AMI Scraper

**Input**: Design documents in `/specs/002-aws-ec2-ami-scraper/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli.md, quickstart.md
**Tests**: Included (constitution III). AWS calls are stubbed with botocore `Stubber`; DB tests use real MariaDB via `MARIADB_TEST_DSN`.

Format: `- [ ] T### [P?] [US?] Description with file path` ([P] = parallelizable)

## Phase 1: Setup

- [ ] T001 Add `[project.scripts] ec2-scrape = "ec2_scraping.cli:main"` in `pyproject.toml` (`boto3`/`pymysql` already declared); run `uv sync`
- [ ] T002 [P] Create `tests/unit/__init__.py` and `tests/integration/__init__.py`
- [ ] T003 [P] Write `tests/integration/conftest.py`: reuse the DB setup from `tests/schema/conftest.py` (skip if `MARIADB_TEST_DSN` unset; apply all `db/migrations/*.sql`), expose connection fixture
- [ ] T004 [P] Write dataclasses in `src/ec2_scraping/models.py`: `Target(profile, region)`, `InstanceRecord`, `AmiRecord` (with tags, security groups, volumes, ENIs, block mappings), `ComboResult(status, error, counts)`; optional AWS fields typed `| None`

## Phase 2: Foundational (blocks all stories)

- [ ] T005 Write `db/migrations/0006_scrape_scope_status.sql`: `ALTER TABLE scrape_run_scope ADD COLUMN IF NOT EXISTS status ENUM('succeeded','failed','skipped') NOT NULL DEFAULT 'succeeded'` and `ADD COLUMN IF NOT EXISTS error TEXT NULL`
- [ ] T006 [P] Test in `tests/schema/test_scrape_history.py`: migrations apply twice without error with 0006; existing scope rows default to `succeeded`
- [ ] T007 [P] Write `src/ec2_scraping/db.py` plus unit test `tests/unit/test_db.py`: `connect(dsn)` parsing `mysql://user:pw@host:port/db` (default env `MARIADB_DSN`, FR-019; no hard-coded DSN), autocommit off, utf8mb4
- [ ] T008 Write `src/ec2_scraping/load.py` reference upserts (`INSERT ... ON DUPLICATE KEY UPDATE` returning id): `account` (aws_account_id CHAR(12)), `region` (code VARCHAR(32)), `availability_zone`, `instance_type` (name VARCHAR(32), vcpu/memory_mib/architecture NULL), `key_pair`, `iam_instance_profile`, `vpc`, `subnet`, `security_group`
- [ ] T009 [P] Test in `tests/integration/test_load_refs.py`: each reference upsert is idempotent and returns the same id on repeat

**Checkpoint**: schema delta, DB connection, reference loading ready.

## Phase 3: User Story 1 - Scrape one account via SSO profile (P1) 🎯 MVP

**Goal**: `ec2-scrape run --profile X --region R` stores all instances and AMIs, idempotently.
**Independent Test**: Stubbed account with known instances/AMIs loads fully; second run creates no duplicates and advances last-seen; expired session stops with named profile and no data change.

### Tests

- [ ] T010 [P] [US1] Test in `tests/unit/test_session.py`: valid profile returns account ID from `get_caller_identity`; `SSOTokenLoadError`, `UnauthorizedSSOTokenError`, `TokenRetrievalError`, and ExpiredToken `ClientError` raise `SsoLoginRequired(profile)` whose message contains `aws sso login --profile <name>` (FR-003, SC-004)
- [ ] T011 [P] [US1] Test in `tests/unit/test_collect.py` (Stubber): clients are built with adaptive retry config (FR-014); multi-page `describe_instances`/`describe_images` fully collected (FR-006); optional fields absent map to None; referenced non-owned AMI fetched, `InvalidAMIID.NotFound` tolerated; only `Describe*` operations called (constitution I)
- [ ] T012 [P] [US1] Test in `tests/integration/test_load_resources.py`: instance and AMI upserts store all FR-004, FR-005 and FR-008 attributes; reload yields no duplicates, keeps `first_seen_at`, advances `last_seen_at` and `last_scrape_run_id`; removed tags/security groups/volumes/ENIs disappear on reload (FR-009, FR-010); instance with unknown AMI loads (soft link)
- [ ] T013 [P] [US1] Test in `tests/integration/test_runner.py`: successful combo marks run `succeeded` with scope row `succeeded`; mid-load exception rolls back that combo leaving prior data unchanged (FR-015); run row never left `running` after exception or `KeyboardInterrupt` (finally block)

### Implementation

- [ ] T014 [US1] Write `src/ec2_scraping/session.py`: `open_session(profile)` → `boto3.Session(profile_name=...)`, EC2/STS clients with `Config(retries={"mode": "adaptive", "max_attempts": 10})`, `get_caller_identity` for account ID; map SSO errors to `SsoLoginRequired`
- [ ] T015 [US1] Write `src/ec2_scraping/collect.py`: paginators for `describe_instances` and `describe_images(Owners=[account_id])`; batched `describe_images(ImageIds=...)` for referenced AMIs; batched `describe_instance_types`, plus `describe_vpcs`/`describe_subnets`/`describe_security_groups` filtered to IDs seen; return `models` dataclasses
- [ ] T016 [US1] Extend `src/ec2_scraping/load.py`: `load_instances` and `load_amis` upserting on 001 unique keys with `first_seen_at` set on insert only, `last_seen_at`/`last_scrape_run_id` always; child rows replaced per resource (delete then insert) for `instance_tag`, `instance_security_group`, `instance_volume`, `instance_network_interface`, `ami_tag`, `ami_block_device_mapping`; instance `state` ENUM('pending','running','shutting-down','terminated','stopping','stopped'); return created/updated/unchanged counts (unchanged = incoming record and children identical to stored, see data-model.md)
- [ ] T017 [US1] Write `src/ec2_scraping/runner.py`: create `scrape_run` (`running`), per combo run collect+load in one transaction (commit/rollback), write `scrape_run_scope` row, finalize run status in `finally` (all ok → `succeeded`)
- [ ] T018 [US1] Write `src/ec2_scraping/cli.py` `run` subcommand: `--profile` (repeatable, required), `--region` (repeatable, default profile region), `--dsn`; print summary of created/updated/unchanged counts (FR-017); exit codes per `contracts/cli.md`

**Checkpoint**: single-profile scrape works end to end (MVP).

## Phase 4: User Story 2 - Multiple profiles and regions (P2)

**Goal**: One run covers many profile/region combos; failures isolated and reported.
**Independent Test**: Two profiles × two regions stored; one failing combo yields `partial`, exit 1, others stored.

- [ ] T019 [P] [US2] Test in `tests/unit/test_regions.py` (Stubber): `--all-regions` resolves via `describe_regions(AllRegions=False)`; `--all-regions` with `--region` is a usage error (exit 64)
- [ ] T020 [P] [US2] Test in `tests/integration/test_runner_multi.py`: four combos recorded in `scrape_run_scope`; one `SsoLoginRequired` (reported, not stored; writes zero rows and reads no stdin, SC-004/SC-007), one disabled-region (`skipped`), one access-denied and one exhausted-throttling combo (`failed`) → others `succeeded`, stored failures carry `status` and `error` per data-model rule, run `partial`; all failing → `failed`; summary lists failures by profile/region (FR-012, SC-003)
- [ ] T021 [US2] Add region resolution to `src/ec2_scraping/session.py` (`resolve_regions(session, regions, all_regions)`)
- [ ] T022 [US2] Extend `src/ec2_scraping/runner.py`: iterate targets sequentially; catch per-combo errors (login, `ClientError`, DB) and record `skipped` (disabled region; expired login is reported only) or `failed` (API/access/throttle/DB) with `error`; compute `partial`/`failed` run status
- [ ] T023 [US2] Extend `src/ec2_scraping/cli.py`: `--all-regions`, exit codes 0/1/2/64, failure section in summary
- [ ] T030 [US2] Add startup sweep in `src/ec2_scraping/runner.py` marking every `running` run found at startup as `failed` (safe under the single-process assumption in spec.md), with a test in `tests/integration/test_runner_multi.py` (after T022)

## Phase 5: User Story 3 - Detect disappeared resources (P3)

**Goal**: `ec2-scrape missing` lists resources absent from the latest successful run of their scope.
**Independent Test**: Scrape, drop a resource from the stub, rescrape; it appears as missing; a failed combo causes no false positives.

- [ ] T024 [P] [US3] Test in `tests/integration/test_missing.py`: removed instance/AMI listed with unchanged `last_seen_at`; resources in a combo whose latest scope row is `failed` are not listed; scope never successfully scraped yields nothing
- [ ] T025 [US3] Write `src/ec2_scraping/missing.py`: query instances and AMIs whose (account, region) has a latest `succeeded` `scrape_run_scope` run with `last_scrape_run_id` different from it
- [ ] T026 [US3] Add `missing` subcommand to `src/ec2_scraping/cli.py` (`--profile`, `--region`, `--dsn`); output kind, account, region, id, last_seen_at

## Phase 6: Polish & Cross-Cutting

- [ ] T027 [P] Performance test in `tests/integration/test_scale.py`: load 5,000 synthetic instances across 3 regions within 10 min (SC-005), using stubbed collection
- [ ] T028 [P] Document usage, SSO login prerequisite, and env vars in `README.md` and note migration 0006 in `db/README.md`
- [ ] T029 Run quickstart.md validation (automated section; live section when an SSO profile is available), then `uv run ruff check --fix . && uv run ruff format . && uv run ty check && uv run pytest -q -x --tb=short`

## Dependencies & Order

- Phase 1 → Phase 2 → stories. US2 builds on US1 runner/CLI; US3 depends only on Phase 2 and data from US1.
- Within a story: tests first (should fail), then implementation.
- T008 → T016 → T017 → T018; T014/T015 → T017. T021–T023 and T030 follow T017/T018. T025 → T026.

## Parallel Examples

- Setup: T002, T003, T004 together.
- US1 tests: T010–T013 together; then T014 ∥ T015.
- US2 tests: T019 ∥ T020. US3 test T024 can start once Phase 2 is done.

## Implementation Strategy

- **MVP**: Phases 1–3 (single-profile scrape, idempotent load). Validate via quickstart steps 1–2.
- Then add US2 (multi-profile/region isolation), then US3 (missing report), then polish.
