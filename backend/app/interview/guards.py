"""代码护栏（02-技术设计 §9）：LLM 不可违反——违反则由代码改写 action。

纯函数设计：compute_directives() 产出给 prompt 的约束 + enforce() 事后改写。
覆盖度口径：questions_asked = 该维度下 AI 已提问次数；总轮次 = 全部已提问数（开场问不计维度但计总轮次）。
"""
from dataclasses import dataclass, field

from .dimensions import DIM_KEYS

ACTIONS = {"followup", "next_question", "switch_dimension", "wrap_up", "end"}

RULES = {
    "quick": {
        "min_per_dim": 1,
        "max_per_dim": 3,
        "ai_end_min_turns": 10,
        "force_wrap_turns": 20,
        "notice_turns": 12,
    },
    "full": {
        "min_per_dim": 2,
        "max_per_dim": 6,
        "ai_end_min_turns": 14,
        "force_wrap_turns": 40,
        "notice_turns": 30,
    },
}
CONFIRMED_ABSENT_FAST_PASS = 2  # 「已确认未做」2 问即记录证据状态并切换

NON_SCORING_STATES = {"insufficient", "not_applicable"}


def empty_coverage() -> dict:
    return {
        k: {"questions_asked": 0, "evidence_state": None, "done": False}
        for k in DIM_KEYS
    }


@dataclass
class Directives:
    """传给 prompt 的护栏指令 + enforce 的依据。"""
    mode: str
    total_questions: int = 0
    current_dim: str | None = None
    allowed_actions: set = field(default_factory=lambda: set(ACTIONS))
    forced_action: str | None = None       # 不为空则直接改写
    forced_dimension: str | None = None    # switch 时必须去的维度
    may_end: bool = False                  # AI 主动 end 是否满足前提
    must_switch: bool = False              # 当前维度到达上限
    can_switch: bool = False               # 当前维度满足最低提问数或快速通过
    offer_end_notice: bool = False         # 达阈值提醒「现在结束就能出报告」
    offer_three_options: bool = False      # 敷衍/跑题连续 2 次
    uncovered_dims: list = field(default_factory=list)
    prompt_notes: list = field(default_factory=list)


def _min_coverage_met(coverage: dict) -> bool:
    return all(coverage[k]["questions_asked"] >= 1 for k in DIM_KEYS)


def least_covered_dim(coverage: dict, exclude: set | None = None) -> str | None:
    """证据缺口最大的未完成维度（提问数最少优先，按维度顺序破平）。"""
    exclude = exclude or set()
    candidates = [
        k
        for k in DIM_KEYS
        if k not in exclude and not coverage[k].get("done")
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda k: (coverage[k]["questions_asked"], DIM_KEYS.index(k)))


