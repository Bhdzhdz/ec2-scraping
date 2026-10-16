"""Resources not seen in the latest successful run of their (account, region) scope."""

_SQL = """
SELECT '{kind}' AS kind, a.aws_account_id, rg.code AS region, t.{id_col} AS resource_id,
       t.last_seen_at
FROM `{table}` t
JOIN (
  SELECT account_id, region_id, MAX(scrape_run_id) AS run_id
  FROM scrape_run_scope WHERE status = 'succeeded' GROUP BY account_id, region_id
) latest ON latest.account_id = t.account_id AND latest.region_id = t.region_id
JOIN account a ON a.id = t.account_id
JOIN region rg ON rg.id = t.region_id
WHERE (t.last_scrape_run_id IS NULL OR t.last_scrape_run_id < latest.run_id){filters}
ORDER BY a.aws_account_id, rg.code, t.{id_col}
"""


def find_missing(conn, account_ids: list[str] | None = None, regions: list[str] | None = None):
    """Return dict rows (kind, aws_account_id, region, resource_id, last_seen_at)."""
    filters, args = "", []
    if account_ids:
        filters += f" AND a.aws_account_id IN ({', '.join(['%s'] * len(account_ids))})"
        args += account_ids
    if regions:
        filters += f" AND rg.code IN ({', '.join(['%s'] * len(regions))})"
        args += regions
    rows: list[dict] = []
    with conn.cursor() as cur:
        for kind, table, id_col in (
            ("instance", "instance", "instance_id"),
            ("ami", "ami", "image_id"),
        ):
            cur.execute(_SQL.format(kind=kind, table=table, id_col=id_col, filters=filters), args)
            rows += list(cur.fetchall())
    return rows
