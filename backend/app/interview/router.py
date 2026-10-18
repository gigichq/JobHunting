"""sessions 路由（02-技术设计 §7）。"""
from datetime import datetime, time, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..analytics import track
from ..auth.security import get_current_user
from ..config import get_settings
from ..database import get_db
from ..models import DiagSession, Message, Report, User, utcnow
from ..report import pipeline as report_pipeline
from . import orchestrator, prompts

router = APIRouter(prefix="/api/sessions")


class SessionCreate(BaseModel):
    mode: Literal["quick", "full"]
    identity: Literal["student", "professional"]
    identity_detail: str | None = Field(default=None, max_length=32)
    goal_clear: bool
    target_role: str | None = Field(default=None, max_length=64)
    target_city: str | None = Field(default=None, max_length=32)
    employment_status: str | None = Field(default=None, max_length=32)
    salary_floor: str | None = Field(default=None, max_length=32)  # 仅存 profile，不进对话


class MessageIn(BaseModel):
    content: str = Field(min_length=1)
    resumed: bool = False


def _get_owned_session(db: Session, session_id: str, user: User) -> DiagSession:
    s = db.get(DiagSession, session_id)
    if not s or s.user_id != user.id:
        raise HTTPException(404, "诊断不存在")
    return s


@router.post("")
async def create_session(
    body: SessionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    today_start = datetime.combine(
        datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc
    )
    today_count = db.scalar(
        select(func.count(DiagSession.id)).where(
            DiagSession.user_id == user.id, DiagSession.created_at >= today_start
        )
    )
    if today_count >= settings.daily_session_limit:
        raise HTTPException(429, f"每天最多新建 {settings.daily_session_limit} 次诊断，明天再来吧")

    if body.goal_clear and not body.target_role:
        raise HTTPException(400, "目标明确时请填写目标岗位")

    profile = body.model_dump()
    session = DiagSession(
        user_id=user.id,
        mode=body.mode,
        identity=body.identity,
        profile_json=DiagSession.dumps(profile),
        coverage_json=DiagSession.dumps(orchestrator.init_coverage()),
    )
    db.add(session)
    db.flush()
    opening = prompts.opening_message(profile, body.mode)
    db.add(
        Message(session_id=session.id, seq=1, role="assistant", content=opening)
    )
    db.commit()
    track(
        "session_start",
        user_id=user.id,
        session_id=session.id,
        props={"mode": body.mode, "identity": body.identity, "goal_clear": body.goal_clear},
        db=db,
    )
    cov = session.coverage
    return {
        "id": session.id,
        "mode": session.mode,
        "identity": session.identity,
        "status": session.status,
        "opening_message": opening,
        "progress": orchestrator.progress_payload(cov),
    }


@router.get("")
def list_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(DiagSession)
        .where(DiagSession.user_id == user.id)
        .order_by(DiagSession.created_at.desc())
    ).all()
    report_map = {
        r.session_id: r
        for r in db.scalars(
            select(Report).where(Report.session_id.in_([s.id for s in rows]))
        ).all()
    }
    out = []
    for s in rows:
        r = report_map.get(s.id)
        out.append(
            {
                "id": s.id,
                "mode": s.mode,
                "identity": s.identity,
                "status": s.status,
                "turn_count": s.turn_count,
                "created_at": s.created_at.isoformat(),
                "report_id": r.id if r and r.status != "deleted" else None,
                "report_status": r.status if r and r.status != "deleted" else None,
            }
        )
    return out


@router.get("/{session_id}")
def get_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = _get_owned_session(db, session_id, user)
    msgs = db.scalars(
        select(Message).where(Message.session_id == s.id).order_by(Message.seq)
    ).all()
    report = db.scalar(select(Report).where(Report.session_id == s.id))
    return {
        "id": s.id,
        "mode": s.mode,
        "identity": s.identity,
        "status": s.status,
        "messages": [
            {"seq": m.seq, "role": m.role, "content": m.content} for m in msgs
        ],
        "progress": orchestrator.progress_payload(s.coverage or orchestrator.init_coverage()),
        "report_id": report.id if report and report.status != "deleted" else None,
    }


@router.delete("/{session_id}")
def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = _get_owned_session(db, session_id, user)
    report = db.scalar(select(Report).where(Report.session_id == s.id))
    if report:
        report_pipeline.mark_report_deleted(db, report)
    db.execute(delete(Message).where(Message.session_id == s.id))
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.post("/{session_id}/messages")
async def post_message(
    session_id: str,
    body: MessageIn,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    s = _get_owned_session(db, session_id, user)
    if s.status not in {"active", "wrapping"}:
        raise HTTPException(409, "该诊断已结束")
    if len(body.content) > settings.max_message_chars:
        raise HTTPException(
            400,
            f"单条消息最长 {settings.max_message_chars} 字。内容较长时可以分段发送；"
            "如果是简历或 JD，建议分块粘贴，我会逐项和你确认。",
        )
    result = await orchestrator.handle_user_message(
        db, s, body.content, resumed=body.resumed
    )
    if result["ended"]:
        report, started = report_pipeline.ensure_report(db, s)
        if started:
            background_tasks.add_task(
                report_pipeline.run_pipeline_task, report.id, report.run_id
            )
        result["report_id"] = report.id
    return result


@router.post("/{session_id}/end")
def end_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """用户主动结束：立即确认并触发生成（不受最低覆盖限制，走部分报告）。"""
    s = _get_owned_session(db, session_id, user)
    if s.status not in {"active", "wrapping", "ended"}:
        raise HTTPException(409, "该诊断已结束")
    if s.status != "ended":
        closing = (
            "好的，我们就聊到这里。基于目前的对话我马上为你生成诊断报告——"
            "没覆盖到的维度会标注「待核实」，不会乱打分。通常 2–3 分钟就好。"
        )
        db.add(
            Message(
                session_id=s.id,
                seq=orchestrator.next_seq(db, s.id),
                role="assistant",
                content=closing,
            )
        )
        s.status = "ended"
        s.ended_at = utcnow()
        db.commit()
        cov = s.coverage or orchestrator.init_coverage()
        track(
            "session_end",
            user_id=user.id,
            session_id=s.id,
            props={"reason": "user_quit", "turns": orchestrator.total_questions(cov)},
            db=db,
        )
    report, started = report_pipeline.ensure_report(db, s)
    if started:
        background_tasks.add_task(
            report_pipeline.run_pipeline_task, report.id, report.run_id
        )
    return {"ok": True, "report_id": report.id}
