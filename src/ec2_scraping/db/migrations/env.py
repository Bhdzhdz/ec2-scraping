"""Alembic migration environment configured for ec2_scraping ORM models."""

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

import ec2_scraping.db.models  # noqa: F401
from ec2_scraping.db.base import Base
from ec2_scraping.db.session import normalize_dsn

config = context.config
target_metadata = Base.metadata


def _get_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        url = (
            os.environ.get("DATABASE_URL")
            or os.environ.get("MARIADB_TEST_DSN")
            or "mysql+pymysql://"
        )
    return normalize_dsn(url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = config.attributes.get("connection", None)
    if connectable is None:
        cfg_section = config.get_section(config.config_ini_section, {})
        cfg_section["sqlalchemy.url"] = _get_url()
        connectable = engine_from_config(
            cfg_section,
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    else:
        context.configure(connection=connectable, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
