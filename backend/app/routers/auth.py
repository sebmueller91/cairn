from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.auth import SESSION_COOKIE, Scope, _scope_for_token, get_scope

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Without an explicit max_age/expires this was a pure browser-session
# cookie — fine on a normal desktop tab, but the iOS home-screen PWA's
# webview gets evicted from memory far more readily than a real Safari
# tab, which drops session-only cookies and leaves the SPA rendering from
# a cached TanStack Query scope while every card 401s underneath it. 400
# days is the practical ceiling browsers honor (Chrome caps Max-Age at
# 400 days and silently clamps anything longer) — there is no shorter
# "sensible" value for a single-user LAN app with no session-fixation
# exposure worth trading UX for.
SESSION_COOKIE_MAX_AGE_SECONDS = 400 * 24 * 3600


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="strict",
        secure=True,
        path="/",
        max_age=SESSION_COOKIE_MAX_AGE_SECONDS,
    )


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
    _set_session_cookie(response, body.token)
    return {"scope": scope}


@router.get("/me")
def get_session(scope: Scope = Depends(get_scope)) -> dict:
    # The cookie is HttpOnly (deliberately, ADR 0011) so the frontend has
    # no other way to tell "already signed in" from "needs the login
    # form" on a fresh page load without probing a real data endpoint.
    return {"scope": scope}


@router.post("/logout")
def logout(response: Response) -> dict:
    # delete_cookie's own defaults (samesite="lax", secure=False) don't
    # match the cookie set_cookie above actually wrote — a browser matches
    # a Set-Cookie clear by name+path+domain, not by attributes, so this
    # mismatch has always "worked" by accident. Passing the same attributes
    # keeps that from silently drifting into a cookie the browser refuses
    # to clear (e.g. if Secure/SameSite scoping ever gets stricter).
    response.delete_cookie(
        key=SESSION_COOKIE,
        httponly=True,
        samesite="strict",
        secure=True,
        path="/",
    )
    return {"ok": True}
