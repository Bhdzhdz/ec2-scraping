"""Database engine, session, and Alembic migration helpers."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def normalize_dsn(dsn: str) -> str:
    """Ensure MySQL/MariaDB DSNs use the ``mysql+pymysql://`` driver prefix."""
    if dsn.startswith("mysql://"):
        return "mysql+pymysql://" + dsn.removeprefix("mysql://")
    if dsn.startswith("mariadb://"):
        return "mysql+pymysql://" + dsn.removeprefix("mariadb://")
    return dsn


def make_engine(dsn: str) -> Engine:
    """Create a SQLAlchemy engine for the given DSN."""
    return create_engine(normalize_dsn(dsn), pool_pre_ping=True)


def make_session_factory(dsn_or_engine: str | Engine) -> sessionmaker[Session]:
    """Create a ``sessionmaker`` bound to an engine or DSN."""
    engine = make_engine(dsn_or_engine) if isinstance(dsn_or_engine, str) else dsn_or_engine
    return sessionmaker(bind=engine, expire_on_commit=False)


def make_alembic_config(dsn: str | None = None) -> Config:
    """Build an Alembic ``Config`` pointing at the bundled migrations directory."""
    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    if dsn:
        cfg.set_main_option("sqlalchemy.url", normalize_dsn(dsn))
    return cfg


def upgrade_db(dsn: str, revision: str = "head", *, sql: bool = False) -> None:
    """Run ``alembic upgrade`` programmatically against ``dsn``."""
    cfg = make_alembic_config(dsn)
    command.upgrade(cfg, revision, sql=sql)
