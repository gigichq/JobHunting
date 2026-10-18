"""密码哈希、JWT 签发校验、当前用户依赖（02-技术设计 §12）。"""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Cookie, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import User

COOKIE_NAME = "jh_token"
TOKEN_DAYS = 7


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def issue_token(user_id: str) -> str:
    settings = get_settings()
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=TOKEN_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.effective_jwt_secret, algorithm="HS256")


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=TOKEN_DAYS * 86400,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def _decode(token: str) -> str | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.effective_jwt_secret, algorithms=["HS256"])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def get_current_user_optional(
    jh_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User | None:
    if not jh_token:
        return None
    user_id = _decode(jh_token)
    if not user_id:
        return None
    return db.get(User, user_id)


def get_current_user(
    user: User | None = Depends(get_current_user_optional),
) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return user
