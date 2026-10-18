"""对话编排器（02-技术设计 §9）。

每轮时序：用户消息入库 → guards 计算硬约束 → 组装 prompt → INTERVIEW_MODEL JSON 决策
→ 校验/enforce → 决策与 AI 消息入库 → 返回。
coverage_json 结构：{dim_key: {...}} + "_opening": {"questions_asked"} + "_current": dim_key|None
"""
import logging
import time
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics import track
from ..config import get_settings
from ..llm.client import LLMError, chat_json, chat_text, redact_pii
from ..models import DiagSession, Message
from . import guards, prompts
from .dimensions import DIM_BY_KEY, DIM_KEYS, OPENING_QUESTIONS

logger = logging.getLogger(__name__)

RECENT_TURNS = 12
BAD_QUALITIES = {"perfunctory", "off_topic"}
QUESTION_ACTIONS = {"followup", "next_question", "switch_dimension"}


def question_count(text: str) -> int:
    return text.count("？") + text.count("?")


def apply_opening_guard(decision: dict, opening_remaining: int) -> tuple[dict, bool]:
    """开场段硬护栏：开场问题问完之前只允许 next_question。
    返回 (决策, 是否违例)——违例时 message 也需要改写成应问的开场问题。"""
    if opening_remaining <= 0 or decision.get("action") == "next_question":
        return decision, False
    if decision.get("action") in {"switch_dimension", "followup"}:
        decision["action"] = "next_question"
        decision["next_dimension"] = None
        return decision, True
    return decision, False


def message_violates_single_question(decision: dict) -> bool:
    """每轮恰 1 问（wrap_up/end 为收尾语，不检查）。"""
    if decision.get("action") not in QUESTION_ACTIONS:
        return False
    return question_count(decision.get("message", "")) != 1


class Decision(BaseModel):
    analysis: str = ""
    answer_quality: Literal[
        "normal", "perfunctory", "off_topic", "pasted_document", "contradictory"
    ] = "normal"
    evidence_state: Literal[
        "evidenced", "confirmed_absent", "insufficient", "not_applicable"
    ] | None = None
    evidence_notes: list[str] = Field(default_factory=list, max_length=40)
    quotes: list[str] = Field(default_factory=list, max_length=10)
    action: str
    next_dimension: str | None = None
    message: str = Field(min_length=1, max_length=1200)


def init_coverage() -> dict:
    cov = guards.empty_coverage()
    cov["_opening"] = {"questions_asked": 1}  # 开场白已含第 1 个开场问题
    cov["_current"] = None
    return cov


def _dim_coverage(cov: dict) -> dict:
    return {k: cov[k] for k in DIM_KEYS}


def total_questions(cov: dict) -> int:
    return cov.get("_opening", {}).get("questions_asked", 0) + sum(
        cov[k]["questions_asked"] for k in DIM_KEYS
    )


def _recent_messages(db: Session, session_id: str, limit: int = RECENT_TURNS) -> list[dict]:
    rows = db.scalars(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.seq.desc())
        .limit(limit)
    ).all()
    return [
        {"role": m.role, "seq": m.seq, "content": m.content}
        for m in reversed(rows)
    ]


def _last_decision(db: Session, session_id: str) -> dict:
    row = db.scalar(
        select(Message)
        .where(Message.session_id == session_id, Message.role == "assistant")
        .order_by(Message.seq.desc())
        .limit(1)
    )
    return Message.loads(row.decision_json, {}) if row else {}


def _consecutive_bad(db: Session, session_id: str) -> int:
    rows = db.scalars(
        select(Message)
        .where(Message.session_id == session_id, Message.role == "assistant")
        .order_by(Message.seq.desc())
        .limit(3)
    ).all()
    count = 0
    for m in rows:
        q = Message.loads(m.decision_json, {}).get("answer_quality")
        if q in BAD_QUALITIES:
            count += 1
        else:
            break
    return count


def next_seq(db: Session, session_id: str) -> int:
    last = db.scalar(
        select(Message.seq)
        .where(Message.session_id == session_id)
        .order_by(Message.seq.desc())
        .limit(1)
    )
    return (last or 0) + 1


def progress_payload(cov: dict) -> dict:
    return {
        "dimensions": [
            {
                "key": k,
                "short": DIM_BY_KEY[k]["short"],
                "questions_asked": cov[k]["questions_asked"],
                "evidence_state": cov[k]["evidence_state"],
                "done": cov[k].get("done", False),
            }
            for k in DIM_KEYS
        ],
        "total_questions": total_questions(cov),
        "current_dimension": cov.get("_current"),
    }


