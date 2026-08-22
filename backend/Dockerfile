FROM python:3.13-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libc6-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi8 libssl3 ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH \
    SERVER_PORT=7680

WORKDIR /app
COPY run.py ./
COPY app/ ./app/
RUN mkdir -p /app/data /app/session /app/data/vcache

EXPOSE 7680

# run.py (not bare uvicorn): it disables uvicorn's signal capture for the
# Python 3.13 workaround and runs the periodic housekeeping task (msg-cache
# prune, stale RAM cache eviction) that app.main does not start itself.
CMD ["python", "run.py"]
