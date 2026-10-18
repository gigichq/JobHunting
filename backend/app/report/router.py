"""reports 路由（02-技术设计 §7/§10）。"""
import urllib.parse
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics import track
from ..auth.security import get_current_user
from ..config import get_settings
from ..database import get_db
from ..models import Correction, DiagSession, Report, User, utcnow
from . import pipeline

router = APIRouter(prefix="/api/reports")

STAGE_TEXT = {
    "extracting": "正在从对话中提取事实…",
    "verifying": "正在逐条核验证据与原话…",
    "scoring": "七个维度并行评分中…",
    "concluding": "正在提炼结构性结论…",
    "composing": "正在撰写报告正文…",
    "rendering": "正在排版生成报告…",
}


def _get_owned_report(db: Session, report_id: str, user: User) -> tuple[Report, DiagSession]:
    report = db.get(Report, report_id)
    if not report or report.status == "deleted":
        raise HTTPException(404, "报告不存在")
    session = db.get(DiagSession, report.session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(404, "报告不存在")
    return report, session


def _report_brief(r: Report, s: DiagSession) -> dict:
    return {
        "id": r.id,
        "session_id": r.session_id,
        "status": r.status,
        "progress_stage": r.progress_stage,
        "progress_text": STAGE_TEXT.get(r.progress_stage or "", ""),
        "version": r.version,
        "quote_hit_rate": r.quote_hit_rate,
        "error": r.error,
        "can_retry": pipeline.can_user_retry(r),
        "mode": s.mode,
        "identity": s.identity,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.get("")
def list_reports(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sessions = {
        s.id: s
        for s in db.scalars(select(DiagSession).where(DiagSession.user_id == user.id)).all()
    }
    if not sessions:
        return []
    reports = db.scalars(
        select(Report)
        .where(Report.session_id.in_(list(sessions)), Report.status != "deleted")
        .order_by(Report.created_at.desc())
    ).all()
    return [_report_brief(r, sessions[r.session_id]) for r in reports]


@router.get("/{report_id}/status")
def report_status(
    report_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    report, session = _get_owned_report(db, report_id, user)
    pipeline.lazy_timeout_check(db, report)
    db.refresh(report)
    return _report_brief(report, session)


@router.post("/{report_id}/retry")
def retry_report(
    report_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """失败/超时后一键重试：原子接管（CAS 置换 run_id），从 stages_json 断点续跑。"""
    settings = get_settings()
    report, session = _get_owned_report(db, report_id, user)
    if report.status == "ready":
        return _report_brief(report, session)  # 幂等：已就绪不重跑
    if not pipeline.can_user_retry(report):
        raise HTTPException(409, "报告正在生成中，请稍候（超过 5 分钟后可重试）")

    report.retry_count += 1
    if report.retry_count > settings.report_max_retries:
        # 累计重试超限 → 降级简版交付（不再调模型）
        pipeline.build_degraded_delivery(db, report)
        track("report_degraded", user_id=user.id, session_id=session.id, db=db)
        return _report_brief(report, session)

    report.run_id = uuid.uuid4().hex  # CAS 接管：旧 run 回写前校验 run_id 即失效
    report.status = "generating"
    report.heartbeat_at = utcnow()
    report.started_at = utcnow()
    report.error = None
    db.commit()
    track("report_retry", user_id=user.id, session_id=session.id, props={"retry_count": report.retry_count}, db=db)
    background_tasks.add_task(pipeline.run_pipeline_task, report.id, report.run_id)
    return _report_brief(report, session)


class CorrectionIn(BaseModel):
    quote_or_fact: str = Field(min_length=1, max_length=1000)
    comment: str = Field(min_length=1, max_length=1000)


@router.post("/{report_id}/correction")
def submit_correction(
    report_id: str,
    body: CorrectionIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report, session = _get_owned_report(db, report_id, user)
    row = Correction(
        report_id=report.id,
        user_id=user.id,
        quote_or_fact=body.quote_or_fact,
        comment=body.comment,
    )
    db.add(row)
    db.commit()
    track("report_correction", user_id=user.id, session_id=session.id, db=db)
    return {"id": row.id, "status": row.status, "sla": "我们会在 72 小时内对照对话原文人工核实并回复"}


@router.get("/{report_id}/corrections")
def list_corrections(
    report_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    _get_owned_report(db, report_id, user)
    rows = db.scalars(
        select(Correction)
        .where(Correction.report_id == report_id)
        .order_by(Correction.created_at.desc())
    ).all()
    return [
        {
            "id": c.id,
            "quote_or_fact": c.quote_or_fact,
            "comment": c.comment,
            "status": c.status,
            "created_at": c.created_at.isoformat(),
        }
        for c in rows
    ]


class FeedbackIn(BaseModel):
    helpful: bool
    actionable: bool
    comment: str | None = Field(default=None, max_length=500)


@router.post("/{report_id}/feedback")
def submit_feedback(
    report_id: str,
    body: FeedbackIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report, session = _get_owned_report(db, report_id, user)
    track(
        "report_feedback",
        user_id=user.id,
        session_id=session.id,
        props={"helpful": body.helpful, "actionable": body.actionable, "comment": body.comment},
        db=db,
    )
    return {"ok": True}


@router.get("/{report_id}/html")
def report_html(
    report_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    report, _ = _get_owned_report(db, report_id, user)
    if not report.html:
        raise HTTPException(409, "报告尚未生成完成")
    return Response(
        content=report.html,
        media_type="text/html; charset=utf-8",
        headers={"X-Robots-Tag": "noindex"},
    )


@router.get("/{report_id}/download")
def report_download(
    report_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    report, session = _get_owned_report(db, report_id, user)
    if not report.html:
        raise HTTPException(409, "报告尚未生成完成")
    u = db.get(User, session.user_id)
    date = report.updated_at.strftime("%Y%m%d") if report.updated_at else ""
    filename = f"求职准备度诊断报告-{u.display_name}-{date}.html"
    quoted = urllib.parse.quote(filename)
    track("report_download", user_id=user.id, session_id=session.id, db=db)
    return Response(
        content=report.html,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
            "X-Robots-Tag": "noindex",
        },
    )
