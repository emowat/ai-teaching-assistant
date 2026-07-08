from __future__ import annotations

import functools
import os

import pytest
import requests
from dotenv import load_dotenv


load_dotenv()


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_COGNITO_AUTH_SMOKE", "").strip().lower()
    not in {"1", "true", "yes", "on"},
    reason="Live Cognito auth smoke is opt-in via RUN_LIVE_COGNITO_AUTH_SMOKE=1.",
)


def _live_base_url() -> str:
    return os.getenv("LIVE_CHAT_API_BASE_URL", "http://127.0.0.1:8001").rstrip("/")


@functools.lru_cache(maxsize=1)
def _mint_cognito_access_token() -> str:
    boto3 = pytest.importorskip("boto3")

    username = os.getenv("LIVE_COGNITO_TEST_USERNAME", "").strip()
    password = os.getenv("LIVE_COGNITO_TEST_PASSWORD", "").strip()
    client_id = os.getenv("COGNITO_APP_CLIENT_ID", "").strip()
    region = (
        os.getenv("AWS_REGION", "").strip()
        or os.getenv("AWS_DEFAULT_REGION", "").strip()
        or os.getenv("COGNITO_REGION", "").strip()
    )
    profile_name = os.getenv("AWS_PROFILE", "").strip() or None

    if not username or not password:
        pytest.skip(
            "Set LIVE_COGNITO_TEST_USERNAME and LIVE_COGNITO_TEST_PASSWORD to run the live Cognito auth smoke test."
        )
    if not client_id or not region:
        pytest.skip(
            "Set COGNITO_APP_CLIENT_ID and COGNITO_REGION to run the live Cognito auth smoke test."
        )

    session = boto3.Session(profile_name=profile_name, region_name=region)
    client = session.client("cognito-idp")
    response = client.initiate_auth(
        ClientId=client_id,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": username,
            "PASSWORD": password,
        },
    )
    token = response["AuthenticationResult"]["AccessToken"]
    if not token:
        raise AssertionError("Cognito did not return an access token.")
    return token


def test_live_cognito_access_token_allows_me_endpoint() -> None:
    token = _mint_cognito_access_token()
    response = requests.get(
        f"{_live_base_url()}/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["primary_role"] == "student"
    assert body["email"] == os.getenv("LIVE_COGNITO_TEST_USERNAME")
    assert body["username"]
    assert "Students" in body["groups"]
    assert body["cognito_sub"]
