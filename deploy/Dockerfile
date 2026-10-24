# The smart home server. Build and run from the repository root:
#   docker compose -f deploy/docker-compose.yml up -d --build
# Runs as a non-root user; application files are read-only to it (SEC-52).
# The database, its backups and nothing else live in /app/data (a volume).

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATABASE_URL=sqlite:////app/data/smart_home.db \
    BACKUP_DIR=/app/data/backups

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --require-hashes -r /tmp/requirements.txt && rm /tmp/requirements.txt

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin smarthome \
    && mkdir -p /app/data \
    && chown smarthome:smarthome /app/data

COPY backend/ /app/backend/
COPY web/ /app/web/

WORKDIR /app/backend
USER smarthome
EXPOSE 8000

# Something is listening on the port (HTTP or HTTPS, whichever is on).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8000), 3).close()"]

# serve.py brings the database up to date, then serves HTTPS if it is turned
# on in Settings > Admin (restart the container after changing it), else HTTP.
CMD ["python", "scripts/serve.py", "--host", "0.0.0.0", "--port", "8000"]
