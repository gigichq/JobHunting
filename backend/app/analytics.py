"""事件埋点：后端直写 + 前端 /api/events 上报（02-技术设计 §7/§13）。"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .auth.security import get_current_user_optional
from .database import SessionLocal, get_db
from .models import Event, User

router = APIRouter()

# 前端允许上报的事件白名单（防任意写入）
FRONTEND_EVENTS = {
    "landing_view",
    "register_view",
    "report_view",
    "report_download",
    "session_pause",
    "session_resume",
    "share_card_view",
}


def track(
    event: str,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    props: dict | None = None,
    db: Session | None = None,
) -> None:
    """后端直写事件。db 为 None 时自开短会话（供 pipeline 等无请求上下文处调用）。"""
    row = Event(
        user_id=user_id,
        session_id=session_id,
        event=event,
        props_json=Event.dumps(props or {}),
    )
    if db is not None:
        db.add(row)
        db.commit()
        return
    own = SessionLocal()
    try:
        own.add(row)
        own.commit()
    finally:
        own.close()


class EventIn(BaseModel):
    event: str
    session_id: str | None = None
    props: dict = {}


@router.post("/api/events")
def post_event(
    body: EventIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if body.event not in FRONTEND_EVENTS:
        return {"ok": False}
    track(
        body.event,
        user_id=user.id if user else None,
        session_id=body.session_id,
        props=body.props,
        db=db,
    )
    return {"ok": True}
