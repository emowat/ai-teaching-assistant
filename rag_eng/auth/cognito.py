"""Cognito access-token verification using JWKS."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException, status
from jose import JWTError, jwt

from rag_eng.auth.models import CurrentUser
from rag_eng.config import Settings

_JWKS_CACHE: dict[str, Any] | None = None

# Cognito group name -> internal role (see application_login_management_plan.md)
_GROUP_ROLE_MAP: dict[str, str] = {
    "Admins": "admin",
    "Professors": "professor",
    "Students": "student",
}


def _fetch_jwks(jwks_url: str) -> dict[str, Any]:
    global _JWKS_CACHE
    if _JWKS_CACHE is None:
        response = httpx.get(jwks_url, timeout=10.0)
        response.raise_for_status()
        _JWKS_CACHE = response.json()
    return _JWKS_CACHE


def clear_jwks_cache() -> None:
    """Clear cached JWKS (useful in tests)."""
    global _JWKS_CACHE
    _JWKS_CACHE = None


def _resolve_primary_role(groups: list[str]) -> str | None:
    for group in groups:
        role = _GROUP_ROLE_MAP.get(group)
        if role:
            return role
    return None


def _claims_to_user(claims: dict[str, Any]) -> CurrentUser:
    groups = claims.get("cognito:groups") or []
    if isinstance(groups, str):
        groups = [groups]

    return CurrentUser(
        cognito_sub=str(claims["sub"]),
        email=claims.get("email"),
        username=claims.get("username") or claims.get("cognito:username"),
        groups=list(groups),
        primary_role=_resolve_primary_role(list(groups)),
    )


def verify_cognito_access_token(token: str, settings: Settings) -> CurrentUser:
    """Validate a Cognito access token and return the current user."""
    if not settings.cognito_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cognito is not configured on this server.",
        )

    issuer = settings.cognito_issuer
    jwks_url = settings.cognito_jwks_url
    client_id = settings.cognito_app_client_id
    if not issuer or not jwks_url or not client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cognito configuration is incomplete.",
        )

    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            raise JWTError("Token header missing kid.")

        jwks = _fetch_jwks(jwks_url)
        key = next((item for item in jwks.get("keys", []) if item.get("kid") == kid), None)
        if key is None:
            clear_jwks_cache()
            jwks = _fetch_jwks(jwks_url)
            key = next((item for item in jwks.get("keys", []) if item.get("kid") == kid), None)
        if key is None:
            raise JWTError("No matching JWKS key for token kid.")

        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=issuer,
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to fetch Cognito JWKS.",
        ) from exc

    if claims.get("token_use") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token must be an access token.",
        )

    if claims.get("client_id") != client_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token was not issued for this application.",
        )

    return _claims_to_user(claims)
