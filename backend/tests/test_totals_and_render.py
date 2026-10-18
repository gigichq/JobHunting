"""分数汇总（待核实不计入）与模板渲染断言（章节锚点/黑名单/总分一致）。"""
import re

from app.interview.dimensions import BAND_TABLE, DIM_BY_KEY, DIM_KEYS, SCALE_LABELS
from app.models import DiagSession
from app.report import pipeline
from app.report.radar import render_radar_svg


def make_session(mode="quick"):
    s = DiagSession(user_id="u1", mode=mode, identity="student")
    cov = {k: {"questions_asked": 2, "evidence_state": "evidenced", "done": True} for k in DIM_KEYS}
    cov["_opening"] = {"questions_asked": 2}
    cov["_current"] = None
    s.coverage_json = DiagSession.dumps(cov)
    s.profile_json = DiagSession.dumps({"goal_clear": True, "target_role": "产品经理"})
    return s


def b_results(scores: dict):
    out = {}
    for k, sc in scores.items():
        state = "evidenced" if sc is not None else "insufficient"
        out[k] = {
            "evidence_state": state,
            "score": sc,
            "core_judgement": f"{k} 判断",
            "evidence_refs": [],
            "why": "因为证据",
            "next_step": "下一步",
            "deliverable_goal": "交付物",
            "translation_rows": [],
        }
    return out


def test_totals_exclude_pending():
    scores = {"inventory": 2, "mapping": 1, "business": 2, "skills": 1, "practice": 2,
              "portfolio": None, "execution": 2}
    totals = pipeline.compute_totals(b_results(scores), make_session())
    assert totals["total"] == 10
    assert totals["max"] == 42  # 6 维已评
    assert totals["scored_count"] == 6
    assert totals["pending_dims"] == ["portfolio"]
    assert totals["completion"] == "6/7"
    assert totals["overall_judgment_allowed"]
    assert totals["valid"]  # ≥5 维已评且总提问 ≥10


def test_totals_below_four_dims_no_overall_judgment():
    scores = {"inventory": 2, "mapping": 1, "business": None, "skills": None,
              "practice": None, "portfolio": None, "execution": 3}
    totals = pipeline.compute_totals(b_results(scores), make_session())
    assert totals["scored_count"] == 3
    assert not totals["overall_judgment_allowed"]
    assert not totals["valid"]


def test_confirmed_absent_counts_in_total():
    results = b_results({k: 2 for k in DIM_KEYS})
    results["portfolio"]["evidence_state"] = "confirmed_absent"
    results["portfolio"]["score"] = 0
    totals = pipeline.compute_totals(results, make_session())
    assert totals["scored_count"] == 7
    assert totals["total"] == 12


