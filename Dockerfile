# Multi-stage secure build for Analytics Platform API (Cloud Firestore-backed)
FROM python:3.10-slim as builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.lock .
RUN pip install --no-cache-dir --prefix=/install -r requirements.lock

# Runtime stage
FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8000

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged service user
RUN groupadd -g 10001 analytics && \
    useradd -u 10001 -g analytics -s /bin/false -M analytics

COPY --from=builder /install /usr/local
COPY api /app/api
COPY dashboard /app/dashboard

USER analytics:analytics

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health/live || exit 1

CMD ["sh", "-c", "uvicorn api.app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
