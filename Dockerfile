FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system homebase && adduser --system --ingroup homebase homebase

COPY requirements.txt constraints.txt .
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

COPY . .
RUN chmod +x /app/scripts/docker-entrypoint.sh && \
    mkdir -p /data/uploads && \
    chown -R homebase:homebase /app /data

USER homebase

EXPOSE 8000

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
