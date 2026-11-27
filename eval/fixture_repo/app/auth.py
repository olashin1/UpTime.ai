import jwt
from fastapi import APIRouter, Depends, Header, HTTPException

from app.config import settings
from app.db import get_session
from app.models import User
from app.rate_limit import limit

router = APIRouter()


@router.post("/login")
@limit("10/minute", key="ip")
def login(body: dict):
    with get_session() as session:
        user = User.by_email(session, body.get("email", ""))
        if user is None or not user.check_password(body.get("password", "")):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        return {"token": user.issue_token()}


def verify_token(token: str) -> dict:
    # Every authenticated request goes through here.
    return jwt.decode(token, settings.jwt_public_key, algorithms=["RS256"])


def get_current_user(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    claims = verify_token(authorization.removeprefix("Bearer "))
    with get_session() as session:
        return User.get(session, claims["sub"])


def require_staff(user=Depends(get_current_user)):
    if not user.is_staff:
        raise HTTPException(status_code=403, detail="Staff only")
    return user
