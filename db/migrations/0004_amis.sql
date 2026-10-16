-- AMI inventory. Idempotent; safe to re-run.

CREATE TABLE IF NOT EXISTS ami (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  account_id BIGINT UNSIGNED NOT NULL,
  region_id BIGINT UNSIGNED NOT NULL,
  image_id VARCHAR(32) NOT NULL,
  owner_aws_account_id CHAR(12) NOT NULL,
  name VARCHAR(255) NULL,
  description VARCHAR(1024) NULL,
  creation_date DATETIME NULL,
  state ENUM('pending','available','invalid','deregistered','transient','failed','error',
             'disabled') NOT NULL,
  architecture VARCHAR(16) NOT NULL,
  platform VARCHAR(32) NULL,
  root_device_type VARCHAR(16) NOT NULL,
  virtualization_type VARCHAR(16) NOT NULL,
  is_public BOOLEAN NOT NULL DEFAULT 0,
  deprecation_time DATETIME NULL,
  first_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_scrape_run_id BIGINT UNSIGNED NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_ami (account_id, region_id, image_id),
  KEY ix_ami_image (region_id, image_id),
  KEY ix_ami_owner (owner_aws_account_id),
  KEY ix_ami_last_run (last_scrape_run_id),
  CONSTRAINT fk_ami_account FOREIGN KEY (account_id) REFERENCES account (id),
  CONSTRAINT fk_ami_region FOREIGN KEY (region_id) REFERENCES region (id),
  CONSTRAINT fk_ami_run FOREIGN KEY (last_scrape_run_id) REFERENCES scrape_run (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ami_block_device_mapping (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  ami_pk BIGINT UNSIGNED NOT NULL,
  device_name VARCHAR(255) NOT NULL,
  snapshot_id VARCHAR(32) NULL,
  size_gib INT UNSIGNED NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_ami_bdm (ami_pk, device_name),
  CONSTRAINT fk_bdm_ami FOREIGN KEY (ami_pk) REFERENCES ami (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ami_tag (
  ami_pk BIGINT UNSIGNED NOT NULL,
  tag_key VARCHAR(128) NOT NULL,
  tag_value VARCHAR(256) NOT NULL,
  PRIMARY KEY (ami_pk, tag_key),
  KEY ix_ami_tag_kv (tag_key, tag_value),
  CONSTRAINT fk_at_ami FOREIGN KEY (ami_pk) REFERENCES ami (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
