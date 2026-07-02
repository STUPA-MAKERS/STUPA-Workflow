"""Runtime configuration: how to reach the database.

Resolution order (first hit wins for the direct DSN):

1. ``DATABASE_URL`` in the process environment — explicit override.
2. ``deploy/.env`` — the stack's own ``DATABASE_URL`` (or, failing that, one
   built from ``POSTGRES_USER``/``POSTGRES_PASSWORD``/``POSTGRES_DB``),
   rewritten to ``localhost:<host port>``: the driver suffix (``+asyncpg``) is
   stripped and host/port are replaced with the postgres host-port published in
   ``deploy/docker-compose.yml`` (``127.0.0.1:5433:5432`` → ``5433``). That way
   the CLI connects out of the box on the VM, and anywhere else once the port
   is SSH-forwarded.
3. No DSN at all → the caller falls back to
   ``docker compose exec -T <service> psql`` (see :mod:`db`).

Everything here is stdlib-only and side-effect free; :func:`resolve` reports
how it decided through :attr:`Config.notes`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

DEFAULT_COMPOSE_FILE = "deploy/docker-compose.yml"
DEFAULT_SERVICE = "postgres"
DEFAULT_HOST_PORT = 5433  # matches the ports: entry in deploy/docker-compose.yml
_CONTAINER_PORT = 5432


@dataclass(frozen=True)
class Config:
    """The resolved database access configuration."""

    database_url: str | None  # direct DSN to try first, if any
    dsn_source: str  # "environment" | "deploy/.env" | ""
    compose_file: str
    service: str
    pg_user: str | None
    pg_db: str
    read_only: bool
    notes: list[str] = field(default_factory=list)  # how the DSN was derived

    @property
    def display_url(self) -> str:
        """The DSN with the password masked, for headers and logs."""
        return mask_dsn(self.database_url) if self.database_url else "—"


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a ``KEY=VALUE`` env file (comments, blanks, quotes, ``export``).

    Inline comments are stripped only when preceded by whitespace, so values
    containing ``#`` (e.g. passwords) survive.
    """
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if value[:1] in ("'", '"'):
            # Quoted: cut at the matching closing quote (anything after it —
            # e.g. an inline comment — is discarded).
            closing = value.find(value[0], 1)
            value = value[1:closing] if closing != -1 else value[1:]
        else:
            # Unquoted: strip a trailing inline comment (whitespace + '#…').
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[key] = value
    return values


def compose_host_port(compose_path: Path, service: str) -> int | None:
    """The host port the *service* publishes for Postgres (container port 5432).

    A deliberately small line-scanner for the short ``ports:`` syntax — enough
    for this repo's compose file, no YAML dependency:

    - ``- "127.0.0.1:5433:5432"`` → 5433
    - ``- "5433:5432"``           → 5433
    - ``- "5432"``                → 5432 (host == container)
    """
    try:
        lines = compose_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    in_service = False
    in_ports = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        # A two-space-indented `name:` line starts a new service block.
        if indent == 2 and stripped.endswith(":") and not stripped.startswith("-"):
            in_service = stripped[:-1] == service
            in_ports = False
            continue
        if not in_service:
            continue
        if stripped == "ports:":
            in_ports = True
            continue
        if in_ports:
            if not stripped.startswith("-"):
                in_ports = False  # left the ports list (next mapping key)
                continue
            entry = stripped[1:].strip().strip("'\"")
            entry = entry.split("/", 1)[0]  # drop a /tcp | /udp suffix
            parts = entry.split(":")
            if len(parts) == 1 and parts[0].isdigit():
                if int(parts[0]) == _CONTAINER_PORT:
                    return _CONTAINER_PORT
                continue
            if len(parts) >= 2 and parts[-1].isdigit() and parts[-2].isdigit():
                container, host = int(parts[-1]), int(parts[-2])
                if container == _CONTAINER_PORT:
                    return host
    return None


def rewrite_dsn(dsn: str, host: str, port: int) -> str | None:
    """Rewrite *dsn* to a plain-psycopg DSN pointing at ``host:port``.

    Strips an SQLAlchemy driver suffix (``postgresql+asyncpg`` → ``postgresql``)
    and replaces the network location while keeping credentials, database and
    query string. Returns ``None`` for something that is not a postgres URL.
    """
    try:
        split = urlsplit(dsn)
    except ValueError:
        return None
    scheme = split.scheme.split("+", 1)[0]
    if scheme not in ("postgresql", "postgres"):
        return None
    credentials, _, _ = split.netloc.rpartition("@")
    netloc = f"{credentials}@{host}:{port}" if credentials else f"{host}:{port}"
    return urlunsplit(("postgresql", netloc, split.path, split.query, split.fragment))


def build_dsn(user: str, password: str, db: str, host: str, port: int) -> str:
    """Assemble a DSN from the discrete ``POSTGRES_*`` variables."""
    from urllib.parse import quote

    auth = quote(user, safe="") + (f":{quote(password, safe='')}" if password else "")
    return f"postgresql://{auth}@{host}:{port}/{quote(db, safe='')}"


