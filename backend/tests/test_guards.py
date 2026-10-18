"""guards 全规则（02-技术设计 §13：快速通过/强制切换/上限/end 前提）。"""
from app.interview import guards
from app.interview.dimensions import DIM_KEYS


def cov_with(**overrides):
    cov = guards.empty_coverage()
    for k, v in overrides.items():
        cov[k].update(v)
    return cov


def test_quick_breadth_first_forces_uncovered_dim():
    cov = cov_with(inventory={"questions_asked": 1})
    d = guards.compute_directives(
        mode="quick", coverage=cov, total_questions=3, current_dim="inventory"
    )
    assert d.forced_dimension is not None
    assert cov[d.forced_dimension]["questions_asked"] == 0


def test_min_questions_before_switch_full_mode():
    cov = cov_with(inventory={"questions_asked": 1})
    d = guards.compute_directives(
        mode="full", coverage=cov, total_questions=5, current_dim="inventory"
    )
    assert not d.can_switch
    decision = {"action": "switch_dimension", "next_dimension": "mapping", "message": "x"}
    fixed, fixes = guards.enforce(decision, d, cov)
    assert fixed["action"] == "followup"
    assert fixes


def test_confirmed_absent_fast_pass_after_two_questions():
    cov = cov_with(inventory={"questions_asked": 2, "evidence_state": "confirmed_absent"})
    d = guards.compute_directives(
        mode="full", coverage=cov, total_questions=6, current_dim="inventory"
    )
    assert d.can_switch and d.must_switch


def test_max_per_dim_forces_switch():
    cov = cov_with(mapping={"questions_asked": 3})
    d = guards.compute_directives(
        mode="quick", coverage=cov, total_questions=9, current_dim="mapping"
    )
    assert d.must_switch
    decision = {"action": "followup", "next_dimension": None, "message": "x"}
    fixed, _ = guards.enforce(decision, d, cov)
    assert fixed["action"] == "switch_dimension"
    assert fixed["next_dimension"] in DIM_KEYS


def test_ai_end_requires_min_coverage_and_turns():
    # 七维各 1 问但总轮次不足 10 → 不许 end
    cov = guards.empty_coverage()
    for k in DIM_KEYS:
        cov[k]["questions_asked"] = 1
    d = guards.compute_directives(
        mode="quick", coverage=cov, total_questions=7, current_dim=DIM_KEYS[-1]
    )
    assert not d.may_end
    decision = {"action": "end", "next_dimension": None, "message": "收尾"}
    fixed, _ = guards.enforce(decision, d, cov)
    assert fixed["action"] != "end"

    # 覆盖且轮次达标 → 允许 end
    d2 = guards.compute_directives(
        mode="quick", coverage=cov, total_questions=10, current_dim=DIM_KEYS[-1]
    )
    assert d2.may_end


def test_force_wrap_at_turn_cap():
    cov = guards.empty_coverage()
    for k in DIM_KEYS:
        cov[k]["questions_asked"] = 2
    d = guards.compute_directives(
        mode="quick", coverage=cov, total_questions=20, current_dim=DIM_KEYS[0]
    )
    assert d.forced_action == "wrap_up"
    decision = {"action": "followup", "next_dimension": None, "message": "x"}
    fixed, _ = guards.enforce(decision, d, cov)
    assert fixed["action"] == "wrap_up"


def test_threshold_notice():
    cov = guards.empty_coverage()
    for k in DIM_KEYS:
        cov[k]["questions_asked"] = 2
    d = guards.compute_directives(
        mode="quick", coverage=cov, total_questions=12, current_dim=DIM_KEYS[0]
    )
    assert d.offer_end_notice


def test_three_options_after_two_bad_answers():
    cov = cov_with(inventory={"questions_asked": 2})
    d = guards.compute_directives(
        mode="quick",
        coverage=cov,
        total_questions=4,
        current_dim="inventory",
        consecutive_bad_answers=2,
    )
    assert d.offer_three_options


def test_illegal_switch_target_rewritten():
    cov = cov_with(inventory={"questions_asked": 2, "done": True})
    d = guards.compute_directives(
        mode="full", coverage=cov, total_questions=6, current_dim="inventory"
    )
    d.can_switch = True
    d.forced_dimension = None
    decision = {"action": "switch_dimension", "next_dimension": "nonexistent", "message": "x"}
    fixed, fixes = guards.enforce(decision, d, cov)
    assert fixed["next_dimension"] in DIM_KEYS and fixed["next_dimension"] != "inventory"
