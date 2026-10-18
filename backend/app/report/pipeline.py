"""报告生成流水线（02-技术设计 §10）。

trigger(session end) → BackgroundTask(run_id + heartbeat):
  A 事实提取 → A′ 证据校验（代码，先于评分） → B 七维评分(并发)
  → C 结构结论 → D 叙事(×2) → E 组装渲染
状态机: extracting → verifying → scoring → concluding → composing → rendering → ready | failed | degraded
"""
import asyncio
import html as html_lib
import logging
import time
import uuid
from datetime import datetime, timezone

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics import track
from ..config import get_settings
from ..interview.dimensions import BAND_TABLE, DIM_BY_KEY, DIM_KEYS, SCALE_LABELS
from ..llm.client import LLMError, chat_json, redact_pii
from ..models import DiagSession, Message, Report, ReportVersion, User, utcnow
from ..database import SessionLocal
from . import prompts, quote_check, radar
from .schemas import (
    SCOREABLE_SOURCES,
    DimScore,
    StageAOut,
    StageCOut,
    StageD1Out,
    StageD2Out,
)

logger = logging.getLogger(__name__)

import os

_env = Environment(
    loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), "templates")),
    autoescape=select_autoescape(["html", "j2"]),
)

# 黑名单词 → 安全替换（通用 + 社招加严）；渲染测试断言最终 HTML 不含这些词
BLACKLIST_COMMON = {
    "家长": "你",
    "北迹星": "求职陪跑",
    "AstraArc": "CAREER PACER",
    "最刺眼": "最需要先补上",
    "请勿转发": "",
    "仅限内部": "",
}
BLACKLIST_PROFESSIONAL = {"学员": "你", "同学": "", "在校": ""}


class PipelineAborted(Exception):
    """运行被接管/删除/超时，静默退出不回写。"""


# ---------------------------------------------------------------- 任务管理


def ensure_report(db: Session, session: DiagSession) -> tuple[Report, bool]:
    """幂等获取/创建报告行。返回 (report, started)——started 为 True 才需要调度新任务。"""
    report = db.scalar(select(Report).where(Report.session_id == session.id))
    if report is None:
        report = Report(session_id=session.id)
        db.add(report)
        db.flush()
    if report.status in {"ready", "deleted"}:
        return report, False
    if report.status == "generating" and _heartbeat_fresh(report):
        return report, False  # 已有活跃 run，不重复启动
    report.run_id = uuid.uuid4().hex
    report.status = "generating"
    report.progress_stage = report.progress_stage or "extracting"
    report.heartbeat_at = utcnow()
    report.started_at = utcnow()
    report.error = None
    db.commit()
    session.status = "generating"
    db.commit()
    return report, True


def _heartbeat_fresh(report: Report) -> bool:
    settings = get_settings()
    if not report.heartbeat_at:
        return False
    hb = report.heartbeat_at
    if hb.tzinfo is None:
        hb = hb.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - hb).total_seconds() < settings.heartbeat_stale_seconds


def mark_report_deleted(db: Session, report: Report) -> None:
    report.status = "deleted"
    report.html = None
    report.report_json = None
    report.stages_json = None
    db.commit()


def can_user_retry(report: Report) -> bool:
    settings = get_settings()
    if report.status in {"failed", "degraded"}:
        return True
    if report.status == "generating":
        if not _heartbeat_fresh(report):
            return True
        if report.started_at:
            st = report.started_at
            if st.tzinfo is None:
                st = st.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - st).total_seconds() > settings.user_retry_after_seconds
    return False


def lazy_timeout_check(db: Session, report: Report) -> None:
    """status 查询时惰性回收卡死任务：generating 且 updated_at < now-10min → failed。"""
    if report.status != "generating":
        return
    ts = report.updated_at or report.created_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - ts).total_seconds() > 600:
        report.status = "failed"
        report.error = "生成超时，已自动回收。点击重试将从断点继续，无需重新对话。"
        db.commit()
        track("report_failed", session_id=report.session_id, props={"stage": report.progress_stage, "reason": "lazy_timeout"}, db=db)


def recover_stuck_reports() -> None:
    """应用启动扫描：心跳失效的 generating 置 failed（可重试接管）。"""
    db = SessionLocal()
    try:
        rows = db.scalars(select(Report).where(Report.status == "generating")).all()
        for r in rows:
            if not _heartbeat_fresh(r):
                r.status = "failed"
                r.error = "服务重启，任务已回收。点击重试将从断点继续。"
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------- 运行时上下文


