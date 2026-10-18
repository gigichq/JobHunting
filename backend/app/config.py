"""统一配置（02-技术设计 §5）。"""
import hashlib
import hmac
import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 在仓库根目录；无论从哪个 cwd 启动都能读到
_REPO_ROOT_ENV = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".env")
)


def _hkdf_sha256(key_material: bytes, info: bytes, length: int = 32) -> bytes:
    """RFC 5869 HKDF（extract+expand），避免引入 cryptography 依赖。"""
    prk = hmac.new(b"\x00" * 32, key_material, hashlib.sha256).digest()
    okm = b""
    block = b""
    counter = 1
    while len(okm) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        okm += block
        counter += 1
    return okm[:length]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(_REPO_ROOT_ENV, ".env"), extra="ignore")

    ai_builder_token: str = ""
    llm_base_url: str = "https://space.ai-builders.com/backend/v1"
    # 全链路默认 deepseek-v4-flash（2026-10 实测：评分方差 0、与 gemini 分差 ≤1、快 2–3 倍；
    # kimi-k3 叙事单调用 5min+ 不可用）。可用 env 换回 gemini-4-argon（评分）等
    interview_model: str = "deepseek-v4-flash"
    scoring_model: str = "deepseek-v4-flash"
    narrative_model: str = "deepseek-v4-flash"
    jwt_secret: str = ""
    db_path: str = "./data/app.db"
    brand_name: str = "求职陪跑"
    brand_tagline_en: str = "CAREER PACER · RUN WITH YOU"
    daily_session_limit: int = 3
    port: int = 8000
    # 额外黑名单替换对（敏感词不入代码库）：格式 "词=替换,词=替换"
    blacklist_extra: str = ""

    # 成本/防滥用护栏
    max_message_chars: int = 2000
    report_max_retries: int = 3
    pipeline_deadline_seconds: int = 8 * 60
    heartbeat_stale_seconds: int = 90
    user_retry_after_seconds: int = 5 * 60

    @property
    def effective_jwt_secret(self) -> str:
        if self.jwt_secret:
            return self.jwt_secret
        if self.ai_builder_token:
            return _hkdf_sha256(self.ai_builder_token.encode(), b"jwt").hex()
        # 本地无 token 的兜底（仅开发环境会走到）
        return "dev-insecure-secret"


@lru_cache
def get_settings() -> Settings:
    return Settings()
