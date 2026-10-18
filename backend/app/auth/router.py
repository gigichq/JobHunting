"""注册/登录/登出/me/账号删除（02-技术设计 §7/§12）。"""
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..analytics import track
from ..models import (
    Correction,
    DiagSession,
    Event,
    Message,
    Report,
    ReportVersion,
    User,
    utcnow,
)
from ..database import get_db
from .security import (
    clear_auth_cookie,
    get_current_user,
    hash_password,
    issue_token,
    set_auth_cookie,
    verify_password,
)

router = APIRouter(prefix="/api/auth")

# 注册按 IP 简单限频：每 IP 每小时 10 次
_register_hits: dict[str, deque] = defaultdict(deque)
_REGISTER_LIMIT, _REGISTER_WINDOW = 10, 3600


def _rate_limit_register(ip: str) -> bool:
    now = time.time()
    hits = _register_hits[ip]
    while hits and now - hits[0] > _REGISTER_WINDOW:
        hits.popleft()
    if len(hits) >= _REGISTER_LIMIT:
        return False
    hits.append(now)
    return True


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    display_name: str = Field(min_length=1, max_length=32)
    age_confirmed: bool


class LoginIn(BaseModel):
    email: EmailStr
    password: str


def _user_out(user: User) -> dict:
    return {"id": user.id, "email": user.email, "display_name": user.display_name}


@router.post("/register")
def register(
    body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)
):
    if not body.age_confirmed:
        raise HTTPException(400, "本服务仅面向年满 18 周岁的用户")
    ip = request.client.host if request.client else "unknown"
    if not _rate_limit_register(ip):
        raise HTTPException(429, "注册过于频繁，请稍后再试")
    exists = db.scalar(select(User).where(User.email == body.email.lower()))
    if exists:
        raise HTTPException(409, "该邮箱已注册，请直接登录")
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        display_name=body.display_name.strip(),
        age_confirmed_at=utcnow(),
    )
    db.add(user)
    db.commit()
    set_auth_cookie(response, issue_token(user.id))
    track("register", user_id=user.id, db=db)
    return _user_out(user)


@router.post("/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "邮箱或密码不正确")
    set_auth_cookie(response, issue_token(user.id))
    return _user_out(user)


@router.post("/logout")
def logout(response: Response):
    clear_auth_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return _user_out(user)


@router.delete("/me")
def delete_me(
    response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """账号删除：级联会话/消息/报告/纠错，events 匿名化；运行中任务通过 deleted 状态终止。"""
    session_ids = db.scalars(
        select(DiagSession.id).where(DiagSession.user_id == user.id)
    ).all()
    if session_ids:
        report_ids = db.scalars(
            select(Report.id).where(Report.session_id.in_(session_ids))
        ).all()
        if report_ids:
            db.execute(delete(Correction).where(Correction.report_id.in_(report_ids)))
            db.execute(
                delete(ReportVersion).where(ReportVersion.report_id.in_(report_ids))
            )
            # 置 deleted：运行中的 pipeline 每次模型调用前校验，发现即终止且不回写
            db.execute(
                update(Report)
                .where(Report.id.in_(report_ids))
                .values(status="deleted", html=None, report_json=None, stages_json=None)
            )
        db.execute(delete(Message).where(Message.session_id.in_(session_ids)))
        db.execute(delete(DiagSession).where(DiagSession.id.in_(session_ids)))
    db.execute(
        update(Event).where(Event.user_id == user.id).values(user_id=None)
    )
    db.delete(user)
    db.commit()
    clear_auth_cookie(response)
    return {"ok": True}
