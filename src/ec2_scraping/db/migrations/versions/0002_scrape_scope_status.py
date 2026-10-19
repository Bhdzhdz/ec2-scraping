"""Add per-combination status and error columns to scrape_run_scope.

Revision ID: 0002_scrape_scope_status
Revises: 0001_initial_schema
Create Date: 2026-10-16 00:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_scrape_scope_status"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE scrape_run_scope "
        "ADD COLUMN IF NOT EXISTS status ENUM('succeeded','failed','skipped') "
        "NOT NULL DEFAULT 'succeeded', "
        "ADD COLUMN IF NOT EXISTS error TEXT NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE scrape_run_scope DROP COLUMN IF EXISTS error, DROP COLUMN IF EXISTS status"
    )
