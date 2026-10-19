# Data Model Delta

Uses all 001 tables ([../001-ec2-ami-inventory-ddl/data-model.md](../001-ec2-ami-inventory-ddl/data-model.md)). One change:

## `scrape_run_scope` (Alembic migration `0002_scrape_scope_status.py` / `ScrapeRunScope` ORM model)
| Column | Type | Notes |
|---|---|---|
| `status` | ENUM('succeeded','failed','skipped') NOT NULL DEFAULT 'succeeded' | per account/region outcome |
| `error` | TEXT NULL | failure cause (set when failed/skipped) |

- Re-runnable (MariaDB `ADD COLUMN IF NOT EXISTS`; MariaDB is the only supported datastore). Existing rows default to `succeeded`.
- A failed SSO login has no account/region ids, so the profile is recorded in CLI output/exit status only; skipped-before-account failures are not stored.
- **Status rule**: `skipped` = SSO login expired (reported, not stored, see above) or region not enabled for the account (stored); `failed` = API errors (including exhausted throttling retries), access denied, DB errors. Either counts against the run (`partial`/`failed`).
- **Unchanged rule** (FR-017): before each upsert, the incoming record (attributes plus tags, security groups, volumes, ENIs, block mappings) is compared with the stored row and children; identical → `unchanged` (only `last_seen_at`/`last_scrape_run_id` advance), otherwise `updated`; absent → `created`.

## Mapping (AWS → 001)
| AWS | Table(s) |
|---|---|
| Reservations[].Instances[] | `instance` + `instance_type`, `availability_zone`, `subnet`, `key_pair`, `iam_instance_profile` |
| SecurityGroups / BlockDeviceMappings / NetworkInterfaces / Tags | `instance_security_group`+`security_group`, `instance_volume`, `instance_network_interface`, `instance_tag` |
| Images[] | `ami`, `ami_block_device_mapping`, `ami_tag` |
| STS identity | `account` |

## Run state
`running` → `succeeded` | `partial` | `failed`. Scope row per combination attempted with its own status.

## Validation rules
- Optional AWS fields absent → NULL.
- `first_seen_at` set on insert only; `last_seen_at` and `last_scrape_run_id` set every upsert.
