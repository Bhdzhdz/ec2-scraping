# CLI Contract: `ec2-scrape`

## `ec2-scrape run`
| Option | Meaning |
|---|---|
| `--profile NAME` (repeatable, required) | AWS SSO profile |
| `--region CODE` (repeatable) | Region; default profile's region |
| `--all-regions` | All enabled regions (exclusive with `--region`) |
| `--dsn URL` | DB DSN; default env `MARIADB_DSN` |

Output: per-combination progress to stderr; final summary to stdout (instances/AMIs created, updated, unchanged; failures with profile/region/cause).

## `ec2-scrape missing`
Options: `--profile`, `--region` (same scope selection), `--dsn`. Lists resources (kind, account, region, id, last_seen_at) not seen in the latest successful run of their scope.

## Exit codes
| Code | Meaning |
|---|---|
| 0 | All combinations succeeded |
| 1 | Partial (some failed) |
| 2 | Total failure |
| 64 | Usage/config error |
