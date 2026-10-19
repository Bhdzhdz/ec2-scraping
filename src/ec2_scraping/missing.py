"""Resources not seen in the latest successful run of their (account, region) scope."""

from sqlalchemy import func, literal, or_, select
from sqlalchemy.orm import Session

from ec2_scraping.db.models import Account, Ami, Instance, Region, ScrapeRunScope


def find_missing(
    db: Session,
    account_ids: list[str] | None = None,
    regions: list[str] | None = None,
) -> list[dict]:
    """Return dict rows (kind, aws_account_id, region, resource_id, last_seen_at)."""
    latest = (
        select(
            ScrapeRunScope.account_id,
            ScrapeRunScope.region_id,
            func.max(ScrapeRunScope.scrape_run_id).label("run_id"),
        )
        .where(ScrapeRunScope.status == "succeeded")
        .group_by(ScrapeRunScope.account_id, ScrapeRunScope.region_id)
        .subquery("latest")
    )

    rows: list[dict] = []
    for kind, model, id_col in (
        ("instance", Instance, Instance.instance_id),
        ("ami", Ami, Ami.image_id),
    ):
        stmt = (
            select(
                literal(kind).label("kind"),
                Account.aws_account_id,
                Region.code.label("region"),
                id_col.label("resource_id"),
                model.last_seen_at,
            )
            .join(
                latest,
                (latest.c.account_id == model.account_id) & (latest.c.region_id == model.region_id),
            )
            .join(Account, Account.id == model.account_id)
            .join(Region, Region.id == model.region_id)
            .where(
                or_(
                    model.last_scrape_run_id.is_(None),
                    model.last_scrape_run_id < latest.c.run_id,
                )
            )
        )
        if account_ids:
            stmt = stmt.where(Account.aws_account_id.in_(account_ids))
        if regions:
            stmt = stmt.where(Region.code.in_(regions))
        stmt = stmt.order_by(Account.aws_account_id, Region.code, id_col)
        rows.extend(dict(r._mapping) for r in db.execute(stmt).all())
    return rows
