"""FastAPI dependencies for Cognito authentication."""

from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from rag_eng.auth.cognito import verify_cognito_access_token
from rag_eng.auth.models import CurrentUser
from rag_eng.config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)


def require_authenticated_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    """Require a valid Cognito access token."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer access token.",
        )

    return verify_cognito_access_token(credentials.credentials, settings)


def require_role(*allowed_roles: str) -> Callable[..., CurrentUser]:
    """Require the authenticated user to have one of the given primary roles."""

    def _dependency(
        current_user: CurrentUser = Depends(require_authenticated_user),
    ) -> CurrentUser:
        if current_user.primary_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role for this operation.",
            )
        return current_user

    return _dependency
