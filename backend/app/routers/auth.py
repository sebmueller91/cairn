from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.auth import SESSION_COOKIE, Scope, _scope_for_token, get_scope

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SessionRequest(BaseModel):
    token: str


@router.post("/session")
def create_session(body: SessionRequest, response: Response) -> dict:
    scope = _scope_for_token(body.token)
    if scope is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_token", "params": {}},
        )
    response.set_cookie(
        key=SESSION_COOKIE,
        value=body.token,
        httponly=True,
        samesite="strict",
        secure=True,
    )
    return {"scope": scope}


@router.get("/me")
def get_session(scope: Scope = Depends(get_scope)) -> dict:
    # The cookie is HttpOnly (deliberately, ADR 0011) so the frontend has
    # no other way to tell "already signed in" from "needs the login
    # form" on a fresh page load without probing a real data endpoint.
    return {"scope": scope}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(key=SESSION_COOKIE)
    return {"ok": True}
