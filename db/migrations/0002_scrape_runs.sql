-- Scrape run tracking. Idempotent; safe to re-run.

CREATE TABLE IF NOT EXISTS scrape_run (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at DATETIME NULL,
  status ENUM('running','succeeded','failed','partial') NOT NULL DEFAULT 'running',
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS scrape_run_scope (
  scrape_run_id BIGINT UNSIGNED NOT NULL,
  account_id BIGINT UNSIGNED NOT NULL,
  region_id BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (scrape_run_id, account_id, region_id),
  CONSTRAINT fk_scope_run FOREIGN KEY (scrape_run_id) REFERENCES scrape_run (id)
    ON DELETE CASCADE,
  CONSTRAINT fk_scope_account FOREIGN KEY (account_id) REFERENCES account (id),
  CONSTRAINT fk_scope_region FOREIGN KEY (region_id) REFERENCES region (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
