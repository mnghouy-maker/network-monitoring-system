"""JWT token schemas."""

from pydantic import BaseModel


class Token(BaseModel):
    """OAuth2-style token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    """Decoded JWT claims we care about."""

    sub: str | None = None
    type: str | None = None


class TokenRefreshRequest(BaseModel):
    """Body for the refresh-token endpoint."""

    refresh_token: str
