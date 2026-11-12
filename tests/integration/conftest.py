"""Integration fixtures: reuse the schema DB setup (skipped without MARIADB_TEST_DSN)."""

from typing import TYPE_CHECKING, Any

import pytest
from tests.schema.conftest import db, dsn  # noqa: F401

from ec2_scraping.db import connect

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session


@pytest.fixture
def conn(db: Any, dsn: str) -> Iterator[Session]:  # noqa: F811
    """Autocommit-off application connection, like the CLI uses (``db`` is for assertions)."""
    assert db is not None
    connection = connect(dsn)
    yield connection
    connection.close()
