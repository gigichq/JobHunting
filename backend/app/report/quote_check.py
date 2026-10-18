"""程序级幻觉防线（02-技术设计 §10 quote_check 升级版）。

规则：
- 每条 quote 必须绑定 message_id 且该消息 role=user（AI 发言不作证据）
- 归一化（去空白/标点/全半角/小写）后子串匹配；失败再做 85% 相似度模糊匹配
- 数字与否定词必须精确一致：数字 token 或否定词不一致即判不命中
- 不命中 → 剔除或标「待确认」，绝不自动转述保留
"""
import difflib
import re
import unicodedata

NEGATION_WORDS = ["没有", "没做过", "没", "不是", "不会", "不", "未", "无"]
_DIGIT_RE = re.compile(r"\d+(?:\.\d+)?")
_PUNCT_RE = re.compile(r"[\s　!-/:-@\[-`{-~。，、；：？！…—·「」『』（）《》【】“”‘’\"']+")

FUZZY_THRESHOLD = 0.85


def normalize(text: str) -> str:
    """全角→半角、去空白与标点、小写。"""
    text = unicodedata.normalize("NFKC", text)
    text = _PUNCT_RE.sub("", text)
    return text.lower()


def digit_tokens(text: str) -> list[str]:
    return _DIGIT_RE.findall(unicodedata.normalize("NFKC", text))


def _negation_signature(text: str) -> list[int]:
    """各否定词出现次数（有序，长词先匹配并抹除避免「没有」重复计「没」）。"""
    sig = []
    remaining = text
    for w in NEGATION_WORDS:
        sig.append(remaining.count(w))
        remaining = remaining.replace(w, "◆")
    return sig


def _strict_tokens_consistent(quote: str, message: str) -> bool:
    """数字与否定词精确一致性：引语中的每个数字必须原样出现在原消息中；
    引语含否定词时，原消息必须覆盖同样的否定表达。"""
    q_digits = digit_tokens(quote)
    m_digits = digit_tokens(message)
    m_pool = list(m_digits)
    for d in q_digits:
        if d in m_pool:
            m_pool.remove(d)
        else:
            return False
    q_neg = _negation_signature(normalize(quote))
    m_neg = _negation_signature(normalize(message))
    for q_count, m_count in zip(q_neg, m_neg):
        if q_count > m_count:
            return False
    return True


def quote_matches(quote: str, message: str) -> bool:
    """单条引语 vs 单条用户消息。"""
    if not quote or not message:
        return False
    nq, nm = normalize(quote), normalize(message)
    if not nq:
        return False
    if not _strict_tokens_consistent(quote, message):
        return False
    if nq in nm:
        return True
    # 模糊匹配：滑动窗口取最优相似度
    window = len(nq)
    if window > len(nm):
        return difflib.SequenceMatcher(None, nq, nm).ratio() >= FUZZY_THRESHOLD
    step = max(1, window // 4)
    best = 0.0
    for start in range(0, len(nm) - window + 1, step):
        ratio = difflib.SequenceMatcher(None, nq, nm[start : start + window + step]).ratio()
        best = max(best, ratio)
        if best >= FUZZY_THRESHOLD:
            return True
    return best >= FUZZY_THRESHOLD


def verify_quote(
    quote: str | None, message_id: int | None, user_messages: dict[int, str]
) -> tuple[bool, str]:
    """返回 (命中与否, 原因)。user_messages: {seq: content}（仅 role=user）。"""
    if quote is None:
        return True, "no_quote"
    if message_id is None:
        return False, "missing_message_id"
    message = user_messages.get(message_id)
    if message is None:
        return False, "message_not_user_or_missing"
    if quote_matches(quote, message):
        return True, "hit"
    return False, "mismatch"