class RunContext:
    def __init__(self, report_id: str, run_id: str):
        self.report_id = report_id
        self.run_id = run_id
        self.started = time.monotonic()
        self.settings = get_settings()

    def checkpoint(self, db: Session, stage: str | None = None) -> Report:
        """每次模型调用前自检：接管/删除/截止。通过则刷新心跳。"""
        report = db.get(Report, self.report_id)
        if report is None or report.status == "deleted" or report.run_id != self.run_id:
            raise PipelineAborted("run 已被接管或报告已删除")
        if time.monotonic() - self.started > self.settings.pipeline_deadline_seconds:
            report.status = "failed"
            report.error = "生成超过总截止时间（8 分钟），已取消剩余调用。可一键重试，从断点继续。"
            db.commit()
            track("report_failed", session_id=report.session_id, props={"stage": report.progress_stage, "reason": "deadline"}, db=db)
            raise PipelineAborted("超过总截止时间")
        report.heartbeat_at = utcnow()
        if stage:
            report.progress_stage = stage
        db.commit()
        return report

    def save_stage(self, db: Session, key: str, data) -> None:
        report = db.get(Report, self.report_id)
        if report is None or report.run_id != self.run_id or report.status == "deleted":
            raise PipelineAborted("回写被拒：run 已失效")
        stages = report.stages
        stages[key] = data
        report.stages_json = Report.dumps(stages)
        db.commit()


# ---------------------------------------------------------------- 入口


async def run_pipeline_task(report_id: str, run_id: str) -> None:
    db = SessionLocal()
    try:
        ctx = RunContext(report_id, run_id)
        await _run_pipeline(db, ctx)
    except PipelineAborted as exc:
        logger.info("pipeline aborted report=%s: %s", report_id, exc)
    except Exception:
        logger.exception("pipeline 未捕获异常 report=%s", report_id)
        report = db.get(Report, report_id)
        if report and report.run_id == run_id and report.status not in {"deleted", "ready"}:
            report.status = "failed"
            report.error = "生成过程出现异常。可一键重试，从断点继续。"
            db.commit()
            track("report_failed", session_id=report.session_id, props={"stage": report.progress_stage, "reason": "exception"}, db=db)
    finally:
        db.close()


