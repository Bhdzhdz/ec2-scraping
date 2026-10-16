"""Scrape-run lifecycle with per-combination isolation and atomic loads."""

import sys
from collections.abc import Callable

from botocore.exceptions import ClientError, EndpointConnectionError

from ec2_scraping import collect as collect_mod
from ec2_scraping import load, session
from ec2_scraping.models import ComboResult, Counts, RunResult

# Errors meaning "this region is not usable for the account" (stored as skipped).
_DISABLED_CODES = {"AuthFailure", "OptInRequired"}


def sweep_stale_runs(conn) -> int:
    """Mark runs left `running` by a crashed process as failed (single-process assumption)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE scrape_run SET status = 'failed', finished_at = NOW() WHERE status = 'running'"
        )
        swept = cur.rowcount
    conn.commit()
    return swept


def _classify(exc: Exception) -> str:
    if isinstance(exc, EndpointConnectionError):
        return "skipped"
    if (
        isinstance(exc, ClientError)
        and exc.response.get("Error", {}).get("Code") in _DISABLED_CODES
    ):
        return "skipped"
    return "failed"


def _record_scope(conn, run_id: int, account_pk: int, region_pk: int, status: str, error) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scrape_run_scope (scrape_run_id, account_id, region_id, status, error) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE status = VALUES(status), error = VALUES(error)",
            (run_id, account_pk, region_pk, status, error),
        )


def _scrape_combo(conn, run_id, ps, region, collect_fn) -> ComboResult:
    result = ComboResult(ps.profile, region, "succeeded")
    try:
        data = collect_fn(ps.ec2(region), ps.account_id)  # no DB writes before this succeeds
        with conn.cursor() as cur:
            account_pk = load.upsert_account(cur, ps.account_id)
            region_pk = load.upsert_region(cur, region)
            ctx = load.LoadContext(cur, run_id, account_pk, region_pk)
            result.instances = load.load_instances(ctx, data)
            result.amis = load.load_amis(ctx, data)
        _record_scope(conn, run_id, account_pk, region_pk, "succeeded", None)
        conn.commit()
        return result
    except Exception as exc:
        conn.rollback()
        result.status, result.error = _classify(exc), f"{type(exc).__name__}: {exc}"
        result.instances, result.amis = Counts(), Counts()
        try:  # best effort: remember the failed attempt for the missing-resources logic
            with conn.cursor() as cur:
                account_pk = load.upsert_account(cur, ps.account_id)
                region_pk = load.upsert_region(cur, region)
            _record_scope(conn, run_id, account_pk, region_pk, result.status, result.error)
            conn.commit()
        except Exception:
            conn.rollback()
        return result


def _run_status(combos: list[ComboResult]) -> str:
    ok = sum(c.status == "succeeded" for c in combos)
    if combos and ok == len(combos):
        return "succeeded"
    return "partial" if ok else "failed"


def run(
    conn,
    profiles: list[str],
    regions: list[str] | None = None,
    all_regions: bool = False,
    *,
    open_session: Callable = session.open_session,
    collect_fn: Callable = collect_mod.collect,
    progress=sys.stderr,
) -> RunResult:
    """Scrape every profile/region combination under one `scrape_run` row."""
    sweep_stale_runs(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO scrape_run (status) VALUES ('running')")
        run_id = cur.lastrowid
    conn.commit()

    result = RunResult(run_id, "failed")
    final = "failed"  # stays failed if interrupted (e.g. KeyboardInterrupt)
    try:
        for profile in profiles:
            try:
                ps = open_session(profile)
                targets = session.resolve_regions(ps, regions, all_regions)
                if not targets:
                    raise ValueError("no region given and the profile has no default region")
            except session.SsoLoginRequired as exc:
                result.combos.append(ComboResult(profile, None, "skipped", str(exc)))
                continue
            except Exception as exc:
                result.combos.append(
                    ComboResult(profile, None, "failed", f"{type(exc).__name__}: {exc}")
                )
                continue
            for region in targets:
                combo = _scrape_combo(conn, run_id, ps, region, collect_fn)
                result.combos.append(combo)
                print(f"{profile}/{region}: {combo.status}", file=progress)
        final = _run_status(result.combos)
        result.status = final
        return result
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE scrape_run SET status = %s, finished_at = NOW() WHERE id = %s",
                (final, run_id),
            )
        conn.commit()
