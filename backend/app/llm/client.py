"""AI Builders 网关封装（02-技术设计 §8）。

- chat_json：json_object 模式 + Pydantic 校验失败回传修复重试 1 次
- 网络/5xx 指数退避重试 2 次
- 模型怪癖表：kimi/gpt-5/gpt-6 不传 temperature、max_tokens 兜底 ≥1024
- 每次调用写 events(llm_call)
- 发送前程序脱敏：手机号/邮箱/微信号
"""
import asyncio
import json
import logging
import re
import time
from typing import Any

from openai import APIError, APITimeoutError, AsyncOpenAI, RateLimitError

from ..analytics import track
from ..config import get_settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.ai_builder_token or "missing-token",
        )
    return _client


# 强制 temperature=1.0（参数不传）且 max_tokens≥1024 的模型前缀
_NO_TEMP_PREFIXES = ("kimi", "gpt-5", "gpt-6")

# 网关怪癖（2026-10 实测）：gemini 系模型的 user 消息含字面量 "score" 时，
# 网关报 400 "Requests ending with a model turn are not supported"（system/assistant 不受影响，
# 其他模型不受影响）。对策：给 user 消息中的 score 插入零宽空格，语义与显示均不变；
# quote_check.normalize 会剥掉零宽字符，引语核验不受影响。
_GEMINI_SCORE_RE = re.compile(r"(?i)s(core)")


def _sanitize_for_gateway(model: str, messages: list[dict]) -> list[dict]:
    if not model.startswith("gemini"):
        return messages
    out = []
    for m in messages:
        content = m.get("content")
        if m.get("role") == "user" and isinstance(content, str):
            m = {**m, "content": _GEMINI_SCORE_RE.sub("s​\\1", content)}
        out.append(m)
    return out

_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_WECHAT_RE = re.compile(r"(?:微信|vx|wx|weixin)[\s:：号]*([a-zA-Z][\w-]{5,19})", re.I)


def redact_pii(text: str) -> str:
    text = _PHONE_RE.sub("[手机号]", text)
    text = _EMAIL_RE.sub("[邮箱]", text)
    text = _WECHAT_RE.sub(lambda m: m.group(0).replace(m.group(1), "[微信号]"), text)
    return text


def _apply_quirks(model: str, temperature: float | None, max_tokens: int) -> dict:
    kwargs: dict[str, Any] = {"max_tokens": max_tokens}
    if model.startswith(_NO_TEMP_PREFIXES):
        kwargs["max_tokens"] = max(max_tokens, 1024)
    elif temperature is not None:
        kwargs["temperature"] = temperature
    return kwargs


class LLMError(Exception):
    pass


class EmptyContentError(LLMError):
    """空内容（常见于思考型模型 max_tokens 被思考耗尽），可重试。"""


async def _chat_once(
    model: str,
    messages: list[dict],
    temperature: float | None,
    max_tokens: int,
    timeout: float,
    json_mode: bool,
    *,
    stage: str,
    session_id: str | None,
    user_id: str | None,
) -> str:
    kwargs = _apply_quirks(model, temperature, max_tokens)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    started = time.monotonic()
    resp = await get_client().chat.completions.create(
        model=model,
        messages=_sanitize_for_gateway(model, messages),
        timeout=timeout,
        **kwargs,
    )
    latency = round(time.monotonic() - started, 2)
    usage = getattr(resp, "usage", None)
    track(
        "llm_call",
        user_id=user_id,
        session_id=session_id,
        props={
            "model": model,
            "stage": stage,
            "latency": latency,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
        },
    )
    content = resp.choices[0].message.content
    if not content:
        finish = getattr(resp.choices[0], "finish_reason", None)
        raise EmptyContentError(f"{model} 返回空内容（finish_reason={finish}）")
    return content


async def _chat_with_backoff(**kw) -> str:
    delay = 2.0
    for attempt in range(3):
        try:
            return await _chat_once(**kw)
        except EmptyContentError as exc:
            # 空内容重试时加大 token 预算（思考型模型思考会吃掉预算）
            if attempt == 2:
                raise
            kw = {**kw, "max_tokens": kw.get("max_tokens", 2048) * 2}
            logger.warning("%s；加倍 max_tokens 至 %s 重试", exc, kw["max_tokens"])
        except (APITimeoutError, RateLimitError, APIError) as exc:
            status = getattr(exc, "status_code", None)
            retriable = isinstance(exc, (APITimeoutError, RateLimitError)) or (
                status is not None and status >= 500
            )
            if not retriable or attempt == 2:
                raise LLMError(f"LLM 调用失败: {exc}") from exc
            await asyncio.sleep(delay)
            delay *= 2
    raise LLMError("unreachable")


def extract_json(text: str) -> dict:
    """容错解析：剥 markdown 代码栅栏、截取首尾花括号。"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


async def chat_json(
    model: str,
    messages: list[dict],
    *,
    schema_hint: str = "",
    validator=None,
    temperature: float | None = None,
    max_tokens: int = 2048,
    timeout: float = 60.0,
    stage: str = "",
    session_id: str | None = None,
    user_id: str | None = None,
) -> Any:
    """请求 JSON 输出；validator(dict)->obj 校验失败时把错误回传修复重试 1 次。"""
    msgs = list(messages)
    if schema_hint:
        msgs = [dict(m) for m in messages]
        msgs[0] = {
            "role": "system",
            "content": msgs[0]["content"] + "\n\n# 输出 JSON 格式要求\n" + schema_hint,
        }
    last_error: Exception | None = None
    for attempt in range(2):
        raw = await _chat_with_backoff(
            model=model,
            messages=msgs,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            json_mode=True,
            stage=stage,
            session_id=session_id,
            user_id=user_id,
        )
        try:
            data = extract_json(raw)
            return validator(data) if validator else data
        except Exception as exc:  # 解析/校验失败 → 修复重试
            last_error = exc
            logger.warning("chat_json 校验失败（第 %d 次）: %s", attempt + 1, exc)
            msgs = msgs + [
                {"role": "assistant", "content": raw[:4000]},
                {
                    "role": "user",
                    "content": f"上面的输出不符合要求：{exc}。请严格按照格式要求重新输出完整 JSON，不要输出任何其他内容。",
                },
            ]
    raise LLMError(f"JSON 校验失败且修复重试无效: {last_error}")


async def chat_text(
    model: str,
    messages: list[dict],
    *,
    temperature: float | None = None,
    max_tokens: int = 4096,
    timeout: float = 120.0,
    stage: str = "",
    session_id: str | None = None,
    user_id: str | None = None,
) -> str:
    return await _chat_with_backoff(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        json_mode=False,
        stage=stage,
        session_id=session_id,
        user_id=user_id,
    )
