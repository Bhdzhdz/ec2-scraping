"""Scrape lifecycle with per-combination isolation, pluggable enrichers, and atomic loads."""

import sys
from collections.abc import Callable, Sequence

from botocore.exceptions import ClientError, EndpointConnectionError
from sqlalchemy.orm import Session

from ec2_scraping import collect as collect_mod
from ec2_scraping import load, session
from ec2_scraping.models import (
    Collected,
    ComboResult,
    Counts,
    EnrichmentResult,
    InstanceEnricher,
    RunResult,
)

# Errors meaning "this region is not usable for the account" (stored as skipped).
_DISABLED_CODES = {"AuthFailure", "OptInRequired"}


def _classify(exc: Exception) -> str:
    if isinstance(exc, EndpointConnectionError):
        return "skipped"
    if (
        isinstance(exc, ClientError)
        and exc.response.get("Error", {}).get("Code") in _DISABLED_CODES
    ):
        return "skipped"
    return "failed"


def _run_enrichers(
    db: Session,
    aws_account_id: str,
    region: str,
    data: Collected,
    enrichers: Sequence[InstanceEnricher],
) -> dict[str, dict[str, EnrichmentResult]]:
    if not enrichers or not data.instances:
        return {}
    results: dict[str, dict[str, EnrichmentResult]] = {
        inst.instance_id: {} for inst in data.instances
    }
    ami_names = {k: v.name for k, v in data.amis.items()}
    for enricher in enrichers:
        targets = data.instances
        if enricher.name == "ssh" and getattr(enricher, "only_unaccessed", False):
            already_accessed = load.get_accessed_ssh_instance_ids(
                db, aws_account_id, region, [i.instance_id for i in data.instances]
            )
            targets = [i for i in data.instances if i.instance_id not in already_accessed]
            if not targets:
                continue

        batch_fn = getattr(enricher, "enrich_batch", None)
        if callable(batch_fn):
            try:
                batch_res = batch_fn(aws_account_id, region, targets, ami_names)
                for inst_id, res in batch_res.items():
                    if inst_id in results:
                        results[inst_id][enricher.name] = res
                continue
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
                for inst in targets:
                    results[inst.instance_id][enricher.name] = EnrichmentResult(
                        status="failed", error=err
                    )
                continue

        for inst in targets:
            try:
                results[inst.instance_id][enricher.name] = enricher.enrich(
                    aws_account_id, region, inst
                )
            except Exception as exc:
                results[inst.instance_id][enricher.name] = EnrichmentResult(
                    status="failed", error=f"{type(exc).__name__}: {exc}"
                )
    return results


def _scrape_combo(
    db: Session,
    ps,
    region: str,
    collect_fn: Callable,
    enrichers: Sequence[InstanceEnricher] = (),
) -> ComboResult:
    result = ComboResult(ps.profile, region, "succeeded")
    try:
        data = collect_fn(ps.ec2(region), ps.account_id)  # no DB writes before this succeeds
        enrichments = _run_enrichers(db, ps.account_id, region, data, enrichers)
        result.instances = load.load_instances(db, ps.account_id, region, data, enrichments)
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        result.status, result.error = _classify(exc), f"{type(exc).__name__}: {exc}"
        result.instances = Counts()
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
    enrichers: Sequence[InstanceEnricher] = (),
    progress=sys.stderr,
) -> RunResult:
    """Scrape every profile/region combination into the `instance` table."""
    result = RunResult("failed")
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
            combo = _scrape_combo(db, ps, region, collect_fn, enrichers)
            result.combos.append(combo)
            print(f"{profile}/{region}: {combo.status}", file=progress)
    result.status = _run_status(result.combos)
    return result
