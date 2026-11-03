FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt \
    && pip install gunicorn "psycopg2-binary" "celery[redis]" redis dj-database-url whitenoise

COPY . /app

RUN mkdir -p /app/staticfiles /app/media \
    && useradd -m appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
