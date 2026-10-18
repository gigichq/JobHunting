"""报告流水线各 Stage 的输出契约（02-技术设计 §10）。"""
from typing import Literal

from pydantic import BaseModel, Field

SourceType = Literal["用户自述", "现场展示", "他人反馈转述", "AI辅导后产出", "AI推断"]
SCOREABLE_SOURCES = {"用户自述", "现场展示"}

EvidenceState = Literal["evidenced", "confirmed_absent", "insufficient", "not_applicable"]


class RawEvidence(BaseModel):
    """Stage A 提取的单条证据（待 A′ 校验）。"""
    dimension: str
    point: str = Field(max_length=300)
    source_type: SourceType = "用户自述"
    quote: str | None = Field(default=None, max_length=500)
    message_id: int | None = None  # 用户消息 seq


class StageAOut(BaseModel):
    profile_summary: str = ""
    timeline: str = ""
    weekly_hours: str = ""
    experiences: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    job_actions: list[str] = Field(default_factory=list)
    key_facts: list[str] = Field(default_factory=list, description="关键事实清单")
    memorable_quotes: list[RawEvidence] = Field(
        default_factory=list, description="最值得记住的话（也走引语校验）"
    )
    evidence: list[RawEvidence] = Field(default_factory=list)


class VerifiedEvidence(BaseModel):
    """Stage A′ 输出：进入评分的结构化证据池。"""
    id: str
    dimension: str
    point: str
    source_type: SourceType
    status: Literal["confirmed", "待确认", "矛盾"]
    quote: str | None = None
    message_id: int | None = None


class DimScore(BaseModel):
    """Stage B 单维输出。"""
    evidence_state: EvidenceState
    score: int | None = Field(default=None, ge=0, le=7)
    core_judgement: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    why: str = ""
    next_step: str = ""
    deliverable_goal: str = ""
    translation_rows: list[dict] = Field(
        default_factory=list,
        description="社招×目标明确：现有经验→目标岗位转译表 [{current, target, gap}]",
    )


class StructuralConclusion(BaseModel):
    text: str
    basis_dimensions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: Literal["高", "中", "低"] = "中"


class StageCOut(BaseModel):
    one_liner: str = ""
    keywords: list[str] = Field(default_factory=list, max_length=3)
    io_interpretation: str = Field(default="", description="输入端/输出端结构解读")
    conclusion_tags: list[str] = Field(default_factory=list)
    conclusions: list[StructuralConclusion] = Field(default_factory=list, max_length=3)
    constraints: list[dict] = Field(
        default_factory=list, description="[{constraint, counter}] 约束与对策"
    )
    interview_failure_attribution: list[dict] = Field(
        default_factory=list,
        description="社招：面试挂点归因 [{possible_cause, verify_method}]，只写可能原因＋验证办法",
    )
    first_priority_action: dict = Field(
        default_factory=dict,
        description="{gap, action, reason, time_cost, sample} 第一优先动作",
    )


class StageD1Out(BaseModel):
    """叙事①：摘要/快照/亮点。"""
    exec_summary: str = ""
    strengths: list[dict] = Field(
        default_factory=list, description="优势牌 [{title, detail}]，≤4 张"
    )
    to_fill: list[str] = Field(default_factory=list, description="待补齐")
    potential_direction: str = ""
    one_sentence_for_you: str = ""
    snapshot: dict = Field(
        default_factory=dict, description="背景快照 {rows: [{label, value}]}"
    )
    environment_observation: str = ""
    highlights: list[dict] = Field(
        default_factory=list, description="亮点与潜力 [{title, detail}]，≤6 项不计分"
    )


class StageD2Out(BaseModel):
    """叙事②：行动计划/执行机制/结语。"""
    week_actions: list[dict] = Field(
        default_factory=list,
        description="本周 3 个动作 [{action, why, deliverable_template}]（社招=两周面试应急包）",
    )
    ninety_day_plan: list[dict] = Field(
        default_factory=list, description="90 天补底子 [{phase, focus, actions}]"
    )
    weekly_rhythm: str = ""
    kanban_checklist: list[str] = Field(default_factory=list)
    retest_advice: str = ""
    ending_letter: str = Field(default="", description="致XX 结语正文")
