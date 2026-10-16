# Quickstart: Validate the Schema

## Prerequisites
- Docker, `uv sync`
- Start a disposable DB: `docker run -d --name ec2inv-test -e MARIADB_ROOT_PASSWORD=pw -e MARIADB_DATABASE=inv -p 3307:3306 mariadb:10.11`
- `export MARIADB_TEST_DSN="mysql://root:pw@127.0.0.1:3307/inv"`

## Run
- Apply: execute `db/migrations/*.sql` in filename order (done by `tests/schema/conftest.py`).
- Test: `uv run pytest tests/schema -q -x --tb=short`

## Expected
- Applying twice succeeds (SC-001).
- Duplicate instance load violates the unique key (SC-003).
- Round-trip of all FR-002/FR-004 attributes (SC-002).
- Lookup queries meet SC-004 on a seeded 100k-row set; missing-in-run query works (SC-005).

See [data-model.md](data-model.md) for tables.
