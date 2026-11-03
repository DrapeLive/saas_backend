# syntax=docker/dockerfile:1.7

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings

WORKDIR /app

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --no-create-home app

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY --chown=app:app . .

RUN chmod +x /app/docker-entrypoint.sh \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R app:app /app/staticfiles /app/media

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8000), 3).close()"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
