"""网关怪癖清洗：gemini user 消息的 score 零宽处理，且不破坏引语核验。"""
from app.llm.client import _sanitize_for_gateway
from app.report import quote_check


def test_gemini_user_score_sanitized():
    msgs = [
        {"role": "system", "content": "score 规则"},
        {"role": "user", "content": "我的 TOEFL score 是 100，Score 不低"},
        {"role": "assistant", "content": "score ok"},
    ]
    out = _sanitize_for_gateway("gemini-4-argon", msgs)
    assert "score" not in out[1]["content"] and "Score" not in out[1]["content"]
    assert "s​core" in out[1]["content"]
    # system / assistant 不动
    assert out[0]["content"] == "score 规则"
    assert out[2]["content"] == "score ok"


def test_other_models_untouched():
    msgs = [{"role": "user", "content": "score"}]
    assert _sanitize_for_gateway("deepseek-v4-flash", msgs)[0]["content"] == "score"
    assert _sanitize_for_gateway("kimi-k3", msgs)[0]["content"] == "score"


def test_quote_check_strips_zero_width():
    original = "我的 TOEFL score 是 100"
    quote_with_zwsp = "我的 TOEFL s​core 是 100"
    ok, _ = quote_check.verify_quote(quote_with_zwsp, 3, {3: original})
    assert ok
