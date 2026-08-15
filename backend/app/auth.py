from typing import Literal

from fastapi import Cookie, Depends, Header, HTTPException, status

from app.config import get_settings

Scope = Literal["read_only", "full"]

SESSION_COOKIE = "cairn_session"


def _scope_for_token(token: str) -> Scope | None:
    settings = get_settings()
    if token == settings.api_token:
        return "full"
    if settings.api_token_readonly and token == settings.api_token_readonly:
        return "read_only"
    return None


def _extract_token(
    authorization: str | None, session_cookie: str | None
) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return session_cookie


def get_scope(
    authorization: str | None = Header(default=None),
    cairn_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> Scope:
    token = _extract_token(authorization, cairn_session)
    scope = _scope_for_token(token) if token else None
    if scope is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "params": {}},
        )
    return scope


def require_write_scope(scope: Scope = Depends(get_scope)) -> Scope:
    if scope != "full":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "read_only_token", "params": {}},
        )
    return scope
