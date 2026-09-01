# Backend image. The api and worker services share it. The compose file overrides the
# command for the worker.
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# System libraries:
# - libmagic1: MIME sniffing for python-magic (T-13).
# - postgresql-client-16: `pg_dump` and `pg_restore` for /admin/backups. The version
#   MUST match the server major (compose runs postgres:16-alpine). A pg_dump older than
#   the server refuses to run, so the pin is not cosmetic. The Debian package comes from
#   the PostgreSQL APT repository, because trixie ships a different major.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 ca-certificates curl gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo $VERSION_CODENAME)-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && apt-get purge -y curl gnupg \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Install the dependencies in their own layer before the source code. A code change then
# invalidates only the fast app install below, not the dependency download. tomllib in the
# standard library reads the dependency list from pyproject.toml, so this image needs no
# separate requirements.txt. The BuildKit cache mount holds the pip wheel cache. A dependency
# bump invalidates this layer, but pip does not fetch or build again what it already has.
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# The image also needs the alembic config and the migrations (issue #38). Without them the
# container cannot run `alembic upgrade head` and a fresh database stays empty. The alembic
# env.py file imports app.models and app.settings, which `pip install .` makes available.
# The setting `prepend_sys_path=.` resolves to /app.
COPY app ./app
COPY worker ./worker
COPY alembic.ini ./
COPY migrations ./migrations
# The dependencies come from the layer above, so install only the package itself.
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-deps .

# Defense in depth (#sec-audit): do not run as root. At run time the container needs read
# access to /app only, for the code and the migrations. Multipart uploads spool to /tmp,
# which is world-writable. This holds for api, worker and the migrate one-shot, because
# alembic writes to the database only.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# Keep forwarded-allow-ips narrow (security.md §3). Never set it to "*". The default is
# loopback. Production passes the NPM network through FORWARDED_ALLOW_IPS.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]
