"""SSO session handling: account resolution and expired-login mapping."""

import pytest
from botocore.exceptions import (
    ClientError,
    SSOTokenLoadError,
    TokenRetrievalError,
    UnauthorizedSSOTokenError,
)

from ec2_scraping.session import SsoLoginRequired, open_session


class FakeSession:
    region_name = "us-east-1"

    def __init__(self, outcome):
        self.outcome = outcome

    def client(self, name, **_):
        outcome = self.outcome

        class Sts:
            def get_caller_identity(self):
                if isinstance(outcome, Exception):
                    raise outcome
                return {"Account": outcome}

        return Sts()


def _factory(outcome):
    return lambda profile_name: FakeSession(outcome)


def test_valid_profile_returns_account_id():
    ps = open_session("dev", _factory("123456789012"))
    assert ps.account_id == "123456789012"
    assert ps.profile == "dev"


@pytest.mark.parametrize(
    "error",
    [
        SSOTokenLoadError(error_msg="x"),
        UnauthorizedSSOTokenError(),
        TokenRetrievalError(provider="sso", error_msg="x"),
        ClientError({"Error": {"Code": "ExpiredToken", "Message": "x"}}, "GetCallerIdentity"),
    ],
)
def test_expired_login_names_the_profile(error):
    with pytest.raises(SsoLoginRequired) as info:
        open_session("dev", _factory(error))
    assert "aws sso login --profile dev" in str(info.value)
    assert info.value.profile == "dev"


def test_other_client_errors_propagate():
    error = ClientError({"Error": {"Code": "AccessDenied", "Message": "x"}}, "GetCallerIdentity")
    with pytest.raises(ClientError):
        open_session("dev", _factory(error))
