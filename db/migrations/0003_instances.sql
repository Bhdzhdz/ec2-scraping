-- EC2 instance inventory. Idempotent; safe to re-run.
-- instance.image_id deliberately has NO foreign key to ami (FR-019): join on (region_id, image_id).

CREATE TABLE IF NOT EXISTS instance (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  account_id BIGINT UNSIGNED NOT NULL,
  region_id BIGINT UNSIGNED NOT NULL,
  instance_id VARCHAR(32) NOT NULL,
  instance_type_id BIGINT UNSIGNED NOT NULL,
  availability_zone_id BIGINT UNSIGNED NOT NULL,
  subnet_pk BIGINT UNSIGNED NULL,
  key_pair_id BIGINT UNSIGNED NULL,
  iam_instance_profile_id BIGINT UNSIGNED NULL,
  image_id VARCHAR(32) NOT NULL,
  state ENUM('pending','running','shutting-down','terminated','stopping','stopped') NOT NULL,
  architecture VARCHAR(16) NOT NULL,
  platform VARCHAR(32) NULL,
  launch_time DATETIME NOT NULL,
  private_ip VARCHAR(45) NULL,
  public_ip VARCHAR(45) NULL,
  monitoring ENUM('disabled','enabled','pending') NOT NULL DEFAULT 'disabled',
  first_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_scrape_run_id BIGINT UNSIGNED NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_instance (account_id, region_id, instance_id),
  KEY ix_instance_state (state),
  KEY ix_instance_type (instance_type_id),
  KEY ix_instance_image (region_id, image_id),
  KEY ix_instance_last_run (last_scrape_run_id),
  CONSTRAINT fk_instance_account FOREIGN KEY (account_id) REFERENCES account (id),
  CONSTRAINT fk_instance_region FOREIGN KEY (region_id) REFERENCES region (id),
  CONSTRAINT fk_instance_type FOREIGN KEY (instance_type_id) REFERENCES instance_type (id),
  CONSTRAINT fk_instance_az FOREIGN KEY (availability_zone_id) REFERENCES availability_zone (id),
  CONSTRAINT fk_instance_subnet FOREIGN KEY (subnet_pk) REFERENCES subnet (id),
  CONSTRAINT fk_instance_key_pair FOREIGN KEY (key_pair_id) REFERENCES key_pair (id),
  CONSTRAINT fk_instance_profile FOREIGN KEY (iam_instance_profile_id)
    REFERENCES iam_instance_profile (id),
  CONSTRAINT fk_instance_run FOREIGN KEY (last_scrape_run_id) REFERENCES scrape_run (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS instance_security_group (
  instance_pk BIGINT UNSIGNED NOT NULL,
  security_group_pk BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (instance_pk, security_group_pk),
  CONSTRAINT fk_isg_instance FOREIGN KEY (instance_pk) REFERENCES instance (id)
    ON DELETE CASCADE,
  CONSTRAINT fk_isg_sg FOREIGN KEY (security_group_pk) REFERENCES security_group (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS instance_volume (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  instance_pk BIGINT UNSIGNED NOT NULL,
  device_name VARCHAR(255) NOT NULL,
  volume_id VARCHAR(32) NOT NULL,
  size_gib INT UNSIGNED NULL,
  volume_type VARCHAR(16) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_instance_volume (instance_pk, device_name),
  CONSTRAINT fk_iv_instance FOREIGN KEY (instance_pk) REFERENCES instance (id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS instance_network_interface (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  instance_pk BIGINT UNSIGNED NOT NULL,
  eni_id VARCHAR(32) NOT NULL,
  subnet_pk BIGINT UNSIGNED NULL,
  private_ip VARCHAR(45) NULL,
  public_ip VARCHAR(45) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_instance_eni (instance_pk, eni_id),
  CONSTRAINT fk_ini_instance FOREIGN KEY (instance_pk) REFERENCES instance (id)
    ON DELETE CASCADE,
  CONSTRAINT fk_ini_subnet FOREIGN KEY (subnet_pk) REFERENCES subnet (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS instance_tag (
  instance_pk BIGINT UNSIGNED NOT NULL,
  tag_key VARCHAR(128) NOT NULL,
  tag_value VARCHAR(256) NOT NULL,
  PRIMARY KEY (instance_pk, tag_key),
  KEY ix_instance_tag_kv (tag_key, tag_value),
  CONSTRAINT fk_it_instance FOREIGN KEY (instance_pk) REFERENCES instance (id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
