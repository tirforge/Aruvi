# Stage 1: Build React frontend (vite outDir writes to ../backend/app/static)
FROM node:20-slim AS frontend-builder
WORKDIR /repo/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2: Python backend + serve frontend
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    g++ \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend/ /app
# Copy built frontend into backend's static directory (served by FastAPI)
COPY --from=frontend-builder /repo/backend/app/static/ /app/app/static/

WORKDIR /app
RUN mkdir -p /app/data /app/session /app/data/vcache

ENV SERVER_PORT=7680
EXPOSE 7680

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -sf http://localhost:7680/health || exit 1

CMD ["python", "run.py"]
