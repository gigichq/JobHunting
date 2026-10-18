# 求职陪跑 · CAREER PACER

AI 求职准备度诊断：与 AI 诊断师完成一场结构化对话，自动生成咨询级《求职准备度诊断报告》——七个维度、0–7 分，每一分都有用户原话做证据。

> **AI 生成内容声明**：本产品的对话与报告由 AI 生成，为单次对话观察的参考意见，不构成录用预测或职业资格判断。仅服务年满 18 周岁用户。

## 技术栈

- 后端：FastAPI + SQLAlchemy 2 + SQLite（WAL）· Python 3.11
- 前端：React 18 + TypeScript + Vite + Tailwind（构建产物由 FastAPI 静态托管，单进程单端口）
- LLM：AI Builders 网关（OpenAI 兼容）——对话 `deepseek-v4-flash` / 评分 `gemini-4-argon`（低温）/ 叙事 `kimi-k3`

## 本地开发

```bash
# 1. 后端（uv 管理 Python 3.11）
uv venv --python 3.11 .venv
uv pip install -r requirements-dev.txt --python .venv/bin/python
cp .env.example .env            # 填入 AI_BUILDER_TOKEN

# 2. 前端
cd frontend && npm install && npm run build && cd ..
#    开发时可用热更新：cd frontend && npm run dev  （proxy 到 :8000）

# 3. 启动
cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000
# 打开 http://localhost:8000
```

## 测试

```bash
cd backend && ../.venv/bin/python -m pytest tests/ -q
```

覆盖：auth 流、guards 全规则（快速通过/强制切换/轮次上限/end 前提）、quote_check（数字/否定词精确一致、幻觉引语剔除）、radar 坐标、分数汇总（待核实不计入）、模板渲染断言（章节锚点/黑名单词/双变体）。

## 容器

```bash
docker build -t career-pacer .
docker run -e PORT=8123 -e AI_BUILDER_TOKEN=xxx -p 8123:8123 career-pacer
curl http://localhost:8123/api/health
```

## 部署（space.ai-builders，上线阶段执行）

1. 建**公开** GitHub 仓库并 push（`.gitignore` 已排除 `docs/`、`.env`、`data/`——首 commit 即生效；push 前跑 PII 扫描）
2. 落地持久化方案（托管 Postgres 或 Litestream——平台文件系统 ephemeral，重部署清空 SQLite）
3. 填 `deploy-config.json` 的 `repo_url`，`POST /v1/deployments`，轮询至 HEALTHY
4. 冒烟：注册 → 快速诊断 → 报告；检查 build/runtime 日志

## 关键设计（docs/design 本地留存，不入仓库）

- 四态证据模型：evidenced / confirmed_absent（没做过≠不知道，如实计 0–1 分）/ insufficient（待核实不计分）/ not_applicable
- 证据校验前置（Stage A′）：引语绑定用户消息 ID 逐字核验，数字与否定词必须精确一致，不命中在评分前剔除
- Stage B 只读结构化证据池，评分依据必须引用证据 ID；AI辅导后产出 / AI推断不可计分
- 任务闭环：run_id + 心跳 + 原子接管 + 断点续跑 + 8 分钟总截止 + 降级简版交付
- 代码护栏：每维最少/最多提问、AI 主动结束的最低覆盖前提、总轮次上限、敷衍两次给三选项
