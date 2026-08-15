from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from app.auth import SESSION_COOKIE, _scope_for_token

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
