# Backend-Image (api + worker teilen sich dieses Image; Command unterscheidet).
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System-Lib für MIME-Sniffing (python-magic → libmagic, T-13). apt-Listen danach
# entfernen (kleines Image).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Deps zuerst (Layer-Cache).
COPY pyproject.toml ./
COPY app ./app
COPY worker ./worker
# Alembic-Config + Migrationen ins Image (Issue #38): ohne sie kann der Container
# kein `alembic upgrade head` ausführen → frische DB bliebe leer. env.py importiert
# app.models/app.settings (via pip install . verfügbar), prepend_sys_path=. ⇒ /app.
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install .

EXPOSE 8000

# Default: API. Worker überschreibt command in compose.
# forwarded-allow-ips eng (security.md §3): nie "*"; Default loopback, real per FORWARDED_ALLOW_IPS (NPM-Netz).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]
