# Database Schema & Migrations

The EC2 instance inventory schema is defined using a single wide **SQLAlchemy 2.0 Declarative ORM model** (`Instance`) in `src/ec2_scraping/db/models.py` and managed with **Alembic migrations** in `src/ec2_scraping/db/migrations/`.

## Design Notes

- **Target engine**: MariaDB 10.6+ / MySQL 8.0+ (`ENGINE=InnoDB`, `DEFAULT CHARSET=utf8mb4`).
- **Wide Single-Table Analytics Schema**: One row per EC2 instance (`UNIQUE (aws_account_id, region, instance_id)`), combining:
  - **Typed scalar columns** for fast filtering and aggregation: lifecycle (`on-demand`/`spot`), tenancy, placement group, CPU/vCPU/GPU/memory/instance-storage specs, EBS volume rollups (`ebs_volume_count`, `ebs_total_size_gib`, `ebs_all_encrypted`, `root_volume_*`), networking (`vpc_cidr`, `subnet_cidr`, `ipv6_address`, `eni_count`), IMDSv2 posture (`imds_http_tokens`), and resolved AMI metadata (`ami_*`).
  - **JSON columns** for multi-valued AWS metadata (`tags`, `security_groups`, `volumes`, `network_interfaces`) and pluggable deep-inspection collectors (`ssh_facts`, `extra_facts`).
- **Analytics View (`v_instance_analytics`)**: Exposes all `instance` columns plus computed analytical fields (`instance_age_days`, `ami_age_days`, `has_public_ip`, `is_imdsv2_enforced`).
- **Pluggable Enrichers**: Additional per-instance collection strategies (such as SSH or SSM inspection) implement the `InstanceEnricher` protocol in `src/ec2_scraping/models.py` and pass into `runner.run(..., enrichers=[...])` to populate `ssh_facts` / `extra_facts` on the same row.

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
