# EC2 Scraping

Geenerate an inventory of the ec2 instances on an aws account and get metadata from them

## Development

```bash
uv sync                      # install deps
uv run pre-commit install    # hooks (commit + pre-push)
uv run ruff check . && uv run ruff format .
uv run ty check
uv run pytest
```

Pre-commit runs ruff + hygiene checks; pre-push runs `ty` and `pytest`.

## Database Schema & Migrations

The 3NF MariaDB/MySQL schema is defined as SQLAlchemy 2.0 ORM models in `src/ec2_scraping/db/models.py` with Alembic migrations in `src/ec2_scraping/db/migrations/` (see [`db/README.md`](db/README.md)).

```bash
# Apply migrations to a target database:
DATABASE_URL="mysql+pymysql://root:pw@127.0.0.1:3307/inv" uv run alembic upgrade head

# Run live DB schema tests against a disposable MariaDB instance:
MARIADB_TEST_DSN="mysql://root:pw@127.0.0.1:3307/inv" uv run pytest tests/schema -q
```

## Docker

```bash
docker build -t ec2-scraping .
docker run --rm ec2-scraping
```
