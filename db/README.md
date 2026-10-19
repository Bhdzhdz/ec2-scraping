# Database Schema & Migrations

The EC2 and AMI inventory schema is defined using **SQLAlchemy 2.0 Declarative ORM models** in `src/ec2_scraping/db/models.py` and managed with **Alembic migrations** in `src/ec2_scraping/db/migrations/`.

## Design Notes

- **Target engine**: MariaDB 10.6+ / MySQL 8.0+ (`ENGINE=InnoDB`, `DEFAULT CHARSET=utf8mb4`).
- **3NF normalization**: Reference entities (`account`, `region`, `availability_zone`, `instance_type`, `key_pair`, `iam_instance_profile`, `vpc`, `subnet`, `security_group`) are stored once and referenced by surrogate `BIGINT UNSIGNED` primary keys.
- **Soft instance-to-AMI link (FR-019)**: `instance.image_id` deliberately has **no foreign key** to `ami` because instances frequently reference public, shared, or deregistered AMIs not yet present in the AMI table. Join `instance` to `ami` on `(region_id, image_id)`.
- **Idempotency (FR-013 / SC-001)**: Migrations use `if_not_exists=True` and Alembic tracks applied revisions in `alembic_version`, so running `alembic upgrade head` (or `upgrade_db(dsn)`) multiple times is a safe no-op.

## Running Migrations

```bash
export DATABASE_URL="mysql+pymysql://user:pass@localhost:3306/inv"
uv run alembic upgrade head
```

Or programmatically in Python:

```python
from ec2_scraping.db import upgrade_db

upgrade_db("mysql://user:pass@localhost:3306/inv")
```