async def _run_pipeline(db: Session, ctx: RunContext) -> None:
    settings = get_settings()
    report = ctx.checkpoint(db)
    session = db.get(DiagSession, report.session_id)
    if session is None:
        raise PipelineAborted("会话已删除")
    user = db.get(User, session.user_id)
    profile = session.profile
    identity = session.identity
    display_name = user.display_name if user else "朋友"
    stages = report.stages
    gen_started = time.monotonic()

    user_messages = _user_messages(db, session.id)
    transcript = _build_transcript(db, session.id)

    # ---- Stage A 事实提取 ----
    if "A" not in stages:
        ctx.checkpoint(db, "extracting")
        sys_p, usr_p = prompts.stage_a_prompt(transcript, profile, identity)
        a_out: StageAOut = await chat_json(
            settings.scoring_model,
            [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}],
            schema_hint=prompts.STAGE_A_SCHEMA,
            validator=lambda d: StageAOut.model_validate(d),
            temperature=0.2,
            max_tokens=4000,
            timeout=90,
            stage="report_A",
            session_id=session.id,
            user_id=session.user_id,
        )
        ctx.save_stage(db, "A", a_out.model_dump())
        stages = db.get(Report, ctx.report_id).stages

    # ---- Stage A′ 证据校验（代码，先于评分） ----
    if "Aprime" not in stages:
        ctx.checkpoint(db, "verifying")
        aprime = _verify_evidence(StageAOut.model_validate(stages["A"]), user_messages)
        ctx.save_stage(db, "Aprime", aprime)
        report = db.get(Report, ctx.report_id)
        report.quote_hit_rate = aprime["quote_hit_rate"]
        db.commit()
        stages = report.stages

    evidence_pool: list[dict] = stages["Aprime"]["evidence"]

    # ---- Stage B 七维评分（并发，逐维落库，单维失败只重跑该维） ----
    b_results: dict = stages.get("B", {})
    missing_dims = [k for k in DIM_KEYS if k not in b_results]
    if missing_dims:
        ctx.checkpoint(db, "scoring")

        async def score_dim(dim_key: str):
            pool = [e for e in evidence_pool if e["dimension"] == dim_key]
            sys_p, usr_p = prompts.stage_b_prompt(dim_key, pool, profile, identity)
            result: DimScore = await chat_json(
                settings.scoring_model,
                [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}],
                schema_hint=prompts.STAGE_B_SCHEMA,
                validator=lambda d: DimScore.model_validate(d),
                temperature=0.2,
                max_tokens=2000,
                timeout=90,
                stage=f"report_B_{dim_key}",
                session_id=session.id,
                user_id=session.user_id,
            )
            return dim_key, _sanitize_dim_score(result, pool)

        outcomes = await asyncio.gather(
            *(score_dim(k) for k in missing_dims), return_exceptions=True
        )
        failed = []
        for item in outcomes:
            if isinstance(item, BaseException):
                failed.append(item)
                continue
            dim_key, data = item
            b_results[dim_key] = data
            ctx.save_stage(db, "B", b_results)
        if failed:
            raise LLMError(f"七维评分有 {len(failed)} 个维度失败: {failed[0]}")
        stages = db.get(Report, ctx.report_id).stages

    totals = compute_totals(b_results, session)

    # ---- Stage C 结构结论 ----
    if "C" not in stages:
        ctx.checkpoint(db, "concluding")
        sys_p, usr_p = prompts.stage_c_prompt(b_results, evidence_pool, profile, identity, totals)
        c_out: StageCOut = await chat_json(
            settings.scoring_model,
            [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}],
            schema_hint=prompts.STAGE_C_SCHEMA,
            validator=lambda d: StageCOut.model_validate(d),
            temperature=0.2,
            max_tokens=3000,
            timeout=90,
            stage="report_C",
            session_id=session.id,
            user_id=session.user_id,
        )
        ctx.save_stage(db, "C", _sanitize_stage_c(c_out, b_results, evidence_pool).model_dump())
        stages = db.get(Report, ctx.report_id).stages

    # ---- Stage D 叙事（×2 并发） ----
    narrative_context = _narrative_context(stages, b_results, totals, profile)
    d_tasks = []
    if "D1" not in stages:
        sys_p, usr_p = prompts.stage_d1_prompt(narrative_context, identity, display_name)
        d_tasks.append(("D1", sys_p, usr_p, prompts.STAGE_D1_SCHEMA, StageD1Out))
    if "D2" not in stages:
        sys_p, usr_p = prompts.stage_d2_prompt(narrative_context, identity, display_name)
        d_tasks.append(("D2", sys_p, usr_p, prompts.STAGE_D2_SCHEMA, StageD2Out))
    if d_tasks:
        ctx.checkpoint(db, "composing")

        async def run_narrative(key, sys_p, usr_p, schema, model_cls):
            out = await chat_json(
                settings.narrative_model,
                [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}],
                schema_hint=schema,
                validator=lambda d: model_cls.model_validate(d),
                max_tokens=4096,
                timeout=120,
                stage=f"report_{key}",
                session_id=session.id,
                user_id=session.user_id,
            )
            return key, out.model_dump()

        outcomes = await asyncio.gather(
            *(run_narrative(*t) for t in d_tasks), return_exceptions=True
        )
        for item in outcomes:
            if isinstance(item, BaseException):
                raise LLMError(f"叙事章节生成失败: {item}")
            key, data = item
            ctx.save_stage(db, key, data)
        stages = db.get(Report, ctx.report_id).stages

    # ---- Stage E 组装渲染（纯代码） ----
    ctx.checkpoint(db, "rendering")
    report_doc = _assemble(
        stages, b_results, totals, session, user, transcript_len=len(user_messages)
    )
    html = render_report_html(report_doc)

    report = db.get(Report, ctx.report_id)
    if report is None or report.run_id != ctx.run_id or report.status == "deleted":
        raise PipelineAborted("回写被拒")
    if report.version > 0 and report.html:
        db.add(
            ReportVersion(
                report_id=report.id,
                version=report.version,
                report_json=report.report_json,
                html=report.html,
            )
        )
    report.version += 1
    report.report_json = Report.dumps(report_doc)
    report.html = html
    report.status = "ready"
    report.progress_stage = None
    report.models_used = Report.dumps(
        {
            "scoring": settings.scoring_model,
            "narrative": settings.narrative_model,
            "interview": settings.interview_model,
        }
    )
    db.commit()
    session.status = "report_ready"
    db.commit()
    track(
        "report_ready",
        user_id=session.user_id,
        session_id=session.id,
        props={
            "duration": round(time.monotonic() - gen_started, 1),
            "valid": report_doc["meta"]["valid"],
            "quote_hit_rate": report.quote_hit_rate,
        },
        db=db,
    )


