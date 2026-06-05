"""Metadata-Introspektion der T-10-Tabellen (magic_link, auth_session) — ohne DB."""

from __future__ import annotations

import app.models  # noqa: F401  — befüllt Base.metadata
from app.db import Base


def test_magic_link_and_auth_session_registered() -> None:
    assert {"magic_link", "auth_session"} <= set(Base.metadata.tables)


def test_magic_link_token_hash_is_binary_and_indexed() -> None:
    table = Base.metadata.tables["magic_link"]
    assert table.c.token_hash.type.python_type is bytes
    index_names = {i.name for i in table.indexes}
    assert "ix_magic_link_token_hash" in index_names


def test_magic_link_scope_check_and_cascade() -> None:
    table = Base.metadata.tables["magic_link"]
    checks = {c.name for c in table.constraints if c.name}
    assert "ck_magic_link_magic_link_scope" in checks
    fk = next(iter(table.c.application_id.foreign_keys))
    assert fk.column.table.name == "application"
    assert fk.ondelete == "CASCADE"


def test_auth_session_sid_unique_and_principal_cascade() -> None:
    table = Base.metadata.tables["auth_session"]
    assert table.c.sid.unique is True
    fk = next(iter(table.c.principal_id.foreign_keys))
    assert fk.column.table.name == "principal"
    assert fk.ondelete == "CASCADE"
