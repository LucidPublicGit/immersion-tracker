FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CONFIG_PATH=/app/config/settings.yaml \
    DATABASE_URL=sqlite:////app/data/immersion.db

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config ./config
COPY scripts ./scripts
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh \
    && mkdir -p /app/data /app/data/tadoku_export \
    && cp /app/config/settings.example.yaml /app/config/settings.yaml

EXPOSE 8000

# Longer timeout: enrich / external metadata can block the single worker briefly
HEALTHCHECK --interval=30s --timeout=15s --start-period=40s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
