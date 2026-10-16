-- Reference tables (3NF lookup data). Idempotent; safe to re-run.

CREATE TABLE IF NOT EXISTS account (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  aws_account_id CHAR(12) NOT NULL,
  alias VARCHAR(64) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_account_aws_id (aws_account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS region (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  code VARCHAR(32) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_region_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS availability_zone (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  region_id BIGINT UNSIGNED NOT NULL,
  name VARCHAR(32) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_az_region_name (region_id, name),
  CONSTRAINT fk_az_region FOREIGN KEY (region_id) REFERENCES region (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS instance_type (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  name VARCHAR(32) NOT NULL,
  vcpu INT UNSIGNED NULL,
  memory_mib INT UNSIGNED NULL,
  architecture VARCHAR(16) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_instance_type_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS key_pair (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  account_id BIGINT UNSIGNED NOT NULL,
  region_id BIGINT UNSIGNED NOT NULL,
  name VARCHAR(255) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_key_pair (account_id, region_id, name),
  CONSTRAINT fk_key_pair_account FOREIGN KEY (account_id) REFERENCES account (id),
  CONSTRAINT fk_key_pair_region FOREIGN KEY (region_id) REFERENCES region (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS iam_instance_profile (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  account_id BIGINT UNSIGNED NOT NULL,
  region_id BIGINT UNSIGNED NOT NULL,
  arn VARCHAR(255) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_iam_profile (account_id, region_id, arn),
  CONSTRAINT fk_iam_profile_account FOREIGN KEY (account_id) REFERENCES account (id),
  CONSTRAINT fk_iam_profile_region FOREIGN KEY (region_id) REFERENCES region (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS vpc (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  account_id BIGINT UNSIGNED NOT NULL,
  region_id BIGINT UNSIGNED NOT NULL,
  vpc_id VARCHAR(32) NOT NULL,
  cidr VARCHAR(43) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_vpc (account_id, region_id, vpc_id),
  CONSTRAINT fk_vpc_account FOREIGN KEY (account_id) REFERENCES account (id),
  CONSTRAINT fk_vpc_region FOREIGN KEY (region_id) REFERENCES region (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS subnet (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  vpc_pk BIGINT UNSIGNED NOT NULL,
  availability_zone_id BIGINT UNSIGNED NOT NULL,
  subnet_id VARCHAR(32) NOT NULL,
  cidr VARCHAR(43) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_subnet (vpc_pk, subnet_id),
  CONSTRAINT fk_subnet_vpc FOREIGN KEY (vpc_pk) REFERENCES vpc (id),
  CONSTRAINT fk_subnet_az FOREIGN KEY (availability_zone_id) REFERENCES availability_zone (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS security_group (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  vpc_pk BIGINT UNSIGNED NOT NULL,
  group_id VARCHAR(32) NOT NULL,
  name VARCHAR(255) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_security_group (vpc_pk, group_id),
  CONSTRAINT fk_sg_vpc FOREIGN KEY (vpc_pk) REFERENCES vpc (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
