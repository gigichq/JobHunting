# 多阶段构建：node 构建前端 → python:3.11-slim 运行（运行镜像不含 node）
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY --from=frontend /build/dist ./frontend/dist
WORKDIR /app/backend
# 平台要求：CMD 必须 shell form 以展开 ${PORT}
CMD sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"
