"""Scrape-run lifecycle with per-combination isolation and atomic loads."""

import sys
from collections.abc import Callable
from typing import Any

from botocore.exceptions import ClientError, EndpointConnectionError
from sqlalchemy import func, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from ec2_scraping import collect as collect_mod
from ec2_scraping import load, session
from ec2_scraping.db.models import ScrapeRun, ScrapeRunScope
from ec2_scraping.models import ComboResult, Counts, RunResult

# Errors meaning "this region is not usable for the account" (stored as skipped).
_DISABLED_CODES = {"AuthFailure", "OptInRequired"}


def sweep_stale_runs(db: Session) -> int:
    """Mark runs left `running` by a crashed process as failed (single-process assumption)."""
    res: Any = db.execute(
        update(ScrapeRun)
        .where(ScrapeRun.status == "running")
        .values(status="failed", finished_at=func.now())
    )
    db.commit()
    return int(res.rowcount or 0)


def _classify(exc: Exception) -> str:
    if isinstance(exc, EndpointConnectionError):
        return "skipped"
    if (
        isinstance(exc, ClientError)
        and exc.response.get("Error", {}).get("Code") in _DISABLED_CODES
    ):
        return "skipped"
    return "failed"


def _record_scope(
    db: Session, run_id: int, account_pk: int, region_pk: int, status: str, error: str | None
) -> None:
    stmt = mysql_insert(ScrapeRunScope).values(
        scrape_run_id=run_id,
        account_id=account_pk,
        region_id=region_pk,
        status=status,
        error=error,
    )
    db.execute(
        stmt.on_duplicate_key_update(
            status=stmt.inserted.status,
            error=stmt.inserted.error,
        )
    )


def _scrape_combo(db: Session, run_id: int, ps, region: str, collect_fn: Callable) -> ComboResult:
    result = ComboResult(ps.profile, region, "succeeded")
    try:
        data = collect_fn(ps.ec2(region), ps.account_id)  # no DB writes before this succeeds
        account_pk = load.upsert_account(db, ps.account_id)
        region_pk = load.upsert_region(db, region)
        ctx = load.LoadContext(db, run_id, account_pk, region_pk)
        result.instances = load.load_instances(ctx, data)
        result.amis = load.load_amis(ctx, data)
        _record_scope(db, run_id, account_pk, region_pk, "succeeded", None)
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        result.status, result.error = _classify(exc), f"{type(exc).__name__}: {exc}"
        result.instances, result.amis = Counts(), Counts()
        try:  # best effort: remember the failed attempt for the missing-resources logic
            account_pk = load.upsert_account(db, ps.account_id)
            region_pk = load.upsert_region(db, region)
            _record_scope(db, run_id, account_pk, region_pk, result.status, result.error)
            db.commit()
        except Exception:
            db.rollback()
        return result


def _run_status(combos: list[ComboResult]) -> str:
    ok = sum(c.status == "succeeded" for c in combos)
    if combos and ok == len(combos):
        return "succeeded"
    return "partial" if ok else "failed"


def run(
    db: Session,
    profiles: list[str],
    regions: list[str] | None = None,
    all_regions: bool = False,
    *,
    open_session: Callable = session.open_session,
    collect_fn: Callable = collect_mod.collect,
    progress=sys.stderr,
) -> RunResult:
    """Scrape every profile/region combination under one `scrape_run` row."""
    sweep_stale_runs(db)
    scrape_run = ScrapeRun(status="running")
    db.add(scrape_run)
    db.commit()
    run_id = scrape_run.id

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
                combo = _scrape_combo(db, run_id, ps, region, collect_fn)
                result.combos.append(combo)
                print(f"{profile}/{region}: {combo.status}", file=progress)
        final = _run_status(result.combos)
        result.status = final
        return result
    finally:
        db.rollback()
        db.execute(
            update(ScrapeRun)
            .where(ScrapeRun.id == run_id)
            .values(status=final, finished_at=func.now())
        )
        db.commit()