def sample_doc(identity="student"):
    scores = {"inventory": 2, "mapping": 1, "business": 2, "skills": 1, "practice": 2,
              "portfolio": None, "execution": 2}
    results = b_results(scores)
    totals = pipeline.compute_totals(results, make_session())
    dims = []
    for k in DIM_KEYS:
        v = dict(results[k])
        v.update(
            key=k, name=DIM_BY_KEY[k]["name"], short=DIM_BY_KEY[k]["short"],
            group=DIM_BY_KEY[k]["group"], high_standard=DIM_BY_KEY[k]["high_standard"],
            pending=v["score"] is None, evidence=[],
        )
        dims.append(v)
    return {
        "meta": {
            "brand_name": "求职陪跑", "brand_tagline_en": "CAREER PACER · RUN WITH YOU",
            "display_name": "小测", "date": "2026-10-18", "identity": identity,
            "mode": "quick", "goal_clear": True, "target_role": "产品经理",
            "completion": totals["completion"], "turn_count": 16, "user_message_count": 15,
            "valid": totals["valid"], "overall_judgment_allowed": totals["overall_judgment_allowed"],
        },
        "totals": totals,
        "facts": {"profile_summary": "画像", "timeline": "来年春招", "weekly_hours": "10h",
                  "experiences": ["经历A"], "skills": ["Excel"], "job_actions": ["投递 5 份"],
                  "key_facts": ["事实1"]},
        "dimensions": dims,
        "structure": {
            "one_liner": "有素材、无成品", "keywords": ["盘点", "成品", "投递"],
            "io_interpretation": "输入强于输出", "conclusion_tags": ["有素材无成品"],
            "conclusions": [{"text": "结论一", "basis_dimensions": ["inventory"],
                             "evidence_refs": [], "confidence": "高"}],
            "constraints": [{"constraint": "时间紧", "counter": "聚焦单一方向"}],
            "interview_failure_attribution": [],
            "first_priority_action": {"gap": "无成品", "action": "整理一份复盘文档",
                                      "reason": "缺口最大", "time_cost": "4 小时",
                                      "sample": "一页 PDF"},
        },
        "narrative1": {
            "exec_summary": "总结", "strengths": [{"title": "执行力", "detail": "有证据"}],
            "to_fill": ["还没开始做作品集"], "potential_direction": "产品方向",
            "one_sentence_for_you": "慢慢来，比较快。",
            "snapshot": {"rows": [{"label": "学校", "value": "某大学"}]},
            "environment_observation": "", "highlights": [{"title": "好奇心", "detail": "强"}],
        },
        "narrative2": {
            "week_actions": [{"action": "动作一", "why": "理由", "deliverable_template": "STAR 模板"}],
            "ninety_day_plan": [{"phase": "第1-4周", "focus": "作品", "actions": ["做复盘"]}],
            "weekly_rhythm": "每周三小时", "kanban_checklist": ["更新简历"],
            "retest_advice": "一个月后复测", "ending_letter": "致小测：\n加油。",
        },
        "memorable_quotes": [],
        "radar_svg": render_radar_svg(
            [{"short": d["short"], "score": d["score"], "pending": d["pending"]} for d in dims]
        ),
        "scale_labels": SCALE_LABELS,
        "band_table": BAND_TABLE,
    }


def test_render_report_assertions():
    doc = sample_doc()
    html = pipeline.render_report_html(doc)
    # 9 章 + 4 区块锚点齐全
    for anchor in ["summary", "c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8", "c9", "sharecard"]:
        assert f'id="{anchor}"' in html, f"缺少锚点 {anchor}"
    # 总分=已评维度之和，待核实不计入
    assert ">10</span>" in html and "/ 42" in html
    assert "待核实" in html
    # 雷达 SVG 存在
    assert "<svg" in html
    # 黑名单词不出现（通用）
    for banned in ["家长", "最刺眼", "请勿转发", "仅限内部"]:
        assert banned not in html, f"黑名单词出现: {banned}"
    # AI 标识
    assert 'name="generator" content="AI"' in html
    assert "AI 生成" in html


def test_render_professional_variant_blacklist():
    doc = sample_doc(identity="professional")
    doc["meta"]["identity"] = "professional"
    doc["structure"]["interview_failure_attribution"] = [
        {"possible_cause": "案例深度不足", "verify_method": "找从业者 mock 一次"}
    ]
    html = pipeline.render_report_html(doc)
    for banned in ["学员", "同学", "在校"]:
        assert banned not in html, f"社招版黑名单词出现: {banned}"
    assert "面试挂点归因" in html
    assert "职业履历卡" in html


def test_scrub_blacklist():
    text = "家长请注意，这是最刺眼的问题"
    out = pipeline.scrub_blacklist(text, "student")
    assert "家长" not in out and "最刺眼" not in out


def test_scrub_blacklist_env_extra():
    # conftest 注入 BLACKLIST_EXTRA=测试敏感词=安全替换
    out = pipeline.scrub_blacklist("这里有测试敏感词出现", "student")
    assert "测试敏感词" not in out and "安全替换" in out
