# Backend image. The api and worker services share it. The compose file overrides the
# command for the worker.
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# System libraries:
# - libmagic1: MIME sniffing for python-magic.
# - postgresql-client-16: `pg_dump` and `pg_restore` for /admin/backups. The version
#   MUST match the server major (compose runs postgres:16-alpine). A pg_dump older than
#   the server refuses to run, so the pin is not cosmetic. The Debian package comes from
#   the PostgreSQL APT repository, because trixie ships a different major.
#
# The signing key of that repository is the file docker/apt.postgresql.org.asc
# (fingerprint B97B 0AFC AA1A 47F0 44F2 44A0 7FCC 7D46 ACCC 4CF8). The build does not
# fetch it, because one failed request to postgresql.org then holds a release back, and
# a fetched key is trusted only through TLS. apt repeats a failed download five times
# (§NF/compatibility/deploy/000978).
COPY docker/apt.postgresql.org.asc /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
RUN echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/80-retries \
    && apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 ca-certificates \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo $VERSION_CODENAME)-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
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

# The image also needs the alembic config and the migrations. Without them the
# container cannot run `alembic upgrade head` and a fresh database stays empty. The alembic
# env.py file imports app.models and app.settings, which `pip install .` makes available.
# The setting `prepend_sys_path=.` resolves to /app.
COPY app ./app
COPY worker ./worker
COPY alembic.ini ./
COPY migrations ./migrations
# The dependencies come from the layer above, so install only the package itself.
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-deps .

# Defense in depth: do not run as root. At run time the container needs read
# access to /app only, for the code and the migrations. Multipart uploads spool to /tmp,
# which is world-writable. This holds for api, worker and the migrate one-shot, because
# alembic writes to the database only.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# Keep forwarded-allow-ips narrow. Never set it to "*". The default is
# loopback. Production passes the Caddy network through FORWARDED_ALLOW_IPS.
# API_WORKERS processes serve the requests side by side (spec 002004), default 4, one per
# vCPU of the VM. The live events, the locks and the rate limits go through Redis, so any
# process can take any request. Each process has its own database pool (5 + 10).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers \"${API_WORKERS:-4}\" --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]
