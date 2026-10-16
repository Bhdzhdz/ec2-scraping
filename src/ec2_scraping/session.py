"""SSO profile sessions: validity check, account id, regions."""

import boto3
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    SSOTokenLoadError,
    TokenRetrievalError,
    UnauthorizedSSOTokenError,
)

CLIENT_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 10})
_EXPIRED_CODES = {"ExpiredToken", "ExpiredTokenException"}


class SsoLoginRequired(Exception):
    """The profile's SSO session is missing or expired."""

    def __init__(self, profile: str):
        self.profile = profile
        super().__init__(
            f"SSO session invalid for profile '{profile}': run `aws sso login --profile {profile}`"
        )


class ProfileSession:
    """A validated boto3 session plus the resolved account id."""

    def __init__(self, profile: str, boto_session, account_id: str):
        self.profile = profile
        self.boto = boto_session
        self.account_id = account_id

    @property
    def default_region(self) -> str | None:
        return self.boto.region_name

    def ec2(self, region: str):
        return self.boto.client("ec2", region_name=region, config=CLIENT_CONFIG)


def open_session(profile: str, session_factory=boto3.Session) -> ProfileSession:
    """Create a session for ``profile`` and resolve its account id (read-only STS call)."""
    try:
        boto_session = session_factory(profile_name=profile)
        sts = boto_session.client("sts", config=CLIENT_CONFIG)
        account_id = sts.get_caller_identity()["Account"]
    except (SSOTokenLoadError, UnauthorizedSSOTokenError, TokenRetrievalError) as exc:
        raise SsoLoginRequired(profile) from exc
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in _EXPIRED_CODES:
            raise SsoLoginRequired(profile) from exc
        raise
    return ProfileSession(profile, boto_session, account_id)


def resolve_regions(
    session: ProfileSession, regions: list[str] | None, all_regions: bool
) -> list[str]:
    """Regions to scrape: explicit list, all enabled regions, or the profile default."""
    if all_regions:
        resp = session.ec2(session.default_region or "us-east-1").describe_regions(AllRegions=False)
        return sorted(r["RegionName"] for r in resp["Regions"])
    if regions:
        return list(dict.fromkeys(regions))
    return [session.default_region] if session.default_region else []
