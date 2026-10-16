"""MariaDB connection helper."""

import os
from urllib.parse import unquote, urlparse

import pymysql
import pymysql.cursors

DSN_ENV = "MARIADB_DSN"


class ConfigError(Exception):
    """Missing or invalid configuration."""


def parse_dsn(dsn: str) -> dict:
    u = urlparse(dsn)
    if u.scheme not in ("mysql", "mariadb") or not u.hostname or not u.path.strip("/"):
        raise ConfigError("DSN must look like mysql://user:password@host:port/database")
    return {
        "host": u.hostname,
        "port": u.port or 3306,
        "user": unquote(u.username or ""),
        "password": unquote(u.password or ""),
        "database": u.path.lstrip("/"),
    }


def connect(dsn: str | None = None):
    """Open a connection with autocommit off; DSN defaults to env ``MARIADB_DSN``."""
    dsn = dsn or os.environ.get(DSN_ENV)
    if not dsn:
        raise ConfigError(f"no database DSN: pass --dsn or set {DSN_ENV}")
    return pymysql.connect(
        **parse_dsn(dsn),
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )
