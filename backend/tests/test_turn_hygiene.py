"""每轮恰 1 问 + 开场段完整性护栏（纯函数部分）。"""
from app.interview.orchestrator import (
    apply_opening_guard,
    message_violates_single_question,
    question_count,
)


def test_question_count_mixed_marks():
    assert question_count("你好。") == 0
    assert question_count("是哪类？怎么定的？") == 2
    assert question_count("what? 为什么？") == 2
    assert question_count("只有一个问题？") == 1


def test_single_question_violation_detection():
    ok = {"action": "next_question", "message": "先聊第一段经历：你具体负责什么？"}
    assert not message_violates_single_question(ok)
    double = {"action": "switch_dimension", "message": "岗位是哪类？方向怎么定的？"}
    assert message_violates_single_question(double)
    zero = {"action": "followup", "message": "说说看。"}
    assert message_violates_single_question(zero)
    # 收尾语不要求带问题
    wrap = {"action": "wrap_up", "message": "我们就聊到这里，报告马上生成。"}
    assert not message_violates_single_question(wrap)


def test_opening_guard_blocks_dimension_switch():
    d = {"action": "switch_dimension", "next_dimension": "inventory", "message": "聊聊能力？"}
    fixed, violated = apply_opening_guard(d, opening_remaining=1)
    assert violated
    assert fixed["action"] == "next_question"
    assert fixed["next_dimension"] is None


def test_opening_guard_blocks_followup():
    d = {"action": "followup", "next_dimension": None, "message": "能展开讲讲吗？"}
    _, violated = apply_opening_guard(d, opening_remaining=2)
    assert violated


def test_opening_guard_passes_when_opening_done():
    d = {"action": "switch_dimension", "next_dimension": "inventory", "message": "聊聊能力？"}
    fixed, violated = apply_opening_guard(d, opening_remaining=0)
    assert not violated
    assert fixed["action"] == "switch_dimension"


def test_opening_guard_allows_next_question_during_opening():
    d = {"action": "next_question", "next_dimension": None, "message": "时间线是怎样的？"}
    _, violated = apply_opening_guard(d, opening_remaining=1)
    assert not violated