# ---------------------------------------------------------------- Stage 实现


def _user_messages(db: Session, session_id: str) -> dict[int, str]:
    rows = db.scalars(
        select(Message).where(Message.session_id == session_id, Message.role == "user")
    ).all()
    return {m.seq: m.content for m in rows}


def _build_transcript(db: Session, session_id: str) -> str:
    rows = db.scalars(
        select(Message).where(Message.session_id == session_id).order_by(Message.seq)
    ).all()
    return "\n".join(f"[{m.role}#{m.seq}] {redact_pii(m.content)}" for m in rows)


def _verify_evidence(a_out: StageAOut, user_messages: dict[int, str]) -> dict:
    """Stage A′：quote↔用户消息绑定核验；不命中→剔除或标待确认。"""
    verified, hits, total_quotes = [], 0, 0
    memorable_ids: set[str] = set()
    eid = 0
    for raw, is_memorable in [(e, False) for e in a_out.evidence] + [
        (q, True) for q in a_out.memorable_quotes
    ]:
        if raw.dimension not in DIM_KEYS:
            continue
        eid += 1
        if is_memorable:
            memorable_ids.add(f"E{eid}")
        entry = {
            "id": f"E{eid}",
            "dimension": raw.dimension,
            "point": raw.point,
            "source_type": raw.source_type,
            "quote": raw.quote,
            "message_id": raw.message_id,
            "status": "confirmed",
        }
        if raw.quote:
            total_quotes += 1
            ok, reason = quote_check.verify_quote(raw.quote, raw.message_id, user_messages)
            if ok:
                hits += 1
            else:
                # 有 point 无可信 quote：剔除引语、证据降为「待确认」；绝不转述保留
                entry["quote"] = None
                entry["message_id"] = None
                entry["status"] = "待确认"
                entry["verify_fail_reason"] = reason
        verified.append(entry)
    return {
        "evidence": verified,
        "quote_hit_rate": round(hits / total_quotes, 3) if total_quotes else 1.0,
        "memorable_quote_ids": sorted(memorable_ids),
        "facts": {
            "profile_summary": a_out.profile_summary,
            "timeline": a_out.timeline,
            "weekly_hours": a_out.weekly_hours,
            "experiences": a_out.experiences,
            "skills": a_out.skills,
            "job_actions": a_out.job_actions,
            "key_facts": a_out.key_facts,
        },
    }


def _sanitize_dim_score(result: DimScore, pool: list[dict]) -> dict:
    """代码校验：引用存在且来源可计分；违例剔除；证据不足时撤销评分。"""
    scoreable_ids = {
        e["id"]
        for e in pool
        if e["source_type"] in SCOREABLE_SOURCES and e["status"] == "confirmed"
    }
    all_ids = {e["id"] for e in pool}
    refs = [r for r in result.evidence_refs if r in all_ids]
    data = result.model_dump()
    data["evidence_refs"] = refs
    if result.evidence_state == "evidenced":
        if not any(r in scoreable_ids for r in refs):
            # 没有任何可计分证据支撑 → 降为信息不足
            data["evidence_state"] = "insufficient"
            data["score"] = None
    if data["evidence_state"] == "confirmed_absent":
        data["score"] = min(data["score"] or 0, 1)
    if data["evidence_state"] in {"insufficient", "not_applicable"}:
        data["score"] = None
    if data["evidence_state"] == "evidenced" and data["score"] is None:
        data["evidence_state"] = "insufficient"
    return data


def _sanitize_stage_c(c_out: StageCOut, b_results: dict, pool: list[dict]) -> StageCOut:
    all_ids = {e["id"] for e in pool}
    for c in c_out.conclusions:
        c.evidence_refs = [r for r in c.evidence_refs if r in all_ids]
        c.basis_dimensions = [d for d in c.basis_dimensions if d in DIM_KEYS]
    return c_out


