"""Integration fixtures: reuse the schema DB setup (skipped without MARIADB_TEST_DSN)."""

import pytest
from tests.schema.conftest import db, dsn  # noqa: F401

from ec2_scraping.db import connect


@pytest.fixture
def conn(db, dsn):  # noqa: F811
    """Autocommit-off application connection, like the CLI uses (``db`` is for assertions)."""
    connection = connect(dsn)
    yield connection
    connection.close()
