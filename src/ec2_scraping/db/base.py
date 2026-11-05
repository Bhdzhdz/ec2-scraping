"""Declarative base and shared column types for the MariaDB/MySQL and SQLite inventory schema."""

from sqlalchemy import BigInteger, Integer
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase

UBigInt = (
    BigInteger()
    .with_variant(mysql.BIGINT(unsigned=True), "mysql", "mariadb")
    .with_variant(Integer(), "sqlite")
)
UInt = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql", "mariadb")
TABLE_DEFAULTS: dict[str, str] = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


class Base(DeclarativeBase):
    """Base class for all inventory ORM models (MySQL/MariaDB and SQLite)."""

    __table_args__ = (TABLE_DEFAULTS,)