def compute_totals(b_results: dict, session: DiagSession) -> dict:
    """总分口径 = 已评维度小计；评分维度 <4 个不下整体判断（产品设计 §4/§7）。"""
    scored = {
        k: v
        for k, v in b_results.items()
        if v.get("score") is not None
        and v.get("evidence_state") in {"evidenced", "confirmed_absent"}
    }
    total = sum(v["score"] for v in scored.values())
    cov = session.coverage or {}
    total_questions = cov.get("_opening", {}).get("questions_asked", 0) + sum(
        cov.get(k, {}).get("questions_asked", 0) for k in DIM_KEYS
    )
    scored_count = len(scored)
    return {
        "total": total,
        "max": 7 * scored_count,
        "scored_count": scored_count,
        "pending_dims": [k for k in DIM_KEYS if k not in scored],
        "completion": f"{scored_count}/7",
        "overall_judgment_allowed": scored_count >= 4,
        "valid": scored_count >= 5 and total_questions >= 10,
        "total_questions": total_questions,
        "input_total": sum(v["score"] for k, v in scored.items() if DIM_BY_KEY[k]["group"] == "input"),
        "input_max": 7 * len([k for k in scored if DIM_BY_KEY[k]["group"] == "input"]),
        "output_total": sum(v["score"] for k, v in scored.items() if DIM_BY_KEY[k]["group"] == "output"),
        "output_max": 7 * len([k for k in scored if DIM_BY_KEY[k]["group"] == "output"]),
    }


def _narrative_context(stages: dict, b_results: dict, totals: dict, profile: dict) -> str:
    facts = stages["Aprime"]["facts"]
    pool = stages["Aprime"]["evidence"]
    c = stages.get("C", {})
    quote_lines = [
        f"- [{e['id']}]「{e['quote']}」" for e in pool if e.get("quote") and e["status"] == "confirmed"
    ]
    dim_lines = [
        f"- {DIM_BY_KEY[k]['short']}: {v['evidence_state']} / {v['score']}分 / {v['core_judgement']} / 下一步: {v['next_step']}"
        for k, v in b_results.items()
    ]
    return f"""# 报告撰写素材（全部事实以此为准，不得新增）

## 画像与事实
{facts['profile_summary']}
时间线：{facts['timeline']}；每周可投入：{facts['weekly_hours']}
目标：{profile.get('target_role') or '探索中'}（目标明确：{profile.get('goal_clear')}）
经历：{'；'.join(facts['experiences'])}
技能：{'；'.join(facts['skills'])}
求职动作：{'；'.join(facts['job_actions'])}
关键事实：{'；'.join(facts['key_facts'])}

## 七维评分（总分 {totals['total']}/{totals['max']}·已评 {totals['scored_count']} 维，待核实 {len(totals['pending_dims'])} 维）
{chr(10).join(dim_lines)}

## 结构结论
一句话：{c.get('one_liner', '')}
结构解读：{c.get('io_interpretation', '')}
结论：{'；'.join(x['text'] for x in c.get('conclusions', []))}
第一优先动作：{c.get('first_priority_action', {})}

## 已验证的用户原话（引用只能从这里选，逐字使用）
{chr(10).join(quote_lines) if quote_lines else '（无已验证引语，正文不要使用直接引语）'}"""


# ---------------------------------------------------------------- Stage E


def scrub_blacklist(text: str, identity: str) -> str:
    table = dict(BLACKLIST_COMMON)
    if identity == "professional":
        table.update(BLACKLIST_PROFESSIONAL)
    for bad, good in table.items():
        text = text.replace(bad, good)
    return text


def _scrub_obj(obj, identity: str):
    if isinstance(obj, str):
        return scrub_blacklist(obj, identity)
    if isinstance(obj, list):
        return [_scrub_obj(x, identity) for x in obj]
    if isinstance(obj, dict):
        return {k: _scrub_obj(v, identity) for k, v in obj.items()}
    return obj