def compute_directives(
    *,
    mode: str,
    coverage: dict,
    total_questions: int,
    current_dim: str | None,
    consecutive_bad_answers: int = 0,
) -> Directives:
    rules = RULES[mode]
    d = Directives(mode=mode, total_questions=total_questions, current_dim=current_dim)

    min_cov = _min_coverage_met(coverage)
    d.uncovered_dims = [k for k in DIM_KEYS if coverage[k]["questions_asked"] == 0]
    d.may_end = min_cov and total_questions >= rules["ai_end_min_turns"]

    cur = coverage.get(current_dim) if current_dim else None
    if cur:
        asked = cur["questions_asked"]
        fast_pass = (
            cur.get("evidence_state") == "confirmed_absent"
            and asked >= CONFIRMED_ABSENT_FAST_PASS
        )
        d.can_switch = asked >= rules["min_per_dim"] or fast_pass
        d.must_switch = asked >= rules["max_per_dim"] or (fast_pass and asked >= rules["max_per_dim"])
        if fast_pass:
            d.can_switch = True
            d.must_switch = True
            d.prompt_notes.append("当前维度已确认未做，记录证据状态后立即切换下一维度。")

    # 快速档先广后深：未完成最低覆盖前，切换必须去未覆盖维度
    if mode == "quick" and d.uncovered_dims:
        d.forced_dimension = least_covered_dim(coverage)
        d.prompt_notes.append(
            f"快速档先广后深：优先覆盖未问过的维度（下一个应为 {d.forced_dimension}）。"
        )
    elif d.must_switch or d.can_switch:
        d.forced_dimension = None  # 完整档/深挖期由 AI 选，enforce 只验合法性

    # 总轮次上限 → 强制收尾
    if total_questions >= rules["force_wrap_turns"]:
        d.forced_action = "wrap_up"
        d.prompt_notes.append("已达总轮次上限，本轮必须收尾（wrap_up）。")

    # 阈值提醒
    if total_questions >= rules["notice_turns"] and min_cov:
        d.offer_end_notice = True
        d.prompt_notes.append("请在本轮消息中告知用户：现在结束就能出报告，也可以继续聊。")

    # 退化场景：敷衍/跑题连续 2 次 → 三选项
    if consecutive_bad_answers >= 2:
        d.offer_three_options = True
        d.prompt_notes.append(
            "用户已连续敷衍/跑题两次：不要机械正反馈，本轮必须给三个选项——换个话题 / 跳过此维 / 现在结束出报告。"
        )

    # 允许动作集合
    allowed = {"followup", "next_question"}
    if cur is None:
        allowed = {"next_question", "switch_dimension"}
    if d.can_switch or d.must_switch:
        allowed.add("switch_dimension")
    if d.must_switch:
        allowed -= {"followup", "next_question"}
    allowed.add("wrap_up") if d.may_end else None
    if d.may_end:
        allowed.add("end")
    if d.forced_action:
        allowed = {d.forced_action}
    d.allowed_actions = allowed
    return d


def enforce(decision: dict, d: Directives, coverage: dict) -> tuple[dict, list[str]]:
    """改写违例决策。返回（修正后的决策, 修正记录）。"""
    fixes: list[str] = []
    action = decision.get("action")
    if action not in ACTIONS:
        decision["action"] = "followup"
        fixes.append(f"非法动作 {action!r} → followup")
        action = "followup"

    if d.forced_action and action != d.forced_action:
        decision["action"] = d.forced_action
        fixes.append(f"{action} → 强制 {d.forced_action}")
        action = d.forced_action

    # AI 主动 end 必须满足最低覆盖与轮次前提
    if action == "end" and not d.may_end:
        decision["action"] = "wrap_up" if d.offer_end_notice else "next_question"
        fixes.append(f"end 不满足前提 → {decision['action']}")
        action = decision["action"]

    # 未满足最低提问数不得切换（快速通过除外）
    if action == "switch_dimension" and d.current_dim and not d.can_switch:
        decision["action"] = "followup"
        fixes.append("switch 未满足每维最低提问数 → followup")
        action = "followup"

    # 到达每维上限必须切换
    if d.must_switch and action in {"followup", "next_question"}:
        decision["action"] = "switch_dimension"
        fixes.append("达到每维提问上限 → 强制 switch_dimension")
        action = "switch_dimension"

    # 切换目标校验
    if action == "switch_dimension":
        target = decision.get("next_dimension")
        if d.forced_dimension and target != d.forced_dimension:
            decision["next_dimension"] = d.forced_dimension
            fixes.append(f"切换目标 {target!r} → 先广后深强制 {d.forced_dimension}")
        elif target not in DIM_KEYS or coverage.get(target, {}).get("done"):
            fallback = least_covered_dim(coverage, exclude={d.current_dim} if d.current_dim else set())
            if fallback:
                decision["next_dimension"] = fallback
                fixes.append(f"非法切换目标 {target!r} → {fallback}")
            else:
                decision["action"] = "wrap_up"
                fixes.append("无可切换维度 → wrap_up")

    return decision, fixes
