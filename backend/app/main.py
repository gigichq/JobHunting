"""FastAPI 入口：/api 路由注册、Vite dist 静态托管 + SPA catch-all、启动回收任务。"""
import logging
import os
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import analytics
from .auth import router as auth_router
from .config import get_settings
from .database import engine
from .interview import router as interview_router
from .models import Base
from .report import pipeline
from .report import router as report_router

# 结构化日志但不落对话明文（各模块只记 id 与元信息）
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    pipeline.recover_stuck_reports()  # 启动扫描：回收心跳失效的生成任务
    yield


app = FastAPI(title="求职陪跑", docs_url=None, redoc_url=None, lifespan=lifespan)

app.include_router(auth_router.router)
app.include_router(interview_router.router)
app.include_router(report_router.router)
app.include_router(analytics.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


_models_cache: dict = {"data": None, "at": 0.0}


@app.get("/api/meta/models")
async def meta_models():
    """代理网关 /v1/models，缓存 1h。"""
    settings = get_settings()
    if _models_cache["data"] and time.time() - _models_cache["at"] < 3600:
        return _models_cache["data"]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{settings.llm_base_url}/models",
                headers={"Authorization": f"Bearer {settings.ai_builder_token}"},
            )
            resp.raise_for_status()
            _models_cache["data"] = resp.json()
            _models_cache["at"] = time.time()
            return _models_cache["data"]
    except httpx.HTTPError:
        return JSONResponse({"data": [], "error": "models 拉取失败"}, status_code=502)


# ---- 前端静态托管（Vite 构建产物）+ SPA catch-all ----
FRONTEND_DIST = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
)

if os.path.isdir(os.path.join(FRONTEND_DIST, "assets")):
    app.mount(
        "/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets"
    )


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    candidate = os.path.normpath(os.path.join(FRONTEND_DIST, full_path))
    if (
        full_path
        and candidate.startswith(FRONTEND_DIST)
        and os.path.isfile(candidate)
    ):
        return FileResponse(candidate)
    index = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.isfile(index):
        return FileResponse(index)
    return JSONResponse(
        {"detail": "前端未构建：请先在 frontend/ 运行 npm run build"}, status_code=404
    )
