"""Scrape lifecycle with per-combination isolation, pluggable enrichers, and atomic loads."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from botocore.exceptions import ClientError, EndpointConnectionError

from ec2_scraping import collect as collect_mod
from ec2_scraping import load, session
from ec2_scraping.models import (
    ComboResult,
    Counts,
    EnrichmentResult,
    RunResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from typing import IO

    from sqlalchemy.orm import Session

    from ec2_scraping.models import (
        Collected,
        InstanceEnricher,
        InstanceRecord,
    )

# Errors meaning "this region is not usable for the account" (stored as skipped).
_DISABLED_CODES = {"AuthFailure", "OptInRequired"}


@dataclass(frozen=True)
class _EnrichJob:
    aws_account_id: str
    region: str
    targets: list[InstanceRecord]
    ami_names: dict[str, str | None]
    batch_kwargs: dict[str, Any]


def _classify(exc: Exception) -> str:
    if isinstance(exc, EndpointConnectionError):
        return "skipped"
    if (
        isinstance(exc, ClientError)
        and exc.response.get("Error", {}).get("Code") in _DISABLED_CODES
    ):
        return "skipped"
    return "failed"


def _filter_unaccessed_ssh(
    db: Session,
    aws_account_id: str,
    region: str,
    instances: list[InstanceRecord],
) -> list[InstanceRecord]:
    inst_ids = [i.instance_id for i in instances]
    already_accessed = load.get_accessed_ssh_instance_ids(db, aws_account_id, region, inst_ids)
    return [i for i in instances if i.instance_id not in already_accessed]


def _ssh_targets_and_users(
    db: Session,
    aws_account_id: str,
    region: str,
    instances: list[InstanceRecord],
    *,
    only_unaccessed: bool,
) -> tuple[list[InstanceRecord], dict[str, str], dict[str, str]]:
    if only_unaccessed:
        targets = _filter_unaccessed_ssh(db, aws_account_id, region, instances)
        known_users: dict[str, str] = {}
    else:
        targets = instances
        inst_ids = [i.instance_id for i in instances]
        known_users = load.get_known_ssh_users(db, aws_account_id, region, inst_ids)
    if not targets:
        return [], {}, {}
    image_ids = list({i.image_id for i in targets if i.image_id})
    known_ami_users = load.get_known_ami_ssh_users(db, image_ids)
    return targets, known_users, known_ami_users


def _store_batch_results(
    name: str,
    batch_res: dict[str, EnrichmentResult],
    results: dict[str, dict[str, EnrichmentResult]],
) -> None:
    for inst_id, res in batch_res.items():
        if inst_id in results:
            results[inst_id][name] = res


def _store_batch_failure(
    name: str,
    targets: list[InstanceRecord],
    err: str,
    results: dict[str, dict[str, EnrichmentResult]],
) -> None:
    for inst in targets:
        results[inst.instance_id][name] = EnrichmentResult(status="failed", error=err)


def _run_batch_enricher(
    enricher: InstanceEnricher,
    job: _EnrichJob,
    results: dict[str, dict[str, EnrichmentResult]],
) -> bool:
    batch_fn = getattr(enricher, "enrich_batch", None)
    if not callable(batch_fn):
        return False
    try:
        batch_res = batch_fn(
            job.aws_account_id, job.region, job.targets, job.ami_names, **job.batch_kwargs
        )
        _store_batch_results(enricher.name, batch_res, results)
    except Exception as exc:
        _store_batch_failure(enricher.name, job.targets, f"{type(exc).__name__}: {exc}", results)
    return True


def _run_single_enricher(
    enricher: InstanceEnricher,
    job: _EnrichJob,
    results: dict[str, dict[str, EnrichmentResult]],
) -> None:
    for inst in job.targets:
        try:
            results[inst.instance_id][enricher.name] = enricher.enrich(
                job.aws_account_id, job.region, inst
            )
        except Exception as exc:
            results[inst.instance_id][enricher.name] = EnrichmentResult(
                status="failed", error=f"{type(exc).__name__}: {exc}"
            )


def _build_enrich_job(
    db: Session,
    aws_account_id: str,
    region: str,
    data: Collected,
    enricher: InstanceEnricher,
) -> _EnrichJob | None:
    ami_names = {k: v.name for k, v in data.amis.items()}
    if enricher.name != "ssh":
        return _EnrichJob(aws_account_id, region, data.instances, ami_names, {})
    targets, known_users, known_ami_users = _ssh_targets_and_users(
        db,
        aws_account_id,
        region,
        data.instances,
        only_unaccessed=bool(getattr(enricher, "only_unaccessed", False)),
    )
    if not targets:
        return None
    batch_kwargs = {"known_users": known_users, "known_ami_users": known_ami_users}
    return _EnrichJob(aws_account_id, region, targets, ami_names, batch_kwargs)


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
    for enricher in enrichers:
        job = _build_enrich_job(db, aws_account_id, region, data, enricher)
        if job and not _run_batch_enricher(enricher, job, results):
            _run_single_enricher(enricher, job, results)
    return results


def _scrape_combo(
    db: Session,
    ps: Any,
    region: str,
    collect_fn: Callable[..., Collected],
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


def _resolve_profile_targets(
    profile: str,
    regions: list[str] | None,
    all_regions: bool,
    open_session: Callable[..., Any],
) -> tuple[Any, list[str], ComboResult | None]:
    try:
        ps = open_session(profile)
        targets = session.resolve_regions(ps, regions, all_regions)
        if not targets:
            msg = "no region given and the profile has no default region"
            raise ValueError(msg)
    except session.SsoLoginRequired as exc:
        return None, [], ComboResult(profile, None, "skipped", str(exc))
    except Exception as exc:
        return None, [], ComboResult(profile, None, "failed", f"{type(exc).__name__}: {exc}")
    return ps, targets, None


def run(
    db: Session,
    profiles: list[str],
    regions: list[str] | None = None,
    all_regions: bool = False,
    **opts: Any,
) -> RunResult:
    """Scrape every profile/region combination into the `instance` table."""
    open_session: Callable[..., Any] = opts.get("open_session", session.open_session)
    collect_fn: Callable[..., Collected] = opts.get("collect_fn", collect_mod.collect)
    enrichers: Sequence[InstanceEnricher] = opts.get("enrichers", ())
    progress: IO[str] = opts.get("progress", sys.stderr)
    result = RunResult("failed")
    for profile in profiles:
        ps, targets, err_combo = _resolve_profile_targets(
            profile, regions, all_regions, open_session
        )
        if err_combo is not None:
            result.combos.append(err_combo)
            continue
        for region in targets:
            combo = _scrape_combo(db, ps, region, collect_fn, enrichers)
            result.combos.append(combo)
            progress.write(f"{profile}/{region}: {combo.status}\n")
    result.status = _run_status(result.combos)
    return result
