import time

N = 100_000


def test_lookups_under_two_seconds(db):
    rows = [
        (
            "111111111111",
            "us-east-1",
            f"i-{n}",
            "t3.micro",
            "us-east-1a",
            f"ami-{n % 1000}",
            "running",
            "x86_64",
            "2026-01-01",
        )
        for n in range(N)
    ]
    with db.cursor() as cur:
        cur.executemany(
            "INSERT INTO instance (aws_account_id, region, instance_id, instance_type,"
            " availability_zone, image_id, state, architecture, launch_time)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            rows,
        )
        cur.execute("ANALYZE TABLE instance")
        cur.fetchall()
        start = time.perf_counter()
        cur.execute(
            "SELECT instance_id FROM instance WHERE region='us-east-1' AND image_id='ami-0'"
        )
        cur.fetchall()
        assert time.perf_counter() - start < 2