def mask_dsn(dsn: str) -> str:
    """Replace the password part of *dsn* with ``•••`` for display.

    Handles URL DSNs (including passwords containing ``@``/``:`` and empty
    usernames) and keyword-form conninfo strings (``password=…``).
    """
    masked = re.sub(r"(password\s*=\s*)\S+", r"\1•••", dsn)
    try:
        split = urlsplit(masked)
    except ValueError:
        return masked
    if "@" not in split.netloc:
        return masked
    credentials, _, hostport = split.netloc.rpartition("@")
    if ":" not in credentials:
        return masked
    user = credentials.split(":", 1)[0]
    return urlunsplit(
        (split.scheme, f"{user}:•••@{hostport}", split.path, split.query, split.fragment)
    )


def _locate(base: Path, relative: str) -> Path:
    """Resolve *relative* against *base* or the nearest ancestor that has it.

    Lets the CLI run from anywhere inside the repo (or a subdirectory of it)
    instead of only from the repo root.
    """
    for parent in (base, *base.parents):
        candidate = parent / relative
        if candidate.exists():
            return candidate
    return base / relative


def normalize_dsn(dsn: str) -> str:
    """Strip an SQLAlchemy driver suffix (``postgresql+asyncpg`` → ``postgresql``).

    Applied to explicit ``$DATABASE_URL`` overrides too, so the stack's
    canonical ``postgresql+asyncpg://…`` form can be pasted verbatim.
    Non-URL conninfo strings (``host=… password=…``) pass through untouched.
    """
    try:
        split = urlsplit(dsn)
    except ValueError:
        return dsn
    scheme, _, _driver = split.scheme.partition("+")
    if not _driver or scheme not in ("postgresql", "postgres"):
        return dsn
    return urlunsplit((scheme, split.netloc, split.path, split.query, split.fragment))


def resolve(*, read_only: bool = False, cwd: Path | None = None) -> Config:
    """Work out how to reach the database (see the module docstring)."""
    base = cwd or Path.cwd()
    compose_file = os.environ.get("COMPOSE_FILE", DEFAULT_COMPOSE_FILE)
    compose_path = Path(compose_file)
    if not compose_path.is_absolute():
        compose_path = _locate(base, compose_file)
    service = os.environ.get("POSTGRES_SERVICE", DEFAULT_SERVICE)
    env_file = Path(os.environ.get("ENV_FILE", str(compose_path.parent / ".env")))

    notes: list[str] = []
    stack_env = parse_env_file(env_file)
    pg_user = os.environ.get("POSTGRES_USER") or stack_env.get("POSTGRES_USER")
    pg_db = os.environ.get("POSTGRES_DB") or stack_env.get("POSTGRES_DB") or "antrag"

    # 1. Explicit override (driver suffix stripped so the stack's canonical
    #    postgresql+asyncpg://… form works verbatim).
    override = os.environ.get("DATABASE_URL")
    if override:
        notes.append("DATABASE_URL taken from the environment")
        return Config(
            database_url=normalize_dsn(override),
            dsn_source="environment",
            compose_file=str(compose_path),
            service=service,
            pg_user=pg_user,
            pg_db=pg_db,
            read_only=read_only,
            notes=notes,
        )

    # 2. deploy/.env, rewritten to localhost + the published compose port.
    port = compose_host_port(compose_path, service)
    if port is None:
        port = DEFAULT_HOST_PORT
        port_note = f"assuming localhost:{port} (no published port found)"
    else:
        port_note = f"localhost:{port} (published in {compose_path.name})"

    dsn: str | None = None
    stack_url = stack_env.get("DATABASE_URL")
    if stack_url:
        dsn = rewrite_dsn(stack_url, "localhost", port)
        if dsn:
            notes.append(f"DATABASE_URL from {env_file} → {port_note}")
    if dsn is None and pg_user and stack_env.get("POSTGRES_PASSWORD"):
        dsn = build_dsn(pg_user, stack_env["POSTGRES_PASSWORD"], pg_db, "localhost", port)
        notes.append(f"POSTGRES_* from {env_file} → {port_note}")
    if dsn is None:
        notes.append(
            f"no usable credentials in {env_file} — docker exec fallback only"
        )

    return Config(
        database_url=dsn,
        dsn_source="deploy/.env" if dsn else "",
        compose_file=str(compose_path),
        service=service,
        pg_user=pg_user,
        pg_db=pg_db,
        read_only=read_only,
        notes=notes,
    )


__all__ = [
    "Config",
    "DEFAULT_COMPOSE_FILE",
    "DEFAULT_HOST_PORT",
    "DEFAULT_SERVICE",
    "build_dsn",
    "compose_host_port",
    "mask_dsn",
    "normalize_dsn",
    "parse_env_file",
    "resolve",
    "rewrite_dsn",
]
