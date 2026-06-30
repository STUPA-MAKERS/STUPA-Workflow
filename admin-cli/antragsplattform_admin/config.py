"""Runtime configuration: how to reach the database.

Two backends (auto-selected):
- ``DATABASE_URL`` set → connect directly via psycopg (e.g. when run inside a container or with
  a published Postgres port).
- otherwise → ``docker compose -f <COMPOSE_FILE> exec -T <service> psql`` against the running
  stack (same model as ``scripts/remove-admin-role.sh``; no host port needed). Credentials are
  taken from ``POSTGRES_USER``/``POSTGRES_DB`` or, if unset, read from the container's env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_COMPOSE_FILE = "deploy/docker-compose.yml"
DEFAULT_SERVICE = "postgres"


@dataclass(frozen=True)
class Config:
    database_url: str | None
    compose_file: str
    service: str
    pg_user: str | None
    pg_db: str
    read_only: bool

    @property
    def direct(self) -> bool:
        return bool(self.database_url)

    @property
    def mode_label(self) -> str:
        return "direct (DATABASE_URL)" if self.direct else f"docker exec {self.service}"


def load(*, read_only: bool = False) -> Config:
    return Config(
        database_url=os.environ.get("DATABASE_URL") or None,
        compose_file=os.environ.get("COMPOSE_FILE", DEFAULT_COMPOSE_FILE),
        service=os.environ.get("POSTGRES_SERVICE", DEFAULT_SERVICE),
        pg_user=os.environ.get("POSTGRES_USER"),
        pg_db=os.environ.get("POSTGRES_DB", "antrag"),
        read_only=read_only,
    )