def _assemble(
    stages: dict,
    b_results: dict,
    totals: dict,
    session: DiagSession,
    user: User | None,
    transcript_len: int,
) -> dict:
    """组装 ReportDocument：终检（引语二次核验已由池保证＋黑名单）→ 雷达 → 元信息。"""
    settings = get_settings()
    identity = session.identity
    profile = session.profile
    pool = stages["Aprime"]["evidence"]
    pool_by_id = {e["id"]: e for e in pool}

    dims = []
    for k in DIM_KEYS:
        v = dict(b_results.get(k, {"evidence_state": "insufficient", "score": None}))
        v["key"] = k
        v["name"] = DIM_BY_KEY[k]["name"]
        v["short"] = DIM_BY_KEY[k]["short"]
        v["group"] = DIM_BY_KEY[k]["group"]
        v["high_standard"] = DIM_BY_KEY[k]["high_standard"]
        v["pending"] = v.get("score") is None
        v["evidence"] = [pool_by_id[r] for r in v.get("evidence_refs", []) if r in pool_by_id]
        dims.append(v)

    radar_svg = radar.render_radar_svg(
        [{"short": d["short"], "score": d.get("score"), "pending": d["pending"]} for d in dims]
    )

    memorable = [
        e for e in pool
        if e["id"] in set(stages["Aprime"].get("memorable_quote_ids", []))
        and e.get("quote") and e["status"] == "confirmed"
    ][:3]

    doc = {
        "meta": {
            "brand_name": settings.brand_name,
            "brand_tagline_en": settings.brand_tagline_en,
            "display_name": user.display_name if user else "朋友",
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "identity": identity,
            "mode": session.mode,
            "goal_clear": bool(profile.get("goal_clear")),
            "target_role": profile.get("target_role"),
            "completion": totals["completion"],
            "turn_count": totals["total_questions"],
            "user_message_count": transcript_len,
            "valid": totals["valid"],
            "overall_judgment_allowed": totals["overall_judgment_allowed"],
        },
        "totals": totals,
        "facts": stages["Aprime"]["facts"],
        "dimensions": dims,
        "structure": stages.get("C", {}),
        "narrative1": stages.get("D1", {}),
        "narrative2": stages.get("D2", {}),
        "memorable_quotes": memorable,
        "radar_svg": radar_svg,
        "scale_labels": SCALE_LABELS,
        "band_table": BAND_TABLE,
    }
    # 黑名单终检：雷达 SVG 为代码产物不过滤，其余全部过滤
    svg = doc.pop("radar_svg")
    doc = _scrub_obj(doc, identity)
    doc["radar_svg"] = svg
    return doc


def render_report_html(doc: dict) -> str:
    template = _env.get_template("report.html.j2")
    return template.render(**doc)


# ---------------------------------------------------------------- 降级交付


def build_degraded_delivery(db: Session, report: Report) -> None:
    """简版交付：已验证事实＋已评维度小结＋对话导出（不再调模型，不计入有效报告）。"""
    session = db.get(DiagSession, report.session_id)
    user = db.get(User, session.user_id) if session else None
    stages = report.stages
    facts = (stages.get("Aprime") or {}).get("facts", {})
    b_results = stages.get("B", {})
    msgs = db.scalars(
        select(Message).where(Message.session_id == report.session_id).order_by(Message.seq)
    ).all()

    def esc(s):
        return html_lib.escape(str(s or ""))

    dim_rows = "".join(
        f"<tr><td>{esc(DIM_BY_KEY[k]['short'])}</td><td>{esc(v.get('score', '待核实'))}</td><td>{esc(v.get('core_judgement', ''))}</td></tr>"
        for k, v in b_results.items()
    )
    fact_items = "".join(f"<li>{esc(f)}</li>" for f in facts.get("key_facts", []))
    chat_lines = "".join(
        f"<p><b>{'你' if m.role == 'user' else 'AI 诊断师'}：</b>{esc(m.content)}</p>" for m in msgs
    )
    name = esc(user.display_name if user else "")
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="generator" content="AI">
<title>诊断简版结果 - {name}</title>
<style>body{{font-family:system-ui,"PingFang SC",sans-serif;max-width:720px;margin:0 auto;padding:24px;color:#1a1a2e;line-height:1.75}}
h1{{color:#0a1e50}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #dfe5f2;padding:8px}}
.note{{background:#fff4ee;border-left:4px solid #ff6b35;padding:12px 16px;border-radius:6px}}</style></head><body>
<h1>诊断简版结果</h1>
<p class="note">本次完整报告生成多次失败，这是基于已验证信息的简版交付（AI 生成，仅供参考）。你的对话已完整保存在下方，可随时重试生成完整报告。</p>
<h2>已验证的关键事实</h2><ul>{fact_items or '<li>（提取阶段未完成）</li>'}</ul>
<h2>已评维度小结</h2><table><tr><th>维度</th><th>分数</th><th>核心判断</th></tr>{dim_rows or '<tr><td colspan=3>（评分阶段未完成）</td></tr>'}</table>
<h2>对话导出</h2>{chat_lines}
<footer><p>—— 本报告由求职陪跑出品 · AI 生成 ——</p></footer></body></html>"""
    report.html = html
    report.status = "degraded"
    report.progress_stage = None
    db.commit()
    if session:
        session.status = "report_ready"
        db.commit()
