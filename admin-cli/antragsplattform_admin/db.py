"""Database access — two interchangeable backends behind one tiny interface.

All call sites write SQL with ``%s`` positional placeholders and pass a params tuple:
- :class:`DirectDb` (psycopg) feeds them straight to the driver (real bind params).
- :class:`DockerDb` renders them into a literal-quoted SQL string and runs it via
  ``docker compose exec -T <service> psql`` (``--csv`` for reads). Quoting doubles single quotes;
  Postgres ``standard_conforming_strings`` is ON by default (PG16) → no backslash escaping needed.

``query`` returns ``list[dict[str, str|None]]`` (values are strings in docker mode; the UI treats
everything as text). ``execute`` returns the affected row count (best-effort in docker mode).
"""

from __future__ import annotations

import csv
import io
import re
import subprocess
from typing import Any, Protocol

from .config import Config


class DbError(RuntimeError):
    pass


class Db(Protocol):
    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]: ...
    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int: ...
    def close(self) -> None: ...
    @property
    def label(self) -> str: ...


# --------------------------------------------------------------------------- literal rendering
def sql_literal(value: Any) -> str:
    """Render a Python value as a safe Postgres SQL literal (standard_conforming_strings=on)."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def render(sql: str, params: tuple[Any, ...]) -> str:
    """Substitute ``%s`` placeholders positionally with quoted literals (docker/psql backend)."""
    parts = sql.split("%s")
    if len(parts) - 1 != len(params):
        raise DbError(f"placeholder/param mismatch: {len(parts) - 1} vs {len(params)}")
    out = [parts[0]]
    for value, tail in zip(params, parts[1:], strict=True):
        out.append(sql_literal(value))
        out.append(tail)
    return "".join(out)


# --------------------------------------------------------------------------- direct (psycopg)
class DirectDb:
    def __init__(self, dsn: str, *, connect_timeout: int = 5, label: str = "direct") -> None:
        self._label = label
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - optional dep
            raise DbError(
                "direct mode needs psycopg (pip install 'psycopg[binary]')."
            ) from exc
        try:
            self._conn = psycopg.connect(
                dsn,
                autocommit=True,
                row_factory=dict_row,
                connect_timeout=connect_timeout,
            )
        except Exception as exc:  # pragma: no cover - needs a live DB
            raise DbError(f"could not connect: {exc}") from exc

    @property
    def label(self) -> str:
        return self._label

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        try:
            with self._conn.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())
        except Exception as exc:  # psycopg errors → the DbError contract callers rely on
            raise DbError(str(exc).strip() or type(exc).__name__) from exc

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        try:
            with self._conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.rowcount
        except Exception as exc:  # psycopg errors → the DbError contract callers rely on
            raise DbError(str(exc).strip() or type(exc).__name__) from exc

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001 — closing a broken connection must not raise
            pass


# ----------------------------------------------------------------------- docker exec / psql
_TAG_RE = re.compile(r"\b(?:INSERT \d+|UPDATE|DELETE|SELECT)\s+(\d+)\b")


class DockerDb:
    def __init__(self, config: Config) -> None:
        self._cfg = config
        self._base = ["docker", "compose", "-f", config.compose_file, "exec", "-T", config.service]
        self._user = config.pg_user or self._printenv("POSTGRES_USER")
        self._db = config.pg_db or self._printenv("POSTGRES_DB")
        if not self._user:
            raise DbError("could not determine POSTGRES_USER (set it or check the running stack).")

    @property
    def label(self) -> str:
        return f"{self._cfg.service} ({self._user}/{self._db})"

    def _printenv(self, var: str) -> str:
        try:
            out = subprocess.run(
                [*self._base, "printenv", var],
                capture_output=True, text=True, timeout=30, check=False,
            )
        except FileNotFoundError as exc:
            raise DbError("docker not found on PATH.") from exc
        except subprocess.TimeoutExpired as exc:
            raise DbError(f"docker compose exec timed out reading {var}.") from exc
        return out.stdout.strip()

    def _psql(self, sql: str, *, csv_out: bool) -> str:
        cmd = [
            *self._base, "psql", "-v", "ON_ERROR_STOP=1",
            "-U", self._user or "", "-d", self._db or "",
        ]
        if csv_out:
            cmd.append("--csv")
        cmd += ["-c", sql]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
        except FileNotFoundError as exc:
            raise DbError("docker not found on PATH.") from exc
        except subprocess.TimeoutExpired as exc:
            raise DbError("psql call timed out.") from exc
        if proc.returncode != 0:
            raise DbError((proc.stderr or proc.stdout or "psql failed").strip())
        return proc.stdout

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        out = self._psql(render(sql, params), csv_out=True)
        reader = csv.DictReader(io.StringIO(out))
        # psql --csv emits empty strings for NULL; normalise to None.
        return [{k: (v if v != "" else None) for k, v in row.items()} for row in reader]

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        out = self._psql(render(sql, params), csv_out=False)
        match = None
        for line in out.splitlines():
            m = _TAG_RE.search(line.strip())
            if m:
                match = m
        return int(match.group(1)) if match else 0

    def close(self) -> None:
        pass


def connect_auto(config: Config) -> tuple[Db | None, list[str]]:
    """Try the resolved direct DSN first, then the docker-exec fallback.

    Returns the connected backend (or ``None`` when both fail) plus the log
    lines describing what happened. Each candidate is probed with a real query
    so a half-working path (port forwarded but stack down, docker present but
    stack stopped) is caught here rather than on the first command.
    """
    notes = list(config.notes)
    if config.database_url:
        from urllib.parse import urlsplit

        from .config import mask_dsn

        try:
            netloc = urlsplit(config.database_url).netloc.rpartition("@")[2]
        except ValueError:
            netloc = "?"
        try:
            db = DirectDb(config.database_url, label=f"direct {netloc}")
            db.query("SELECT 1")
        except DbError as exc:
            notes.append(f"direct {mask_dsn(config.database_url)}: {exc}")
        else:
            notes.append(f"connected · direct · {mask_dsn(config.database_url)}")
            return db, notes
    try:
        docker = DockerDb(config)
        docker.query("SELECT 1")
    except DbError as exc:
        notes.append(f"docker exec {config.service}: {exc}")
        return None, notes
    notes.append(f"connected · docker exec · {docker.label}")
    return docker, notes