async def handle_user_message(
    db: Session, session: DiagSession, content: str, *, resumed: bool = False
) -> dict:
    """处理一条用户发言，返回 {message, progress, ended, decision_fixes}。"""
    settings = get_settings()
    started = time.monotonic()
    cov = session.coverage or init_coverage()
    profile = session.profile
    identity = session.identity

    # 1. 用户消息入库
    user_msg = Message(
        session_id=session.id,
        seq=next_seq(db, session.id),
        role="user",
        content=content,
        dimension_key=cov.get("_current"),
    )
    db.add(user_msg)
    db.commit()

    # 2. 护栏状态
    opening_total = len(OPENING_QUESTIONS[identity])
    opening_asked = cov.get("_opening", {}).get("questions_asked", 0)
    opening_remaining = max(0, opening_total - opening_asked)
    current_dim = cov.get("_current")
    directives = guards.compute_directives(
        mode=session.mode,
        coverage=_dim_coverage(cov),
        total_questions=total_questions(cov),
        current_dim=current_dim,
        consecutive_bad_answers=_consecutive_bad(db, session.id),
    )
    if opening_remaining > 0:
        # 开场段只允许继续开场问题（问完才可切维度）
        directives.allowed_actions = {"next_question"}
        if directives.forced_action:
            directives.allowed_actions = {directives.forced_action}
    elif current_dim is None:
        # 开场已结束但尚未进入任何维度：本轮必须切入维度
        directives.prompt_notes.append(
            "开场段已结束：本轮 action 必须是 switch_dimension，切入第一个维度提问。"
        )

    # 3. 组装 prompt
    last_decision = _last_decision(db, session.id)
    evidence_notes = last_decision.get("evidence_notes", [])
    recent = _recent_messages(db, session.id)
    for m in recent:
        m["content"] = redact_pii(m["content"])
    guard_notes = list(directives.prompt_notes)
    if resumed:
        guard_notes.append(prompts.resume_note())

    sys_prompt = prompts.system_prompt(profile, session.mode)
    user_prompt = prompts.turn_user_prompt(
        current_dim=current_dim,
        coverage=_dim_coverage(cov),
        evidence_notes=evidence_notes,
        recent_turns=recent,
        guard_notes=guard_notes,
        allowed_actions=directives.allowed_actions,
        opening_remaining=opening_remaining,
        identity=identity,
    )

    # 4. LLM 决策（校验失败自动修复重试 1 次）
    decision_model: Decision = await chat_json(
        settings.interview_model,
        [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ],
        schema_hint=prompts.DECISION_SCHEMA_HINT,
        validator=lambda d: Decision.model_validate(d),
        temperature=0.3,
        max_tokens=1500,
        stage="interview_turn",
        session_id=session.id,
        user_id=session.user_id,
    )
    decision = decision_model.model_dump()

    # 5. 护栏改写
    decision, fixes = guards.enforce(decision, directives, _dim_coverage(cov))
    # 开场段硬护栏：开场问题问完之前不得切维度/追问
    decision, opening_violated = apply_opening_guard(decision, opening_remaining)
    if opening_violated:
        fixes.append("开场段未完成 → 强制 next_question")
        pending_q = OPENING_QUESTIONS[identity][opening_asked]
        decision["message"] = await _polish_message(
            session,
            decision["message"],
            f"在简短肯定用户上一轮回答（≤1 句）之后，提出这个问题：「{pending_q}」。"
            "总共不超过 3 句、恰好一个问号。",
        )
    # 开场结束且无当前维度时，提问必须归属某个维度（否则计数与护栏全部失效）
    if (
        opening_remaining == 0
        and current_dim is None
        and decision["action"] in {"followup", "next_question"}
    ):
        decision["action"] = "switch_dimension"
        decision["next_dimension"] = directives.forced_dimension or guards.least_covered_dim(
            _dim_coverage(cov)
        )
        fixes.append("开场后无当前维度 → 强制 switch_dimension")
    # 每轮恰 1 问：违例时轻量改写 message（软修复，失败保留原文不阻塞对话）
    if message_violates_single_question(decision):
        fixes.append(f"message 含 {question_count(decision['message'])} 个问号 → 改写为恰 1 问")
        decision["message"] = await _polish_message(
            session,
            decision["message"],
            "改写为不超过 3 句、恰好一个问号的一段话：保留原意、事实与引用的用户原话；"
            "若原文有多个问题，只保留最重要的那一个。",
        )
    if fixes:
        logger.info("guards 改写决策 session=%s: %s", session.id, fixes)
    action = decision["action"]

    # 6. 状态推进
    dim_done_event = None
    if action in {"followup", "next_question"}:
        if opening_remaining > 0:
            cov["_opening"]["questions_asked"] = opening_asked + 1
        elif current_dim:
            cov[current_dim]["questions_asked"] += 1
    elif action == "switch_dimension":
        new_dim = decision.get("next_dimension") or guards.least_covered_dim(_dim_coverage(cov))
        if current_dim:
            cov[current_dim]["done"] = _dim_is_done(cov[current_dim], session.mode)
            if cov[current_dim]["done"]:
                dim_done_event = current_dim
        if new_dim:
            cov["_current"] = new_dim
            cov[new_dim]["questions_asked"] += 1
            current_dim = new_dim

    # 更新当前维度证据状态（switch 前的判断归旧维度，switch 后不覆盖新维度）
    if action != "switch_dimension" and current_dim and decision.get("evidence_state"):
        cov[current_dim]["evidence_state"] = decision["evidence_state"]
        if cov[current_dim]["evidence_state"] == "confirmed_absent":
            cov[current_dim]["done"] = (
                cov[current_dim]["questions_asked"] >= guards.CONFIRMED_ABSENT_FAST_PASS
            )

    ended = action in {"wrap_up", "end"}

    # 7. AI 消息入库
    ai_msg = Message(
        session_id=session.id,
        seq=next_seq(db, session.id),
        role="assistant",
        content=decision["message"],
        dimension_key=cov.get("_current"),
        decision_json=Message.dumps({**decision, "guard_fixes": fixes}),
    )
    db.add(ai_msg)

    session.coverage_json = DiagSession.dumps(cov)
    session.turn_count = total_questions(cov)
    if ended:
        session.status = "ended"
        from ..models import utcnow

        session.ended_at = utcnow()
    db.commit()

    # 8. 埋点
    track(
        "turn",
        user_id=session.user_id,
        session_id=session.id,
        props={
            "dimension": cov.get("_current"),
            "latency": round(time.monotonic() - started, 2),
            "action": action,
            "quality": decision.get("answer_quality"),
        },
        db=db,
    )
    if dim_done_event:
        track(
            "dimension_done",
            user_id=session.user_id,
            session_id=session.id,
            props={
                "dimension": dim_done_event,
                "evidence_state": cov[dim_done_event]["evidence_state"],
            },
            db=db,
        )
    if ended:
        track(
            "session_end",
            user_id=session.user_id,
            session_id=session.id,
            props={
                "reason": "ai_end",
                "turns": total_questions(cov),
                "coverage": {k: cov[k]["questions_asked"] for k in DIM_KEYS},
            },
            db=db,
        )

    return {
        "message": decision["message"],
        "progress": progress_payload(cov),
        "ended": ended,
    }


async def _polish_message(session: DiagSession, original: str, requirement: str) -> str:
    """用快模型按要求改写 message；失败时原样返回，不阻塞对话。"""
    settings = get_settings()
    try:
        out = await chat_text(
            settings.interview_model,
            [
                {
                    "role": "system",
                    "content": "你是中文文案改写助手。只输出改写后的那段话本身，"
                    "不要任何解释、引号或 markdown。",
                },
                {"role": "user", "content": f"{requirement}\n\n原文：\n{original}"},
            ],
            temperature=0.3,
            max_tokens=400,
            timeout=30,
            stage="message_fix",
            session_id=session.id,
            user_id=session.user_id,
        )
        out = out.strip()
        return out if out else original
    except LLMError:
        logger.warning("message 改写失败，保留原文 session=%s", session.id)
        return original


def _dim_is_done(dim_cov: dict, mode: str) -> bool:
    rules = guards.RULES[mode]
    if dim_cov.get("evidence_state") == "confirmed_absent":
        return dim_cov["questions_asked"] >= guards.CONFIRMED_ABSENT_FAST_PASS
    return dim_cov["questions_asked"] >= rules["min_per_dim"]
