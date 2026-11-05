"""Database engine, session, and Alembic migration helpers with SQLite fallback."""

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

DSN_ENV = "MARIADB_DSN"
DEFAULT_SQLITE_DSN = "sqlite:///ec2_inventory.db"
_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class ConfigError(Exception):
    """Missing or invalid configuration."""


def parse_dsn(dsn: str) -> dict:
    """Validate and parse a MariaDB/MySQL or SQLite DSN."""
    if not dsn:
        raise ConfigError(
            "DSN must look like mysql://user:password@host:port/database or sqlite:///path.db"
        )
    u = urlparse(dsn)
    if u.scheme in ("sqlite", "sqlite+pysqlite"):
        return {
            "scheme": "sqlite",
            "database": dsn.split(":///", 1)[1] if ":///" in dsn else ":memory:",
        }
    if (
        u.scheme not in ("mysql", "mariadb", "mysql+pymysql")
        or not u.hostname
        or not u.path.strip("/")
    ):
        raise ConfigError(
            "DSN must look like mysql://user:password@host:port/database or sqlite:///path.db"
        )
    return {
        "host": u.hostname,
        "port": u.port or 3306,
        "user": unquote(u.username or ""),
        "password": unquote(u.password or ""),
        "database": u.path.lstrip("/"),
    }


def normalize_dsn(dsn: str) -> str:
    """Ensure MySQL/MariaDB DSNs use ``mysql+pymysql://`` and validate SQLite DSNs."""
    parse_dsn(dsn)
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


def _init_sqlite_engine(sqlite_dsn: str) -> Engine:
    engine = make_engine(sqlite_dsn)
    with engine.begin() as conn:
        cfg = make_alembic_config()
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    return engine


def connect(dsn: str | None = None, *, fallback_dsn: str = DEFAULT_SQLITE_DSN) -> Session:
    """Open a SQLAlchemy ORM Session; falls back to SQLite if MariaDB is unset or unreachable."""
    dsn = dsn or os.environ.get(DSN_ENV)
    if not dsn:
        engine = _init_sqlite_engine(fallback_dsn)
        return make_session_factory(engine)()

    norm = normalize_dsn(dsn)
    if norm.startswith("sqlite"):
        engine = _init_sqlite_engine(norm)
        return make_session_factory(engine)()

    engine = make_engine(norm)
    try:
        with engine.connect() as probe:
            probe.execute(text("SELECT 1"))
    except OperationalError:
        engine.dispose()
        engine = _init_sqlite_engine(fallback_dsn)
    return make_session_factory(engine)()


def make_alembic_config(dsn: str | None = None) -> Config:
    """Build an Alembic ``Config`` pointing at the bundled migrations directory."""
    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    if dsn:
        cfg.set_main_option("sqlalchemy.url", normalize_dsn(dsn))
    return cfg


def upgrade_db(dsn: str | None = None, revision: str = "head", *, sql: bool = False) -> None:
    """Run ``alembic upgrade`` programmatically against ``dsn`` (or SQLite fallback)."""
    target = dsn or os.environ.get(DSN_ENV) or DEFAULT_SQLITE_DSN
    cfg = make_alembic_config(target)
    command.upgrade(cfg, revision, sql=sql)
