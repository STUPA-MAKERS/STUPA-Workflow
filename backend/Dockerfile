# Backend-Image (api + worker teilen sich dieses Image; Command unterscheidet).
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# System-Lib für MIME-Sniffing (python-magic → libmagic, T-13). apt-Listen danach
# entfernen (kleines Image).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Dependencies in eigener Layer VOR dem Quellcode: ein Code-Change invalidiert
# damit nur den (sekundenschnellen) App-Install unten, nicht den Dep-Download.
# Die Dep-Liste kommt direkt aus pyproject.toml (tomllib, stdlib) — keine
# separate requirements.txt zu pflegen. Zusätzlich BuildKit-Cache-Mount für den
# pip-Wheel-Cache: auch wenn diese Layer invalidiert (Dep-Bump), wird nichts
# erneut heruntergeladen, was schon einmal gebaut/geladen wurde.
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Quellcode + Alembic-Config/Migrationen (Issue #38: ohne sie kann der Container
# kein `alembic upgrade head` ausführen → frische DB bliebe leer. env.py importiert
# app.models/app.settings (via pip install . verfügbar), prepend_sys_path=. ⇒ /app).
COPY app ./app
COPY worker ./worker
COPY alembic.ini ./
COPY migrations ./migrations
# Deps stecken in der Layer oben → hier nur noch das Paket selbst (schnell).
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-deps .

EXPOSE 8000

# Default: API. Worker überschreibt command in compose.
# forwarded-allow-ips eng (security.md §3): nie "*"; Default loopback, real per FORWARDED_ALLOW_IPS (NPM-Netz).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]
