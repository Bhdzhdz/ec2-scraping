-- Per-combination outcome for scrape runs (feature 002). Re-runnable (MariaDB syntax).
ALTER TABLE scrape_run_scope
  ADD COLUMN IF NOT EXISTS status ENUM('succeeded','failed','skipped') NOT NULL DEFAULT 'succeeded',
  ADD COLUMN IF NOT EXISTS error TEXT NULL;
