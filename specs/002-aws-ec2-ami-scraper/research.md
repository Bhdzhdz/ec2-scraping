# Research

## SSO profiles with boto3
- **Decision**: `boto3.Session(profile_name=...)`; validate with `sts.get_caller_identity()` (also yields account ID). On `SSOTokenLoadError`, `UnauthorizedSSOTokenError`, `TokenRetrievalError`, or `ClientError` ExpiredToken, report "run `aws sso login --profile X`" and skip.
- **Rationale**: boto3 resolves SSO cached tokens natively (needs botocore SSO support, bundled; `awscli` not required at runtime). Meets FR-001/003/007.
- **Alternatives**: spawn `aws sso login` (interactive, violates FR-018); env access keys (violates FR-001).

## Region selection
- **Decision**: `--region` repeatable; `--all-regions` uses `ec2.describe_regions(AllRegions=False)` (enabled regions). Default: profile's configured region.
- **Alternatives**: hard-coded list (goes stale).

## Collection
- **Decision**: boto3 paginators for `describe_instances`, `describe_images(Owners=[account_id])`, plus a batched `describe_images(ImageIds=...)` for AMIs referenced by instances but not owned (tolerate `InvalidAMIID.NotFound`). `describe_instance_types` (batched) for vcpu/memory/arch of types seen. `describe_vpcs`, `describe_subnets`, `describe_security_groups` filtered to IDs seen.
- **Rationale**: paginators satisfy FR-006; filtered lookups bound API cost.
- **Alternatives**: fetching all VPCs/subnets unfiltered (more calls/data).

## Throttling
- **Decision**: botocore `Config(retries={"mode": "adaptive", "max_attempts": 10})`.
- **Alternatives**: custom retry loop (more code).

## Persistence
- **Decision**: one SQLAlchemy `Session` transaction per combination: upsert refs via `sqlalchemy.dialects.mysql.insert(...).on_duplicate_key_update(...)` → sync `Instance`/`Ami` ORM rows (preserving `first_seen_at`) → replace child ORM rows (tags, SGs, volumes, ENIs, block mappings) by delete-then-insert for the resource → commit. Rollback on error (FR-015, FR-010).
- **Alternatives**: row-by-row autocommit (not atomic).

## Scrape-run status and missing resources
- **Decision**: Alembic migration `0002_scrape_scope_status` adds `status ENUM('succeeded','failed','skipped')` and `error TEXT NULL` to `scrape_run_scope` (`ScrapeRunScope` ORM model). Run status: all succeeded → `succeeded`; some → `partial`; none → `failed`. Status assignment (`skipped` vs `failed`) and the unchanged-count rule are defined in data-model.md. Missing = resources in (account, region) whose latest `succeeded` scope run is newer than/different from their `last_scrape_run_id`.
- **Rationale**: without per-combination status, partial failures would wrongly mark resources missing (spec US3 scenario 2).
- **Alternatives**: store only successful combos (loses FR-011 attempted record).

## Interrupts
- **Decision**: on `KeyboardInterrupt`/exception, finalize run as `failed` in a `finally` block; a startup sweep marks stale `running` runs as `failed`.

## Concurrency
- **Decision**: sequential in v1 (Simplicity); 5,000 instances is ~50 paginated calls, well inside SC-005.
