# Backend-Image (api + worker teilen sich dieses Image; Command unterscheidet).
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Deps zuerst (Layer-Cache).
COPY pyproject.toml ./
COPY app ./app
COPY worker ./worker
RUN pip install .

EXPOSE 8000

# Default: API. Worker überschreibt command in compose.
# forwarded-allow-ips eng (security.md §3): nie "*"; Default loopback, real per FORWARDED_ALLOW_IPS (NPM-Netz).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]
