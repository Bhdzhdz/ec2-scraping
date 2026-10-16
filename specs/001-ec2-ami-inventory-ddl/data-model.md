# Data Model (3NF, MariaDB/MySQL)

All tables: InnoDB, utf8mb4. `id` = `BIGINT UNSIGNED AUTO_INCREMENT PK`. Times are UTC `DATETIME`. FKs `ON DELETE CASCADE` only where noted.

## Reference tables
| Table | Columns | Keys / constraints |
|---|---|---|
| `account` | id, aws_account_id CHAR(12), alias NULL | UNIQUE(aws_account_id) |
| `region` | id, code VARCHAR(32) | UNIQUE(code) |
| `availability_zone` | id, region_id→region, name VARCHAR(32) | UNIQUE(region_id, name) |
| `instance_type` | id, name VARCHAR(32), vcpu NULL, memory_mib NULL, architecture NULL | UNIQUE(name) |
| `key_pair` | id, account_id, region_id, name VARCHAR(255) | UNIQUE(account_id, region_id, name) |
| `iam_instance_profile` | id, account_id, region_id, arn VARCHAR(255) | UNIQUE(account_id, region_id, arn) |
| `vpc` | id, account_id, region_id, vpc_id VARCHAR(32), cidr NULL | UNIQUE(account_id, region_id, vpc_id) |
| `subnet` | id, vpc_pk→vpc, availability_zone_id→availability_zone, subnet_id VARCHAR(32), cidr NULL | UNIQUE(vpc_pk, subnet_id) |
| `security_group` | id, vpc_pk→vpc, group_id VARCHAR(32), name NULL | UNIQUE(vpc_pk, group_id) |

## Scrape runs
| Table | Columns | Keys |
|---|---|---|
| `scrape_run` | id, started_at, finished_at NULL, status ENUM('running','succeeded','failed','partial') | |
| `scrape_run_scope` | scrape_run_id→scrape_run (CASCADE), account_id, region_id | PK(scrape_run_id, account_id, region_id) |

## Instances
| Table | Columns | Keys |
|---|---|---|
| `instance` | id, account_id, region_id, instance_id VARCHAR(32), instance_type_id, availability_zone_id, subnet_id NULL→subnet, key_pair_id NULL, iam_instance_profile_id NULL, image_id VARCHAR(32), state ENUM('pending','running','shutting-down','terminated','stopping','stopped'), architecture, platform NULL, launch_time, private_ip NULL, public_ip NULL, monitoring ENUM('disabled','enabled','pending'), first_seen_at, last_seen_at, last_scrape_run_id→scrape_run | UNIQUE(account_id, region_id, instance_id); IDX(state), IDX(instance_type_id), IDX(region_id, image_id), IDX(last_scrape_run_id) |
| `instance_security_group` | instance_pk→instance (CASCADE), security_group_pk→security_group | PK(instance_pk, security_group_pk) |
| `instance_volume` | id, instance_pk (CASCADE), device_name, volume_id, size_gib NULL, volume_type NULL | UNIQUE(instance_pk, device_name) |
| `instance_network_interface` | id, instance_pk (CASCADE), eni_id, subnet_id NULL, private_ip NULL, public_ip NULL | UNIQUE(instance_pk, eni_id) |
| `instance_tag` | instance_pk (CASCADE), tag_key VARCHAR(128), tag_value VARCHAR(256) | PK(instance_pk, tag_key); IDX(tag_key, tag_value) |

## AMIs
| Table | Columns | Keys |
|---|---|---|
| `ami` | id, account_id, region_id, image_id VARCHAR(32), owner_aws_account_id CHAR(12), name NULL, description NULL, creation_date NULL, state, architecture, platform NULL, root_device_type, virtualization_type, is_public BOOL, deprecation_time NULL, first_seen_at, last_seen_at, last_scrape_run_id→scrape_run | UNIQUE(account_id, region_id, image_id); IDX(region_id, image_id), IDX(owner_aws_account_id) |
| `ami_block_device_mapping` | id, ami_pk (CASCADE), device_name, snapshot_id NULL, size_gib NULL | UNIQUE(ami_pk, device_name) |
| `ami_tag` | ami_pk (CASCADE), tag_key, tag_value | PK(ami_pk, tag_key); IDX(tag_key, tag_value) |

## Relationships
- instance → instance_type, availability_zone, subnet, key_pair, iam_instance_profile (FK, NULLable where optional).
- instance ⇢ ami: soft join on (region_id, image_id); no FK (FR-019).
- instance ↔ security_group: via `instance_security_group`.
- Missing-in-run query: `last_scrape_run_id <> :run`.
