"""quote_check：幻觉引语防线（数字/否定词精确一致、归一化、模糊匹配）。"""
from app.report import quote_check


def test_exact_substring_hit():
    msg = {3: "我在社团里负责了一场 200 人的活动，拉到了三家赞助。"}
    ok, reason = quote_check.verify_quote("负责了一场 200 人的活动", 3, msg)
    assert ok


def test_normalization_tolerates_punctuation_and_width():
    msg = {3: "我投了大概３０份简历，基本没有回音。"}
    ok, _ = quote_check.verify_quote("投了大概30份简历", 3, msg)
    assert ok


def test_digit_mismatch_rejected():
    msg = {3: "我们卖了 60 张票。"}
    ok, _ = quote_check.verify_quote("我们卖了 600 张票", 3, msg)
    assert not ok


def test_negation_mismatch_rejected():
    msg = {3: "我做过完整的用户调研。"}
    ok, _ = quote_check.verify_quote("我没做过完整的用户调研", 3, msg)
    assert not ok


def test_negation_preserved_hit():
    msg = {3: "说实话我没做过任何复盘。"}
    ok, _ = quote_check.verify_quote("我没做过任何复盘", 3, msg)
    assert ok


def test_fuzzy_match_above_threshold():
    msg = {3: "大二暑假我在一家快消公司做市场部实习生，主要支持新品上市。"}
    # 少量字符差异（≥85% 相似）应命中
    ok, _ = quote_check.verify_quote("我在一家快消公司做市场部实习生，主要支持新品上市", 3, msg)
    assert ok


def test_fabricated_quote_rejected():
    msg = {3: "我学过一点 Excel。"}
    ok, _ = quote_check.verify_quote("我精通 Python 和 SQL，做过三个数据项目", 3, msg)
    assert not ok


def test_missing_message_id_rejected():
    ok, reason = quote_check.verify_quote("随便一句", None, {1: "随便一句"})
    assert not ok and reason == "missing_message_id"


def test_ai_message_not_usable():
    # user_messages 只含 user 消息；指向不存在的 seq（即 AI 消息）→ 拒绝
    ok, reason = quote_check.verify_quote("你的优势是执行力", 2, {1: "别的话"})
    assert not ok and reason == "message_not_user_or_missing"


def test_no_quote_passes_through():
    ok, reason = quote_check.verify_quote(None, None, {})
    assert ok and reason == "no_quote"
