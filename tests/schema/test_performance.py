import time

from .conftest import add_ami

N = 100_000


def test_lookups_under_two_seconds(db, ref):
    add_ami(db, ref, "ami-0")
    rows = [
        (
            ref["account"],
            ref["region"],
            f"i-{n}",
            ref["itype"],
            ref["az"],
            f"ami-{n % 1000}",
            "running",
            "x86_64",
            "2026-01-01",
        )
        for n in range(N)
    ]
    with db.cursor() as cur:
        cur.executemany(
            "INSERT INTO instance (account_id, region_id, instance_id, instance_type_id,"
            " availability_zone_id, image_id, state, architecture, launch_time)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            rows,
        )
        cur.execute(
            "INSERT INTO instance_tag SELECT id, 'Env', IF(id % 2, 'prod', 'dev') FROM instance"
        )
        cur.execute("ANALYZE TABLE instance, instance_tag")
        cur.fetchall()
        start = time.perf_counter()
        cur.execute(
            "SELECT i.instance_id FROM instance i JOIN ami a ON a.region_id=i.region_id"
            " AND a.image_id=i.image_id WHERE a.image_id='ami-0'"
        )
        cur.fetchall()
        assert time.perf_counter() - start < 2
        start = time.perf_counter()
        cur.execute("SELECT instance_pk FROM instance_tag WHERE tag_key='Env' AND tag_value='prod'")
        cur.fetchall()
        assert time.perf_counter() - start < 2
