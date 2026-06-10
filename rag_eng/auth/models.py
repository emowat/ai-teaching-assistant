"""Auth response models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CurrentUser(BaseModel):
    """Authenticated user derived from a validated Cognito access token."""

    cognito_sub: str
    email: str | None = None
    username: str | None = None
    groups: list[str] = Field(default_factory=list)
    primary_role: str | None = None


class MeResponse(BaseModel):
    """Public profile returned by GET /me."""

    cognito_sub: str
    email: str | None = None
    username: str | None = None
    groups: list[str] = Field(default_factory=list)
    primary_role: str | None = None

    @classmethod
    def from_current_user(cls, user: CurrentUser) -> MeResponse:
        return cls(
            cognito_sub=user.cognito_sub,
            email=user.email,
            username=user.username,
            groups=user.groups,
            primary_role=user.primary_role,
        )
