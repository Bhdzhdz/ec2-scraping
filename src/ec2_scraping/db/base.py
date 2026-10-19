"""Declarative base and shared column types for the MariaDB/MySQL inventory schema."""

from sqlalchemy.dialects.mysql import BIGINT, INTEGER
from sqlalchemy.orm import DeclarativeBase

UBigInt = BIGINT(unsigned=True)
UInt = INTEGER(unsigned=True)
TABLE_DEFAULTS: dict[str, str] = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


class Base(DeclarativeBase):
    """Base class for all inventory ORM models (InnoDB, utf8mb4)."""

    __table_args__ = (TABLE_DEFAULTS,)
